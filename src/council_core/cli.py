"""``council`` command-line interface.

Subcommands:
  run       - convene the council on a brief and print the verdict markdown
  packs     - list available packs
  backends  - show configured backends and credential readiness
  models    - list Cursor models and per-persona resolution for a pack
  skill     - install the council skill for Cursor / Claude Code

The CLI (not the router) resolves an ambiguous route by asking the user.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from council_core import __version__
from council_core.config_loader import load_runtime_config, ready_backends
from council_core.format import render_json, render_markdown
from council_core.input import CouncilRequest
from council_core.model_resolve import resolve_council_models
from council_core.orchestrator import _load_all_packs, run_council
from council_core.pack import list_builtin_packs, load_pack
from council_core.roster import build_pack_council
from council_core.sdk_client import SdkUnavailableError, discover_models


def _read_brief(args) -> str:
    if args.brief and args.brief != "-":
        return args.brief
    return sys.stdin.read()


def _grounding_args(pairs: Optional[List[str]]) -> dict:
    out = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        if key:
            out[key.strip()] = value
    return out


def _fmt_params(params) -> str:
    if not params:
        return ""
    return " [" + ", ".join(f"{k}={v}" for k, v in params.items()) + "]"


def _cmd_run(args) -> int:
    config = load_runtime_config()
    packs = _load_all_packs(config)

    request = CouncilRequest(
        brief=_read_brief(args),
        cwd=args.cwd,
        mode=args.mode,
        stakes=args.stakes,
        pack=args.pack,
        pack_path=args.pack_path,
        dynamic=args.dynamic,
        roster=args.roster.split(",") if args.roster else None,
        peer_review_override=(True if args.peer_review else None),
        grounding_args=_grounding_args(args.ground),
        ui_model=args.ui_model,
        ui_backend=args.ui_backend,
        require_cursor=bool(getattr(args, "require_cursor", False)),
    )

    def _announce(text: str) -> None:
        print(text, file=sys.stderr)
        print("", file=sys.stderr)

    result, manifest = run_council(
        request, config=config, seed=args.seed, packs=packs, on_assignments=_announce
    )

    # Resolve an ambiguous route interactively (CLI's job, not the router's).
    if not result.convened and result.route and result.route.kind == "choice_required":
        if not sys.stdin.isatty() or args.non_interactive:
            _emit_result(result, as_json=args.json)
            print("\nNon-interactive: re-run with --pack <id> or --dynamic.", file=sys.stderr)
            return 2
        print(f"Routing is ambiguous ({result.route.reason}).")
        options = [c.pack_id for c in result.route.candidates] + ["dynamic"]
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        choice = input("Choose a pack number (or Enter for dynamic): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            picked = options[int(choice) - 1]
        else:
            picked = "dynamic"
        if picked == "dynamic":
            request.dynamic = True
        else:
            request.pack = picked
        result, manifest = run_council(
            request, config=config, seed=args.seed, packs=packs, on_assignments=_announce
        )

    _emit_result(result, as_json=args.json)

    if args.manifest and manifest is not None:
        Path(args.manifest).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        print(f"\n[manifest written to {args.manifest}]", file=sys.stderr)

    return 0 if result.convened and result.execution.status.value != "failed" else 1


def _emit_result(result, *, as_json: bool) -> None:
    text = render_json(result) if as_json else render_markdown(result)
    try:
        print(text, end="" if as_json else "\n")
    except UnicodeEncodeError:
        # Windows consoles are often cp1255/cp1252; never crash a finished run on glyphs.
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
        if not text.endswith("\n"):
            sys.stdout.buffer.write(b"\n")


def _configure_stdio() -> None:
    """Best-effort UTF-8 on Windows so verdict glyphs don't crash print()."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _cmd_packs(args) -> int:
    config = load_runtime_config()
    packs = _load_all_packs(config)
    print("Available packs:")
    for pid in list_builtin_packs():
        pack = packs.get(pid)
        if pack:
            print(
                f"  {pid} (v{pack.version}) — modes: {', '.join(pack.modes)}; "
                f"{len(pack.personas)} advisors; grounding: {pack.grounding.name}"
            )
        else:
            print(f"  {pid} — (failed to load)")
    return 0


