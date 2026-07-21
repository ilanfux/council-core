"""``council`` command-line interface.

Subcommands:
  run       - convene the council on a brief and print the verdict markdown
  packs     - list available packs
  backends  - show configured backends and credential readiness

The CLI (not the router) resolves an ambiguous route by asking the user.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from council_core import __version__
from council_core.config_loader import load_runtime_config, ready_backends
from council_core.format import render_markdown
from council_core.input import CouncilRequest
from council_core.manifest import RunManifest
from council_core.orchestrator import _load_all_packs, run_council
from council_core.pack import list_builtin_packs


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
    )

    result, manifest = run_council(request, config=config, seed=args.seed, packs=packs)

    # Resolve an ambiguous route interactively (CLI's job, not the router's).
    if not result.convened and result.route and result.route.kind == "choice_required":
        if not sys.stdin.isatty() or args.non_interactive:
            print(render_markdown(result))
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
        result, manifest = run_council(request, config=config, seed=args.seed, packs=packs)

    print(render_markdown(result))

    if args.manifest and manifest is not None:
        Path(args.manifest).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        print(f"\n[manifest written to {args.manifest}]", file=sys.stderr)

    return 0 if result.convened and result.execution.status.value != "failed" else 1


def _cmd_packs(args) -> int:
    config = load_runtime_config()
    packs = _load_all_packs(config)
    print("Available packs:")
    for pid in list_builtin_packs():
        pack = packs.get(pid)
        if pack:
            print(f"  {pid} (v{pack.version}) — modes: {', '.join(pack.modes)}; "
                  f"{len(pack.personas)} advisors; grounding: {pack.grounding.name}")
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="council", description="Generic multi-model council.")
    parser.add_argument("--version", action="version", version=f"council-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="convene the council on a brief")
    run.add_argument("brief", nargs="?", default="-", help="the brief text, or '-' for stdin")
    run.add_argument("--pack", help="force a pack id (dev/finance/career/...)")
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
    run.add_argument("--non-interactive", action="store_true", help="never prompt; fail on ambiguous route")
    run.set_defaults(func=_cmd_run)

    p = sub.add_parser("packs", help="list available packs")
    p.set_defaults(func=_cmd_packs)

    b = sub.add_parser("backends", help="show backend credential readiness")
    b.set_defaults(func=_cmd_backends)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
