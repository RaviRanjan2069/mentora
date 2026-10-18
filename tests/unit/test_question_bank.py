"""The generated 1000-question bank: shape, and every answer key re-checked independently by
re-running the question text as it is stored in data/sample/question_bank.yaml."""

from __future__ import annotations

import io
import keyword
import re
from collections import Counter
from pathlib import Path

import pytest

from mentora.course import load_course, load_items
from mentora.question_bank import generate_bank, raised

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "data" / "sample" / "question_bank.yaml"
OPTION = re.compile(r"^\(([A-D])\) (.+)$")


def _parse(text: str) -> tuple[str, str, dict[str, str]]:
    lines = text.split("\n")
    options = {m[1]: m[2] for line in lines if (m := OPTION.match(line))}
    body = [line for line in lines if not OPTION.match(line)]
    return body[0], "\n".join(body[1:]), options


def _env(stem: str, code: str) -> dict[str, object]:
    env: dict[str, object] = {}
    typed = re.search(r"The user types (\S+)\.", stem)
    if typed:
        env["input"] = lambda *_: typed[1]
    content = "".join(f"{m[1]}\n" for m in re.finditer(r"^#   (\S+)$", code, re.MULTILINE))
    env["open"] = lambda name, mode="r", *a, **k: io.StringIO("" if "w" in mode else content)
    return env


def test_bank_file_is_current_and_well_formed() -> None:
    items = load_items(BANK)
    assert len(items) == 1000
    course = {c.key for c in load_course(ROOT / "data" / "concepts.yaml").concepts}
    per_concept = Counter(i.concepts[0] for i in items)
    assert set(per_concept) == course and set(per_concept.values()) == {50}
    assert len({i.external_id for i in items}) == 1000
    assert len({i.text for i in items}) == 1000
    assert sum(i.graded for i in items) == 200
    regenerated = generate_bank()
    assert [r["text"] for r in regenerated] == [i.text for i in items], "re-run the generator"
    for item in items:
        _, _, options = _parse(item.text)
        assert item.item_type == "mcq" and sorted(options) == ["A", "B", "C", "D"], item.external_id
        assert len(set(options.values())) == 4, item.external_id
        assert item.answer_key in options, item.external_id


@pytest.mark.parametrize("item", load_items(BANK), ids=lambda i: i.external_id)
def test_answer_key_is_right(item: object) -> None:
    stem, code, options = _parse(item.text)  # type: ignore[attr-defined]
    expected = options[item.answer_key]  # type: ignore[attr-defined]
    if "valid Python variable name" in stem:
        valid = {k: v.isidentifier() and not keyword.iskeyword(v) for k, v in options.items()}
        want = "NOT" not in stem
        assert [k for k, ok in valid.items() if ok == want] == [item.answer_key]  # type: ignore[attr-defined]
        return
    if "time complexity" in stem or not (code or "evaluate to" in stem or "type" in stem):
        pytest.skip("conceptual question (fact or Big-O), checked by review")
    if code:
        actual = raised(code, _env(stem, code))
    elif m := re.match(r"What does (.+) evaluate to\?$", stem):
        value = eval(m[1])
        actual = str(round(value, 4) if isinstance(value, float) else value)
    elif m := re.match(r"What does print\(repr\((.+)\)\) show\?$", stem):
        actual = repr(eval(m[1]))
    elif m := re.match(r"What (?:type is the value of|is the type of) (.+)\?$", stem):
        actual = type(eval(m[1])).__name__
    else:
        pytest.skip("no executable form")
    assert actual == expected, f"{item.external_id}: keyed {expected!r}, code gives {actual!r}"  # type: ignore[attr-defined]