def _cmd_backends(args) -> int:
    config = load_runtime_config()
    registry = config.registry()
    print("Backends (credentials from environment only):")
    for name, reason in sorted(ready_backends(config, registry).items()):
        print(f"  {name}: {'ready' if reason is None else 'NOT READY — ' + reason}")
    return 0


def _cmd_models(args) -> int:
    """List Cursor catalog models and optionally resolve a pack's roster against them."""

    config = load_runtime_config()
    registry = config.registry()

    available: List[str] = []
    catalog = {}
    discover_error: Optional[str] = None
    try:
        available, catalog = discover_models()
    except SdkUnavailableError as error:
        discover_error = str(error)
    except Exception as error:  # pragma: no cover - network/SDK flakiness
        discover_error = str(error)

    if discover_error:
        print(f"Cursor discovery unavailable: {discover_error}", file=sys.stderr)
        print(
            "Cascade will fall back to provider APIs or --ui-model / COUNCIL_UI_MODEL.",
            file=sys.stderr,
        )
    else:
        print(f"Models available to your Cursor key ({len(available)}):")
        for model_id in sorted(available):
            params = catalog.get(model_id) or {}
            if params:
                param_bits = ", ".join(
                    f"{pid}={{{','.join(sorted(vals))}}}" if vals else pid
                    for pid, vals in sorted(params.items())
                )
                print(f"  {model_id}  [{param_bits}]")
            else:
                print(f"  {model_id}")

    pack_id = args.pack or "dev_cursor"
    try:
        pack = load_pack(pack_id)
    except Exception as error:
        print(f"Could not load pack '{pack_id}': {error}", file=sys.stderr)
        return 1 if discover_error else 0

    mode = args.mode or pack.default_mode
    request = CouncilRequest(
        brief="(models dry-run)",
        pack=pack_id,
        mode=mode,
        stakes=args.stakes,
        ui_model=args.ui_model,
        ui_backend=args.ui_backend,
    )
    try:
        council = build_pack_council(pack, request)
    except Exception as error:
        print(f"Could not build roster for '{pack_id}': {error}", file=sys.stderr)
        return 1

    def _discover(_key):
        if discover_error is not None:
            raise SdkUnavailableError(discover_error)
        return available, catalog

    resolution = resolve_council_models(
        council,
        config,
        registry,
        ui_model=request.ui_model,
        ui_backend=request.ui_backend,
        discover=_discover,
    )

    print(
        f"\nPersona resolution for pack '{pack_id}' mode '{mode}' "
        f"(cascade tier: {resolution.tier}):"
    )
    available_set = set(available)
    for persona in council.advisors:
        if persona.backend != "cursor":
            mark = f"provider:{persona.backend}"
        elif discover_error:
            mark = "cursor-unresolved"
        elif persona.model in available_set:
            mark = "ok"
        else:
            mark = "fallback"
        print(
            f"  {persona.key}: {persona.model} @ {persona.backend} ({mark})"
            f"{_fmt_params(persona.model_params)}"
        )
    chair = council.chairman
    print(f"  chairman: {chair.model} @ {chair.backend}{_fmt_params(chair.model_params)}")
    if resolution.warnings:
        print("\nResolution warnings:")
        for warning in resolution.warnings:
            print(f"  - {warning}")
    return 0


