"""Portable usage metering.

Every agent run (advisor, peer reviewer, chairman) appends one JSONL row to
``~/.council/usage.jsonl``. It never blocks or breaks a council run and requires
no server.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from council_core.input import AgentOutcome

USER_DATA_DIR = Path(os.path.expanduser("~")) / ".council"
USAGE_LOG_PATH = USER_DATA_DIR / "usage.jsonl"


@dataclass
class MeteringSink:
    """Collects per-run usage rows for one council invocation."""

    pack: str
    stakes: str
    log_path: Path = USAGE_LOG_PATH

    def record(
        self,
        stage: str,
        persona_key: str,
        model: str,
        family: str,
        outcome: AgentOutcome,
        backend: str = "cursor",
    ) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pack": self.pack,
            "stakes": self.stakes,
            "stage": stage,  # advisor | peer | chairman
            "persona": persona_key,
            "backend": backend,
            "model": model,
            "actual_model": outcome.actual_model,
            "family": family,
            "status": outcome.status,
            "run_id": outcome.run_id,
            "duration_ms": outcome.duration_ms,
            "error": outcome.error_message,
        }
        self._append_jsonl(row)

    def _append_jsonl(self, row: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        except Exception:
            # Metering must never break a council run.
            pass


def summarize(log_path: Path = USAGE_LOG_PATH, month: Optional[str] = None) -> Dict[str, object]:
    """Aggregate the usage log. ``month`` is 'YYYY-MM'; defaults to current month."""

    current_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    rows = _read_rows(log_path)
    month_rows = [r for r in rows if str(r.get("ts", "")).startswith(current_month)]

    by_model: Dict[str, int] = {}
    by_stage: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_backend: Dict[str, int] = {}
    total_duration_ms = 0
    for row in month_rows:
        by_model[row.get("model", "?")] = by_model.get(row.get("model", "?"), 0) + 1
        by_stage[row.get("stage", "?")] = by_stage.get(row.get("stage", "?"), 0) + 1
        by_status[row.get("status", "?")] = by_status.get(row.get("status", "?"), 0) + 1
        by_backend[row.get("backend", "?")] = by_backend.get(row.get("backend", "?"), 0) + 1
        total_duration_ms += int(row.get("duration_ms") or 0)

    return {
        "month": current_month,
        "total_runs_all_time": len(rows),
        "runs_this_month": len(month_rows),
        "by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
        "by_stage": by_stage,
        "by_status": by_status,
        "by_backend": by_backend,
        "total_duration_ms": total_duration_ms,
    }


def _read_rows(log_path: Path) -> List[dict]:
    if not log_path.exists():
        return []
    rows: List[dict] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return rows
    return rows
