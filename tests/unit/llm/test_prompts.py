from __future__ import annotations

from pathlib import Path

import pytest

from mentora.llm.prompts import PromptError, PromptRegistry, default_registry


def _write(root: Path, pid: str, version: int, body: str) -> None:
    folder = root / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"v{version}.md").write_text(body, encoding="utf-8")


TEMPLATE = """---
description: test
---
## system
You tutor $course.
## user
Question: $question {"json": "braces are fine"}
"""


def test_latest_version_and_render(tmp_path: Path) -> None:
    _write(tmp_path, "agent/x", 1, TEMPLATE.replace("tutor", "teach"))
    _write(tmp_path, "agent/x", 2, TEMPLATE)
    reg = PromptRegistry(tmp_path)
    assert reg.versions("agent/x") == [1, 2]
    rendered = reg.get("agent/x").render(course="SYN101", question="why?")
    assert rendered.tag == "agent/x@v2"
    assert rendered.system == "You tutor SYN101."
    assert rendered.user == 'Question: why? {"json": "braces are fine"}'
    assert reg.get("agent/x", 1).render(course="c", question="q").system == "You teach c."


def test_missing_value_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "a", 1, TEMPLATE)
    with pytest.raises(PromptError, match="missing value"):
        PromptRegistry(tmp_path).get("a").render(course="c")


def test_unknown_prompt_and_version(tmp_path: Path) -> None:
    _write(tmp_path, "a", 1, TEMPLATE)
    reg = PromptRegistry(tmp_path)
    with pytest.raises(PromptError):
        reg.get("missing")
    with pytest.raises(PromptError):
        reg.get("a", 9)


def test_shipped_prompts_parse() -> None:
    reg = default_registry()
    for pid in ("rag/answer", "rag/answer_no_retrieval", "rag/entailment_judge"):
        assert reg.get(pid).version >= 1