def _cmd_skill_install(args) -> int:
    from council_core.skill_install import describe_manual_steps, install_skill

    cursor = bool(args.cursor or args.all_assistants)
    claude = bool(args.claude or args.all_assistants)
    if not cursor and not claude:
        cursor = claude = True  # default: both

    personal = bool(args.personal)
    project = bool(args.project)
    if not personal and not project:
        personal = True  # default: personal scope

    try:
        installed, notes = install_skill(
            cursor=cursor,
            claude=claude,
            personal=personal,
            project=project,
            project_root=Path(args.project_root) if args.project_root else None,
        )
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        print(describe_manual_steps(), file=sys.stderr)
        return 1

    for note in notes:
        print(note)
    if not installed:
        print(describe_manual_steps(), file=sys.stderr)
        return 1
    return 0


def _cmd_usage(args) -> int:
    import json

    from council_core.config_loader import load_runtime_config
    from council_core.metering import USAGE_LOG_PATH, summarize

    summary = summarize(month=args.month)
    config = load_runtime_config()
    ceiling = int(float(config.budget.get("monthly_agent_run_ceiling", 600) or 600))
    warn_fraction = float(config.budget.get("warn_fraction", 0.6) or 0.6)
    warn_at = int(ceiling * warn_fraction)
    runs = int(summary["runs_this_month"])

    if args.json:
        payload = dict(summary)
        payload["budget"] = {"monthly_ceiling": ceiling, "warn_at": warn_at, "warn_fraction": warn_fraction}
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Usage log: {USAGE_LOG_PATH}")
    print(f"Month: {summary['month']}")
    print(f"Agent runs this month: {runs} / {ceiling} (soft ceiling)")
    print(f"All-time recorded rows: {summary['total_runs_all_time']}")
    print(f"Agent time this month: {int(summary['total_duration_ms']) / 1000:.1f}s")
    if summary["by_model"]:
        print("By model:")
        for model, count in summary["by_model"].items():
            print(f"  {model}: {count}")
    if summary["by_stage"]:
        print("By stage:", ", ".join(f"{k}={v}" for k, v in summary["by_stage"].items()))
    if summary.get("by_backend"):
        print("By backend:", ", ".join(f"{k}={v}" for k, v in summary["by_backend"].items()))
    if summary["by_status"]:
        print("By status:", ", ".join(f"{k}={v}" for k, v in summary["by_status"].items()))

    if runs >= warn_at:
        print(
            f"\nWARNING: {runs} runs this month is past the {int(warn_fraction * 100)}% soft ceiling "
            f"({warn_at}/{ceiling}).",
            file=sys.stderr,
        )
    return 0


def _cmd_pack_draft(args) -> int:
    from council_core.pack import PackError
    from council_core.pack_promote import draft_pack_from_manifest, load_manifest

    try:
        manifest = load_manifest(args.manifest_or_run_id)
        dest = draft_pack_from_manifest(
            manifest,
            args.out,
            pack_id=args.pack_id,
        )
    except (PackError, OSError, ValueError) as error:
        print(f"draft-from-run failed: {error}", file=sys.stderr)
        return 1
    print(f"Draft pack written to {dest}")
    print("This is DRAFT-ONLY — run `council pack validate` then human-review before trusting.")
    return 0


