"""Reads the Markdown skills straight from the repository.

The three skill folders are the single source of truth for the tool's
behaviour: edit a Markdown file, redeploy, and every module that cites it gets
smarter. Nothing here hardcodes strategy.

Progressive disclosure: a module loads its skill's SKILL.md plus only the
reference files it actually needs, which keeps prompts sharp and cheap.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import settings

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillDoc:
    name: str
    description: str
    body: str
    references: dict[str, str]


class SkillRegistry:
    """Loads and caches the skill folders found at the repository root."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or settings.skills_dir
        self._cache: dict[str, SkillDoc] = {}
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def available(self) -> list[str]:
        return sorted(
            p.parent.name for p in self._root.glob("*/SKILL.md") if p.parent.name != "backend"
        )

    def load(self, name: str) -> SkillDoc:
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            doc = self._read(name)
            self._cache[name] = doc
            return doc

    def reload(self) -> None:
        with self._lock:
            self._cache.clear()

    def _read(self, name: str) -> SkillDoc:
        skill_path = self._root / name / "SKILL.md"
        if not skill_path.is_file():
            raise FileNotFoundError(f"skill not found: {name}")

        raw = skill_path.read_text(encoding="utf-8")
        description = ""
        body = raw
        if match := _FRONTMATTER.match(raw):
            body = raw[match.end():]
            fm = match.group(1)
            if desc := re.search(r"^description:\s*(.*)$", fm, re.MULTILINE):
                description = desc.group(1).strip().strip("|").strip()

        references: dict[str, str] = {}
        for folder in ("references", "assets"):
            base = self._root / name / folder
            if not base.is_dir():
                continue
            for ref in sorted(base.glob("*.md")):
                references[f"{folder}/{ref.name}"] = ref.read_text(encoding="utf-8")

        return SkillDoc(name=name, description=description, body=body.strip(), references=references)

    def compose(self, skill: str, refs: list[str]) -> str:
        """SKILL.md followed by the requested reference files, in a stable order.

        Stability matters: this string is the cached prompt prefix, and any byte
        that moves invalidates the cache for every request behind it.
        """
        doc = self.load(skill)
        parts = [f"# SKILL: {doc.name}\n\n{doc.body}"]
        for ref in refs:
            key = ref if "/" in ref else f"references/{ref}"
            if content := doc.references.get(key):
                parts.append(f"\n\n---\n\n# REFERENCE FILE: {key}\n\n{content.strip()}")
            else:
                available = ", ".join(sorted(doc.references)) or "none"
                raise KeyError(f"{skill}: missing reference {key!r} (has: {available})")
        return "\n".join(parts)


registry = SkillRegistry()
