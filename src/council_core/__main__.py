"""Enable ``python -m council_core`` once the CLI lands (Phase 1)."""

from council_core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