def _cmd_pack_validate(args) -> int:
    from council_core.pack import PackError
    from council_core.pack_promote import validate_draft_pack

    try:
        status = validate_draft_pack(args.path)
    except (PackError, Exception) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(status)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(prog="council", description="Generic multi-model council.")
    parser.add_argument("--version", action="version", version=f"council-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="convene the council on a brief")
    run.add_argument("brief", nargs="?", default="-", help="the brief text, or '-' for stdin")
    run.add_argument("--pack", help="force a pack id (dev/finance/career/dev_cursor/...)")
    run.add_argument("--pack-path", help="path to an external pack directory")
    run.add_argument("--dynamic", action="store_true", help="force a dynamically generated council")
    run.add_argument("--mode", help="pack mode (e.g. review/plan)")
    run.add_argument("--stakes", default="standard", help="stakes tier (default: standard)")
    run.add_argument("--roster", help="comma-separated advisor keys (pack rosters only)")
    run.add_argument("--peer-review", action="store_true", help="force peer review on")
    run.add_argument("--cwd", default=".", help="working directory for grounding")
    run.add_argument("--ground", action="append", help="grounding arg key=value (repeatable)")
    run.add_argument("--seed", type=int, help="RNG seed (anonymization/pairing)")
    run.add_argument("--manifest", help="write the run manifest JSON to this path")
    run.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON result on stdout (for skills)",
    )
    run.add_argument(
        "--non-interactive", action="store_true", help="never prompt; fail on ambiguous route"
    )
    run.add_argument(
        "--ui-model",
        help="cascade Priority C: skill UI model id when Cursor + provider APIs are unavailable "
        "(also COUNCIL_UI_MODEL)",
    )
    run.add_argument(
        "--ui-backend",
        help="backend for --ui-model (default: first ready provider, or COUNCIL_UI_BACKEND)",
    )
    run.add_argument(
        "--require-cursor",
        action="store_true",
        help="refuse provider/UI fallback when a Cursor-backed roster cannot use Cursor",
    )
    run.set_defaults(func=_cmd_run)

    p = sub.add_parser("packs", help="list available packs")
    p.set_defaults(func=_cmd_packs)

    b = sub.add_parser("backends", help="show backend credential readiness")
    b.set_defaults(func=_cmd_backends)

    m = sub.add_parser("models", help="list Cursor models and persona resolution")
    m.add_argument("--pack", default="dev_cursor", help="pack to resolve (default: dev_cursor)")
    m.add_argument("--mode", help="pack mode (default: pack default)")
    m.add_argument("--stakes", default="standard", help="stakes tier for roster selection")
    m.add_argument("--ui-model", help="Priority C UI model for cascade preview")
    m.add_argument("--ui-backend", help="backend for --ui-model")
    m.set_defaults(func=_cmd_models)

    sk = sub.add_parser("skill", help="install the council skill for Cursor / Claude Code")
    sk_sub = sk.add_subparsers(dest="skill_command", required=True)
    sk_install = sk_sub.add_parser("install", help="copy skills/council into assistant skill dirs")
    sk_install.add_argument(
        "--cursor", action="store_true", default=False, help="install for Cursor"
    )
    sk_install.add_argument(
        "--claude", action="store_true", default=False, help="install for Claude Code"
    )
    sk_install.add_argument(
        "--all",
        dest="all_assistants",
        action="store_true",
        help="install for both Cursor and Claude Code (default if neither flag set)",
    )
    sk_install.add_argument(
        "--personal",
        action="store_true",
        default=False,
        help="install under ~/.cursor/skills and/or ~/.claude/skills",
    )
    sk_install.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="install under <cwd>/.cursor/skills and/or <cwd>/.claude/skills",
    )
    sk_install.add_argument(
        "--project-root",
        help="project root for --project (default: cwd)",
    )
    sk_install.set_defaults(func=_cmd_skill_install)

    u = sub.add_parser("usage", help="summarize metered usage and soft budget")
    u.add_argument("--month", help="Month as YYYY-MM (default: current UTC month)")
    u.add_argument("--json", action="store_true", help="Emit raw JSON summary")
    u.set_defaults(func=_cmd_usage)

    pk = sub.add_parser("pack", help="draft/validate packs")
    pk_sub = pk.add_subparsers(dest="pack_command", required=True)
    pk_draft = pk_sub.add_parser(
        "draft-from-run",
        help="promote a run manifest into a DRAFT pack (never auto-trusted)",
    )
    pk_draft.add_argument("manifest_or_run_id", help="manifest JSON path or run id")
    pk_draft.add_argument("--out", required=True, help="empty destination directory for the draft")
    pk_draft.add_argument("--pack-id", help="override draft pack id")
    pk_draft.set_defaults(func=_cmd_pack_draft)

    pk_val = pk_sub.add_parser("validate", help="validate a pack directory")
    pk_val.add_argument("path", help="path to a pack directory containing pack.yaml")
    pk_val.set_defaults(func=_cmd_pack_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
