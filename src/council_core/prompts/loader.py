"""PromptSet: prompt templates loaded from files, not hardcoded.

A pack supplies a ``prompts/`` directory that overrides the base templates in
``council_core/prompts/base/``. Templates are versioned by content hash so the
run manifest can record exactly which template produced a prompt.

Placeholders use ``str.format`` with named fields. Templates:
  - ``advisor.txt``  : {title} {prompt} {brief} {mode} {grounding} {read_rule} {extra}
  - ``peer.txt``     : {n} {brief} {anonymized}
  - ``chairman.txt`` : {brief} {advisor_block} {peer_block} {verdict_skeleton}
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List

from council_core.input import AdvisorResult, PersonaSpec

_BASE_DIR = Path(__file__).parent / "base"
_TEMPLATES = ("advisor.txt", "peer.txt", "chairman.txt")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class PromptSet:
    """Holds the three templates + their version hashes for one pack."""

    def __init__(self, templates: Dict[str, str]) -> None:
        self._t = templates
        self.versions: Dict[str, str] = {name: _hash(text) for name, text in templates.items()}

    @classmethod
    def load(cls, pack_prompts_dir: Path | None) -> "PromptSet":
        templates: Dict[str, str] = {}
        for name in _TEMPLATES:
            text: str | None = None
            if pack_prompts_dir is not None:
                candidate = pack_prompts_dir / name
                if candidate.is_file():
                    text = candidate.read_text(encoding="utf-8")
            if text is None:
                base = _BASE_DIR / name
                text = base.read_text(encoding="utf-8")
            templates[name] = text
        return cls(templates)

    # -- builders ---------------------------------------------------------

    def build_advisor(
        self,
        persona: PersonaSpec,
        brief: str,
        mode: str,
        grounded: bool,
        grounding_text: str,
        read_rule: str,
        extra: str = "",
    ) -> str:
        grounding = (
            "Working directory: the material you can read with your tools."
            if grounded
            else f"Evidence provided (cite strictly from it):\n{grounding_text}"
        )
        return self._t["advisor.txt"].format(
            title=persona.title,
            prompt=persona.prompt,
            brief=brief,
            mode=(mode or "").upper() or "ADVISE",
            grounding=grounding,
            read_rule=read_rule,
            extra=extra,
        )

    def build_peer(self, brief: str, anonymized_map: Dict[str, str]) -> str:
        anonymized = "\n\n".join(f"**{letter}:** {text}" for letter, text in anonymized_map.items())
        return self._t["peer.txt"].format(n=len(anonymized_map), brief=brief, anonymized=anonymized)

    def build_chairman(
        self,
        brief: str,
        advisors: List[AdvisorResult],
        peer_reviews: List[str],
        verdict_skeleton: str,
    ) -> str:
        advisor_block = "\n\n".join(
            f"### {a.persona.title} (model: {a.persona.model})\n{a.outcome.text.strip()}"
            for a in advisors
            if a.outcome.ok
        ) or "(no advisor produced a usable response)"
        peer_block = (
            "\n\n".join(f"- {t.strip()}" for t in peer_reviews if t.strip())
            if peer_reviews
            else "(peer review not run for this tier)"
        )
        return self._t["chairman.txt"].format(
            brief=brief,
            advisor_block=advisor_block,
            peer_block=peer_block,
            verdict_skeleton=verdict_skeleton,
        )
