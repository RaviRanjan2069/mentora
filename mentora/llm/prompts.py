"""Versioned prompt templates (files, not strings in code).

Layout: ``mentora/prompts/<prompt id>/v<N>.md`` where the file is

    ---
    description: one line
    ---
    ## system
    ...
    ## user
    ... $placeholders ...

Placeholders use ``string.Template`` syntax (``$name`` / ``${name}``) so JSON braces in
prompts need no escaping. A missing placeholder value is an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_VERSION_RE = re.compile(r"^v(\d+)\.md$")
_SECTION_RE = re.compile(r"^## (system|user)\s*$", re.MULTILINE)


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    description: str
    system: Template
    user: Template

    @property
    def tag(self) -> str:
        return f"{self.id}@v{self.version}"

    def render(self, **values: object) -> RenderedPrompt:
        text = {k: str(v) for k, v in values.items()}
        try:
            return RenderedPrompt(
                id=self.id,
                version=self.version,
                system=self.system.substitute(text).strip(),
                user=self.user.substitute(text).strip(),
            )
        except KeyError as exc:
            raise PromptError(f"{self.id}@v{self.version}: missing value {exc}") from exc


@dataclass(frozen=True)
class RenderedPrompt:
    id: str
    version: int
    system: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.id}@v{self.version}"


def _parse(prompt_id: str, version: int, raw: str) -> PromptTemplate:
    if not raw.startswith("---"):
        raise PromptError(f"{prompt_id}@v{version}: missing front matter")
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front) or {}
    parts = _SECTION_RE.split(body)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    if "system" not in sections or "user" not in sections:
        raise PromptError(f"{prompt_id}@v{version}: needs '## system' and '## user' sections")
    return PromptTemplate(
        id=prompt_id,
        version=version,
        description=str(meta.get("description", "")),
        system=Template(sections["system"]),
        user=Template(sections["user"]),
    )


class PromptRegistry:
    def __init__(self, root: Path = PROMPTS_DIR) -> None:
        self.root = root

    def versions(self, prompt_id: str) -> list[int]:
        folder = self.root / prompt_id
        if not folder.is_dir():
            raise PromptError(f"unknown prompt {prompt_id!r}")
        found = [_VERSION_RE.match(p.name) for p in folder.iterdir()]
        return sorted(int(m.group(1)) for m in found if m)

    def _read(self, prompt_id: str, version: int | None) -> tuple[int, str]:
        available = self.versions(prompt_id)
        if not available:
            raise PromptError(f"prompt {prompt_id!r} has no versions")
        v = available[-1] if version is None else version
        if v not in available:
            raise PromptError(f"prompt {prompt_id!r} has no v{v}")
        return v, (self.root / prompt_id / f"v{v}.md").read_text(encoding="utf-8")

    def get(self, prompt_id: str, version: int | None = None) -> PromptTemplate:
        v, raw = self._read(prompt_id, version)
        return _parse(prompt_id, v, raw)

    def fragment(self, fragment_id: str, version: int | None = None) -> Fragment:
        """A reusable piece of prompt text (front matter + plain body, no sections)."""
        v, raw = self._read(fragment_id, version)
        if not raw.startswith("---"):
            raise PromptError(f"{fragment_id}@v{v}: missing front matter")
        _, _front, body = raw.split("---", 2)
        return Fragment(id=fragment_id, version=v, text=body.strip())


@dataclass(frozen=True)
class Fragment:
    id: str
    version: int
    text: str

    @property
    def tag(self) -> str:
        return f"{self.id}@v{self.version}"


@lru_cache(maxsize=1)
def default_registry() -> PromptRegistry:
    return PromptRegistry()
