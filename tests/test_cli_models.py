"""CLI `council models` — offline with a stubbed discover_models."""

from __future__ import annotations

from council_core.cli import main
from council_core.sdk_client import SdkUnavailableError


def test_models_cmd_with_mocked_catalog(monkeypatch, capsys):
    catalog = {
        "gpt-5.5": {"reasoning": {"high", "low"}},
        "composer-2.5": {},
        "claude-sonnet-4-6": {"effort": {"high"}, "thinking": {"true", "false"}},
        "gpt-5.3-codex": {"reasoning": {"high"}, "fast": {"true", "false"}},
        "gpt-5.4": {},
        "claude-opus-4-8": {"effort": {"xhigh"}, "thinking": {"true"}},
        "gemini-3.1-pro": {},
    }

    def fake_discover(api_key=None):
        return list(catalog), catalog

    monkeypatch.setattr("council_core.cli.discover_models", fake_discover)
    rc = main(["models", "--pack", "dev_cursor", "--mode", "review", "--stakes", "standard"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Models available to your Cursor key" in out
    assert "gpt-5.5" in out
    assert "Persona resolution for pack 'dev_cursor'" in out
    assert "cascade tier: cursor" in out
    assert "bug_hunter:" in out
    assert "chairman:" in out


def test_models_cmd_graceful_without_cursor(monkeypatch, capsys):
    def boom(api_key=None):
        raise SdkUnavailableError("CURSOR_API_KEY is not set")

    monkeypatch.setattr("council_core.cli.discover_models", boom)
    # Provide ui-model so cascade lands on Priority C instead of leaving cursor unresolved
    rc = main(
        [
            "models",
            "--pack",
            "dev_cursor",
            "--stakes",
            "standard",
            "--ui-model",
            "composer-2.5",
            "--ui-backend",
            "cursor",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Cursor discovery unavailable" in captured.err
    assert "cascade tier: ui" in captured.out or "cascade tier: providers" in captured.out
