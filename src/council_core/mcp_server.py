"""Local MCP server exposing council-core to MCP clients (Claude Desktop, etc.).

Runs where your API keys and packs live and does the real multi-model dispatch;
the client only sends a brief and receives a verdict. Diversity is preserved —
this is NOT the host chat model role-playing personas.

Design notes:
- Tools are defined as plain sync functions (``_convene`` / ``_list_packs`` /
  ``_check_backends``) so they're unit-testable WITHOUT the ``mcp`` package, and
  so FastMCP runs them in a worker thread. Sync is deliberate: ``run_council``
  may drive the Cursor SDK via ``asyncio.run()``, which would raise if called
  from inside FastMCP's own event loop. Running off-loop avoids that nested-loop
  trap (the MCP-side extension of the Windows-Proactor gotcha).
- Secrets never leave the server: the client only ever sees briefs and verdicts.

Install: ``pip install 'council-core[mcp]'``. Run: ``council-mcp`` (stdio).
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from council_core.config_loader import load_runtime_config, ready_backends
from council_core.format import result_to_dict
from council_core.input import CouncilRequest
from council_core.orchestrator import run_council
from council_core.pack import list_builtin_packs, load_pack

# Injectable seam so tests exercise the tool logic with a fake runner.
RunFn = Callable[[CouncilRequest], tuple]


def _build_grounding_args(
    documents: Optional[List[str]],
    inline_documents: Optional[Dict[str, str]],
    tmp_holder: List[str],
) -> Dict[str, str]:
    """Return grounding_args; stage inline docs to a temp dir (recorded for cleanup)."""

    lines: List[str] = list(documents or [])
    if inline_documents:
        tmpdir = tempfile.mkdtemp(prefix="council_mcp_docs_")
        tmp_holder.append(tmpdir)
        for name, text in inline_documents.items():
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(name)).strip("_") or "doc"
            path = Path(tmpdir) / f"{safe}.md"
            path.write_text(str(text), encoding="utf-8")
            lines.append(f"{name}::{path}")
    return {"documents": "\n".join(lines)} if lines else {}


def _convene(
    brief: str,
    pack: Optional[str] = None,
    mode: Optional[str] = None,
    stakes: str = "standard",
    dynamic: bool = False,
    cwd: str = ".",
    documents: Optional[List[str]] = None,
    inline_documents: Optional[Dict[str, str]] = None,
    require_cursor: bool = False,
    _run: RunFn = run_council,
) -> dict:
    """Convene a council on ``brief`` and return the verdict (markdown + structured).

    A ``choice_required`` route is returned as structured data — the caller picks a
    pack and re-invokes; the server never prompts.
    """

    tmp_dirs: List[str] = []
    try:
        grounding_args = _build_grounding_args(documents, inline_documents, tmp_dirs)
        request = CouncilRequest(
            brief=brief,
            cwd=cwd,
            mode=mode,
            stakes=stakes,
            pack=pack,
            dynamic=dynamic,
            grounding_args=grounding_args,
            require_cursor=require_cursor,
        )
        result, _manifest = _run(request)
        return result_to_dict(result)
    finally:
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


def _list_packs() -> List[dict]:
    """List available packs with their modes and grounding, so the caller can choose."""

    out: List[dict] = []
    for pid in list_builtin_packs():
        try:
            p = load_pack(pid)
        except Exception as error:  # a broken pack should not sink discovery
            out.append({"id": pid, "error": str(error)})
            continue
        out.append(
            {
                "id": p.id,
                "version": p.version,
                "display_name": p.display_name,
                "modes": list(p.modes),
                "default_mode": p.default_mode,
                "advisors": len(p.personas),
                "grounding": getattr(p.grounding, "name", ""),
            }
        )
    return out


def _check_backends() -> Dict[str, str]:
    """Report which execution backends have credentials ready."""

    config = load_runtime_config()
    registry = config.registry()
    return {
        name: ("ready" if reason is None else reason)
        for name, reason in ready_backends(config, registry).items()
    }


def build_server():
    """Construct the FastMCP server. Imports ``mcp`` lazily so the module stays
    importable (and testable) without the optional dependency."""

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as error:  # pragma: no cover - optional dep
        raise SystemExit(
            "The MCP server needs the 'mcp' package: pip install 'council-core[mcp]'.\n"
            f"(import error: {error})"
        )

    server = FastMCP("council")

    @server.tool()
    def convene_council(
        brief: str,
        pack: Optional[str] = None,
        mode: Optional[str] = None,
        stakes: str = "standard",
        dynamic: bool = False,
        cwd: str = ".",
        documents: Optional[List[str]] = None,
        inline_documents: Optional[Dict[str, str]] = None,
        require_cursor: bool = False,
    ) -> dict:
        """Convene a multi-model council on a brief and return its verdict.

        brief: the question/decision/change to deliberate on.
        pack: dev|finance|career|travel (+ *_cursor); omit to auto-route.
        mode: pack-specific focus (e.g. review|plan, resume|strategy, food|route).
        stakes: quick|standard|thorough (thorough adds specialists + peer review).
        dynamic: true to synthesize a bespoke roster for a novel topic.
        cwd: working dir for repo/document grounding.
        documents: list of "label::/abs/path" evidence files.
        inline_documents: {name: text} evidence passed inline (staged server-side).
        require_cursor: fail instead of downgrading if the Cursor packs can't reach Cursor.
        """

        return _convene(
            brief=brief, pack=pack, mode=mode, stakes=stakes, dynamic=dynamic,
            cwd=cwd, documents=documents, inline_documents=inline_documents,
            require_cursor=require_cursor,
        )

    @server.tool()
    def list_packs() -> List[dict]:
        """List available council packs, their modes, and grounding."""

        return _list_packs()

    @server.tool()
    def check_backends() -> Dict[str, str]:
        """Report which model backends have credentials ready on this server."""

        return _check_backends()

    return server


# --------------------------------------------------------------------------- #
# Remote / HTTP transport (for the Claude mobile app via a custom connector)    #
# --------------------------------------------------------------------------- #
#
# WARNING: exposing this to the internet runs the council on YOUR keys for anyone
# who can reach it — always require the bearer token, and never bind 0.0.0.0
# without a tunnel/proxy in front. The auth logic below is unit-tested; the ASGI
# wiring needs the live ``mcp`` + ``uvicorn`` stack and is verified at runtime.

def _token_from_env() -> Optional[str]:
    return (os.environ.get("COUNCIL_MCP_TOKEN") or "").strip() or None


def _authorized(auth_header: Optional[str], token: str) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header."""

    if not token or not auth_header:
        return False
    scheme, _, value = auth_header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return False
    return secrets.compare_digest(value.strip(), token)


def build_http_app(token: str):  # pragma: no cover - needs mcp + starlette
    """FastMCP streamable-HTTP ASGI app, gated by a bearer-token middleware."""

    server = build_server()
    try:
        app = server.streamable_http_app()
    except AttributeError:  # API name differs across mcp versions
        app = server.http_app()

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class _BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if not _authorized(request.headers.get("authorization"), token):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(_BearerAuth)
    return app


def run_http(host: str = "127.0.0.1", port: int = 8787) -> None:  # pragma: no cover - live server
    token = _token_from_env()
    if not token:
        raise SystemExit(
            "Refusing to serve HTTP without auth: set COUNCIL_MCP_TOKEN to a strong secret."
        )
    import uvicorn

    uvicorn.run(build_http_app(token), host=host, port=port)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="council-mcp", description="Council MCP server.")
    parser.add_argument("--http", action="store_true",
                        help="serve over HTTP for a remote connector (needs COUNCIL_MCP_TOKEN)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="HTTP bind host (default 127.0.0.1; keep local, put a tunnel in front)")
    parser.add_argument("--port", type=int, default=8787, help="HTTP port (default 8787)")
    args = parser.parse_args(argv)

    if args.http:
        run_http(host=args.host, port=args.port)
    else:
        build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
