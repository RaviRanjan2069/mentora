"""Generated multiple-choice question bank for the sample course (SYN101).

Every question is built from a template with random parameters. The correct option is
computed by *running* the snippet (or evaluating the expression), so an answer key can never
be wrong; the other options come from typical mistakes (off-by-one, precedence, aliasing...).

    from mentora.question_bank import generate_bank
    items = generate_bank(n_per_concept=50, seed=2026)   # list of item dicts for items.yaml

Generation is deterministic for a given seed. Only this module's own snippets are executed.
"""

from __future__ import annotations

import contextlib
import io
import random
import string
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

WORDS = [
    "apple",
    "banana",
    "cherry",
    "python",
    "laptop",
    "garden",
    "planet",
    "rocket",
    "silver",
    "window",
    "orange",
    "monkey",
    "puzzle",
    "candle",
    "dragon",
    "forest",
    "guitar",
    "island",
    "jacket",
    "kitten",
    "lemon",
    "marble",
    "notebook",
    "pepper",
]
NAMES = ["total", "count", "score", "price", "speed", "items", "level", "value", "result"]
KEYWORDS = ["class", "for", "if", "def", "while", "return", "import", "lambda", "True"]
EXCEPTIONS = [
    "ZeroDivisionError",
    "IndexError",
    "KeyError",
    "ValueError",
    "TypeError",
    "NameError",
    "AttributeError",
]
BIG_O = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)"]
NOTHING = "(nothing is printed)"


@dataclass(frozen=True)
class Question:
    stem: str
    code: str
    correct: str
    distractors: tuple[str, ...]


Template = Callable[[random.Random], Question | None]


# --- helpers -----------------------------------------------------------------------------


def run(code: str, env: dict[str, Any] | None = None) -> str:
    """Execute a snippet and return what it printed (stripped). Exceptions propagate."""
    buf = io.StringIO()
    ns: dict[str, Any] = dict(env or {})
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<question>", "exec"), ns)
    return buf.getvalue().strip()


def raised(code: str, env: dict[str, Any] | None = None) -> str:
    """Name of the exception the snippet raises, or its output if it raises nothing."""
    try:
        return run(code, env)
    except Exception as exc:
        return type(exc).__name__


def q(stem: str, code: str, correct: object, *wrong: object) -> Question | None:
    """A question with exactly three distinct wrong options, or None if there aren't enough."""
    correct = str(correct)
    if not correct or "\n" in correct:
        return None
    out: list[str] = []
    for w in wrong:
        s = str(w)
        if s and "\n" not in s and s != correct and s not in out:
            out.append(s)
        if len(out) == 3:
            return Question(stem, code.strip("\n"), correct, tuple(out))
    return None


def word(rng: random.Random, min_len: int = 5) -> str:
    return rng.choice([w for w in WORDS if len(w) >= min_len])


def ints(rng: random.Random, k: int, lo: int = 1, hi: int = 9) -> list[int]:
    return [rng.randint(lo, hi) for _ in range(k)]


def near(n: int, *extra: object) -> list[object]:
    return [*extra, n + 1, n - 1, n + 2, n * 2, n - 2, 0]


PRINTS = ["What does this code print?", "What is printed?", "What is the output of this code?"]


def stem(rng: random.Random) -> str:
    return rng.choice(PRINTS)


# --- week 1 ------------------------------------------------------------------------------


def variables(rng: random.Random) -> Question | None:
    kind = rng.randrange(6)
    a, b, c, d = ints(rng, 4, 2, 9)
    if kind == 0:
        code = f"x = {a}\nx += {b}\nx *= {c}\nx -= {d}\nprint(x)"
        return q(
            stem(rng),
            code,
            run(code),
            a + b * c - d,
            (a + b) * c,
            a + b + c - d,
            int(run(code)) + d,
        )
    if kind == 1:
        code = f"a, b = {a}, {b}\na, b = b, a + b\nprint(a, b)"
        return q(stem(rng), code, run(code), f"{a} {b}", f"{b} {b + b}", f"{a + b} {b}", f"{b} {a}")
    if kind == 2:
        n = rng.choice(NAMES)
        code = f"{n} = {a}\nbackup = {n}\n{n} = {b + 10}\nprint(backup)"
        return q(stem(rng), code, run(code), b + 10, a + b + 10, "backup", "None")
    if kind == 3:
        code = f"x = y = {a}\nx += {b}\nprint(x, y)"
        return q(
            stem(rng), code, run(code), f"{a + b} {a + b}", f"{a} {a}", f"{a} {a + b}", f"{b} {a}"
        )
    w, w2 = word(rng), word(rng)
    digit = rng.randint(1, 9)
    invalid = [f"{digit}{w}", f"{w}-{w2}", rng.choice(KEYWORDS), f"{w} {w2}", f"{w}!"]
    valid = [
        w,
        f"_{w}",
        f"{w}_{digit}",
        f"{w.capitalize()}{w2.capitalize()}",
        f"{w}{digit}",
        f"{w}_{w2}",
    ]
    rng.shuffle(invalid)
    rng.shuffle(valid)
    if kind == 4:
        return q("Which of these is NOT a valid Python variable name?", "", invalid[0], *valid)
    return q("Which of these IS a valid Python variable name?", "", valid[0], *invalid)


def types(rng: random.Random) -> Question | None:
    a, b = rng.randint(2, 9), rng.randint(2, 9)
    w = word(rng)
    kind = rng.randrange(3)
    if kind == 0:
        expr = rng.choice(
            [
                f"{a} / {b}",
                f"{a} // {b}",
                f"{a} * 1.0",
                f'"{a}" + "{b}"',
                f"{a} > {b}",
                f"[{a}, {b}]",
                f"({a},)",
                f"({a})",
                f"int('{a}') + {b}",
                f"str({a}) * 2",
                f"float({a})",
                f"{a} ** 2",
                f"round({a}.{b})",
                f"len('{w}')",
                f"{{'{w}': {a}}}",
                f"{{{a}, {b}}}",
                "None",
                f"'{w}'.upper()",
                f"{a} == {a}.0",
                f"'{w}'.split()",
            ]
        )
        code = f"print(type({expr}).__name__)"
        names = ["int", "float", "str", "bool", "list", "tuple", "dict", "set", "NoneType"]
        rng.shuffle(names)
        return q(f"What type is the value of {expr}?", "", run(code), *names)
    if kind == 1:
        forms = [
            (f'print(int("{a}") + {b})', f"{a}{b}", "TypeError", a * b),
            (f"print(str({a}) + str({b}))", a + b, f"{a} {b}", "TypeError"),
            (f"print(int({a}.9))", a + 1, f"{a}.9", "ValueError"),
            (f'print(float("{a}") + {b})', a + b, f"{a}{b}", f"{a + b}.00"),
            (f'print("{a}" * {b})', a * b, f"{a} " * 1 + f"x{b}", "TypeError"),
        ]
        code, *wrong = rng.choice(forms)
        return q(stem(rng), str(code), run(str(code)), *wrong)
    v = rng.choice(
        ["0", "1", '""', '"0"', '" "', "[]", "[0]", "0.0", "None", '"False"', "-1", "{}"]
    )
    code = f"print(bool({v}))"
    return q(
        f"What does bool({v}) evaluate to?",
        "",
        run(code),
        "True" if run(code) == "False" else "False",
        "None",
        "TypeError",
    )


def expressions(rng: random.Random) -> Question | None:
    a, b, c = rng.randint(5, 20), rng.randint(2, 6), rng.randint(2, 5)
    forms = [
        (f"{a} + {b} * {c}", [f"({a} + {b}) * {c}", f"{a} + {b} + {c}"]),
        (f"({a} + {b}) * {c}", [f"{a} + {b} * {c}", f"{a} * {c} + {b}"]),
        (f"{a} - {b} - {c}", [f"{a} - ({b} - {c})", f"{a} - {b} + {c}"]),
        (f"{a} // {b} + {a} % {b}", [f"{a} // ({b} + {a}) % {b}", f"{a} // {b}"]),
        (f"{a} % {b} * {c}", [f"{a} % ({b} * {c})", f"{a} * {c} % {b}"]),
        (f"-{a} // {b}", [f"-({a} // {b})", f"{a} // {b}"]),
        (f"{a} // {b} * {b}", [f"{a} // ({b} * {b})", f"{a}"]),
        (f"{b} ** 2 + {c}", [f"{b} ** ({c} + 2)", f"{b} * 2 + {c}"]),
        (f"{a} % {b}", [f"{a} // {b}", f"{b} % {a}"]),
        (f"{a} // {b}", [f"{a} % {b}", f"round({a} / {b})"]),
        (f"{a} / {b} * {c}", [f"{a} / ({b} * {c})", f"{a} // {b} * {c}"]),
        (f"2 * {b} ** 2", [f"(2 * {b}) ** 2", f"2 * {b} * 2"]),
    ]
    expr, alts = rng.choice(forms)
    value = eval(expr)
    wrong = [eval(x) for x in alts]
    if isinstance(value, float):
        value = round(value, 4)
        wrong = [round(float(x), 4) for x in wrong]
        return q(
            f"What does {expr} evaluate to?", "", value, *wrong, round(value + 1, 4), int(value)
        )
    return q(f"What does {expr} evaluate to?", "", value, *wrong, *near(value))


def io_questions(rng: random.Random) -> Question | None:
    a, b, c = ints(rng, 3, 1, 9)
    w = word(rng)
    kind = rng.randrange(5)
    if kind == 0:
        sep = rng.choice(["-", ", ", "", "/", "::"])
        code = f'print({a}, {b}, {c}, sep="{sep}")'
        return q(
            stem(rng),
            code,
            run(code),
            f"{a} {b} {c}",
            f"{a}{sep}{b}{sep}{c}{sep}",
            f"{a}{b}{c}" if sep else f"{a}-{b}-{c}",
            f"{a},{b},{c}",
        )
    if kind == 1:
        end = rng.choice(["", " ", "-", "!"])
        code = f'print("{w}", end="{end}")\nprint({a})'
        return q(
            stem(rng),
            code,
            run(code),
            f"{w} {a}" if end != " " else f"{w}{a}",
            f"{w}{end}",
            f"{a}{end}{w}",
            f"{w}\\n{a}",
        )
    if kind == 2:
        x = a + b / 7
        code = f'value = {a} + {b} / 7\nprint(f"{{value:.2f}}")'
        return q(stem(rng), code, run(code), f"{x:.1f}", f"{x:.3f}", int(x), f"{x:.2f}0")
    env = {"input": lambda *_: str(a)}
    if kind == 3:
        code = f"x = input()\nprint(x * {b})"
        return q(
            f"The user types {a}. What is printed?",
            code,
            run(code, env),
            a * b,
            f"{a} " * 1 + f"* {b}",
            "TypeError",
            f"{a}{b}",
        )
    code = f"x = input()\nprint(int(x) + {b})"
    return q(
        f"The user types {a}. What is printed?",
        code,
        run(code, env),
        f"{a}{b}",
        "TypeError",
        a * b,
        b,
    )


# --- week 2 ------------------------------------------------------------------------------


def conditionals(rng: random.Random) -> Question | None:
    hi, lo = rng.randint(50, 90), rng.randint(10, 40)
    x = rng.randint(0, 100)
    kind = rng.randrange(4)
    if kind == 0:
        code = (
            f'x = {x}\nif x > {hi}:\n    print("high")\nelif x > {lo}:\n    print("medium")\n'
            'else:\n    print("low")'
        )
        return q(stem(rng), code, run(code), "high", "medium", "low", "high medium", NOTHING)
    if kind == 1:
        t = rng.randint(10, 60)
        code = (
            f'x = {x}\nif x % 2 == 0:\n    if x > {t}:\n        print("A")\n    else:\n'
            '        print("B")\nelse:\n    print("C")'
        )
        return q(stem(rng), code, run(code), "A", "B", "C", NOTHING, "AB")
    if kind == 2:
        t1, t2, t3 = sorted(rng.sample(range(5, 95), 3))
        code = (
            f'x = {x}\nif x > {t1}:\n    print("X", end="")\nif x > {t2}:\n'
            f'    print("Y", end="")\nif x > {t3}:\n    print("Z", end="")\nprint("!")'
        )
        return q(stem(rng), code, run(code), "X!", "XY!", "XYZ!", "!", "Z!", "Y!")
    t = rng.randint(20, 80)
    a, b = rng.randint(1, 9), rng.randint(10, 19)
    code = f"x = {x}\ny = {a} if x < {t} else {b}\nprint(y * 2)"
    return q(stem(rng), code, run(code), a * 2, b * 2, a, b, a + b)


def boolean_logic(rng: random.Random) -> Question | None:
    vals = ["0", "3", "''", "'hi'", "[]", "[1]", "None", "7", "''"]
    kind = rng.randrange(3)
    if kind == 0:
        x, y = rng.sample(vals, 2)
        op = rng.choice(["or", "and"])
        code = f"print(repr({x} {op} {y}))"
        return q(
            f"What does print(repr({x} {op} {y})) show?",
            "",
            run(code),
            "True",
            "False",
            repr(eval(x)),
            repr(eval(y)),
        )
    if kind == 1:
        a, b, c, d = ints(rng, 4, 1, 9)
        expr = rng.choice(
            [
                f"{a} > {b} and not {c} == {d}",
                f"{a} < {b} or {c} > {d} and {a} == {b}",
                f"not ({a} > {b} or {c} > {d})",
                f"{a} >= {b} and {c} <= {d} or {a} != {d}",
                f"not {a} > {b} and not {c} > {d}",
            ]
        )
        code = f"print({expr})"
        return q(
            f"What does {expr} evaluate to?",
            "",
            run(code),
            "True" if run(code) == "False" else "False",
            "None",
            "SyntaxError",
        )
    pool = rng.sample(["0", "1", "''", "'a'", "[]", "[0]", "None", "0.0", "' '", "-2"], 5)
    code = f"values = [{', '.join(pool)}]\nprint(sum(1 for v in values if v))"
    n = int(run(code))
    return q("How many values in the list are truthy?", code, n, *near(n, 5))


# --- week 3 ------------------------------------------------------------------------------


def while_loops(rng: random.Random) -> Question | None:
    s, k, limit = rng.randint(0, 5), rng.randint(2, 5), rng.randint(12, 40)
    kind = rng.randrange(4)
    if kind == 0:
        code = f"n = {s}\nwhile n < {limit}:\n    n += {k}\nprint(n)"
        r = int(run(code))
        return q(stem(rng), code, r, r - k, limit, r + k, limit - 1)
    if kind == 1:
        n0 = rng.randint(20, 200)
        code = f"n = {n0}\ncount = 0\nwhile n > 1:\n    n //= 2\n    count += 1\nprint(count)"
        r = int(run(code))
        return q(stem(rng), code, r, *near(r, n0 // 2))
    if kind == 2:
        code = f"i = 0\nwhile True:\n    i += {k}\n    if i > {limit}:\n        break\nprint(i)"
        r = int(run(code))
        return q(stem(rng), code, r, r - k, limit, limit + 1, r + k)
    n = rng.randint(4, 12)
    skip = rng.randint(2, 4)
    code = (
        f"total = 0\ni = 0\nwhile i < {n}:\n    i += 1\n    if i % {skip} == 0:\n"
        "        continue\n    total += i\nprint(total)"
    )
    r = int(run(code))
    return q(stem(rng), code, r, sum(range(1, n + 1)), r - n, sum(range(n)), *near(r))


def for_loops(rng: random.Random) -> Question | None:
    a, step = rng.randint(0, 5), rng.randint(1, 4)
    b = a + rng.randint(5, 15)
    kind = rng.randrange(5)
    if kind == 0:
        code = f"total = 0\nfor i in range({a}, {b}, {step}):\n    total += i\nprint(total)"
        r = int(run(code))
        return q(
            stem(rng),
            code,
            r,
            sum(range(a, b + 1, step)),
            sum(range(0, b, step)),
            sum(range(a + step, b, step)),
            *near(r),
        )
    if kind == 1:
        code = f"print(list(range({a}, {b}, {step})))"
        out = run(code)
        return q(
            stem(rng),
            code,
            out,
            list(range(a, b + 1, step)),
            list(range(a + 1, b, step)),
            list(range(a, b)),
            list(range(a, b, step))[1:],
        )
    if kind == 2:
        c = rng.randint(2, 5)
        code = f"count = 0\nfor i in range({a}, {b}):\n    for j in range({c}):\n        count += 1\nprint(count)"
        r = int(run(code))
        return q(stem(rng), code, r, (b - a + 1) * c, (b - a) + c, b * c, *near(r))
    if kind == 3:
        w = word(rng)
        code = f'result = ""\nfor ch in "{w}":\n    result = ch + result\nprint(result)'
        return q(stem(rng), code, run(code), w, w[1:] + w[0], "".join(sorted(w)), w[::-1][1:])
    n = rng.randint(3, 12)
    code = f"for i in range({n}):\n    pass\nprint(i)"
    return q(stem(rng), code, n - 1, n, 0, "NameError", n + 1)


def strings(rng: random.Random) -> Question | None:
    w = word(rng, 6)
    n = len(w)
    kind = rng.randrange(4)
    if kind == 0:
        i, j = sorted(rng.sample(range(1, n), 2))
        expr = rng.choice(
            [f"[{i}:{j}]", f"[{i}:]", f"[:{j}]", "[::-1]", f"[-{i}:]", "[::2]", f"[{i}:-1]"]
        )
        code = f's = "{w}"\nprint(s{expr})'
        return q(
            stem(rng),
            code,
            run(code),
            w[i : j + 1],
            w[i + 1 : j + 1],
            w[i - 1 : j],
            w[:i],
            w[j:],
            w[::-1][1:],
        )
    if kind == 1:
        c = rng.choice(w)
        method, wrong = rng.choice(
            [
                ("s.upper()", [w.capitalize(), w, w.swapcase().lower()]),
                ("s.capitalize()", [w.upper(), w, w.title()[::-1]]),
                (f's.find("{c}")', [w.find(c) + 1, w.rfind(c) + 1, -1]),
                (f's.count("{c}")', [w.count(c) + 1, 1 if w.count(c) > 1 else 2, n]),
                ("len(s)", [n - 1, n + 1, n * 2]),
                (
                    f's.replace("{c}", "*")',
                    [
                        w.replace(c, "*", 1) if w.count(c) > 1 else w,
                        w.replace(c, ""),
                        w.replace(c, "*") + "*",
                    ],
                ),
                ('"-".join(s)', [f"-{w}-", w, "-".join(w) + "-"]),
                ("s * 2", [w + " " + w, "TypeError", w]),
            ]
        )
        code = f's = "{w}"\nprint({method})'
        return q(stem(rng), code, run(code), *cast(list[object], wrong), "None")
    if kind == 2:
        i = rng.randint(1, n - 2)
        idx = rng.choice([str(i), f"-{i}"])
        code = f's = "{w}"\nprint(s[{idx}])'
        k = int(idx)
        return q(
            stem(rng),
            code,
            run(code),
            w[k + 1],
            w[k - 1],
            w[(k + 1) % n] if k < 0 else w[-k],
            "IndexError",
        )
    code = f's = "{w}"\ns.upper()\nprint(s)'
    return q(stem(rng), code, w, w.upper(), "None", "TypeError", w.capitalize())


# --- weeks 4-5 ---------------------------------------------------------------------------


def lists(rng: random.Random) -> Question | None:
    base = rng.sample(range(1, 20), rng.randint(3, 5))
    x, y = rng.randint(20, 40), rng.randint(41, 60)
    kind = rng.randrange(6)
    if kind == 0:
        i = rng.randint(0, len(base) - 1)
        code = f"lst = {base}\nlst.append({x})\nlst.insert({i}, {y})\nlst.pop()\nprint(lst)"
        out = run(code)
        wrong1 = [*base[:i], y, *base[i:], x]
        wrong2 = ([*base, x])[:]
        wrong2.insert(i + 1, y)
        wrong2.pop()
        wrong3 = [*base[:], x]
        wrong3.insert(i, y)
        wrong3.pop(0)
        return q(stem(rng), code, out, wrong1, wrong2, wrong3, [*base, x])
    if kind == 1:
        expr = rng.choice(["[1:3]", "[-2:]", "[::2]", "[:2]", "[1:]", "[::-1]"])
        code = f"lst = {base}\nprint(lst{expr})"
        return q(
            stem(rng),
            code,
            run(code),
            base[1:4],
            base[-3:],
            base[1::2],
            base[:3],
            base[2:],
            base[0],
        )
    if kind == 2:
        copy = rng.random() < 0.5
        code = f"a = {base}\nb = a{'[:]' if copy else ''}\nb.append({x})\nprint(a)"
        return q(stem(rng), code, run(code), base, [*base, x], [x], "None")
    if kind == 3:
        k = rng.randint(2, 4)
        code = f"lst = {base}\nprint([v * {k} for v in lst if v % 2 == 0])"
        evens = [v * k for v in base if v % 2 == 0]
        odds = [v * k for v in base if v % 2 == 1]
        return q(
            stem(rng),
            code,
            run(code),
            odds,
            [v * k for v in base],
            [v for v in base if v % 2 == 0],
            [*evens, 0],
        )
    if kind == 4:
        expr, wrong = rng.choice(
            [
                ("len(lst)", [len(base) - 1, len(base) + 1, sum(base)]),
                ("sum(lst)", [sum(base) - base[0], sum(base) + base[-1], len(base)]),
                ("max(lst) - min(lst)", [max(base), min(base), max(base) + min(base)]),
                (f"lst.index({base[1]})", [2, base[1], 0]),
                ("lst[-1]", [base[0], base[-2], "IndexError"]),
            ]
        )
        code = f"lst = {base}\nprint({expr})"
        return q(stem(rng), code, run(code), *cast(list[object], wrong), -1)
    code = f"lst = {base}\nprint(lst.sort())"
    return q(stem(rng), code, "None", sorted(base), base, sorted(base, reverse=True))


def tuples(rng: random.Random) -> Question | None:
    t = tuple(rng.sample(range(1, 20), rng.randint(3, 5)))
    kind = rng.randrange(5)
    if kind == 0:
        i = rng.randint(1, len(t) - 1)
        expr = rng.choice([f"[{i}]", f"[-{i}]", f"[{i - 1}:{i + 1}]", f"[{i}:]"])
        code = f"t = {t}\nprint(t{expr})"
        return q(
            stem(rng),
            code,
            run(code),
            t[i - 1],
            t[i : i + 2],
            t[-i - 1] if i + 1 <= len(t) else t[0],
            list(t[i - 1 : i + 1]),
            t[:i],
        )
    if kind == 1:
        code = f"t = {t}\nfirst, *rest = t\nprint(first, rest)"
        return q(
            stem(rng),
            code,
            run(code),
            f"{t[0]} {t[1:]}",
            f"{t[0]} {list(t[1:-1])}",
            f"{t[-1]} {list(t[:-1])}",
            "ValueError",
        )
    if kind == 2:
        code = f"t = {t}\nt[0] = {t[0] + 1}\nprint(t)"
        return q(
            "What happens when this code runs?",
            code,
            raised(code),
            (t[0] + 1, *t[1:]),
            t,
            "ValueError",
            "IndexError",
        )
    if kind == 3:
        x = rng.randint(20, 30)
        expr, wrong = rng.choice(
            [
                (f"t + ({x},)", [(*t, x, x), (*t, (x,)), "TypeError"]),
                ("t * 2", [tuple(v * 2 for v in t), t, (t, t)]),
                ("len(t + t)", [len(t), len(t) + 1, len(t) * 3]),
                (f"t.count({t[0]})", [0, 2, t[0]]),
            ]
        )
        code = f"t = {t}\nprint({expr})"
        return q(stem(rng), code, run(code), *cast(list[object], wrong), "None")
    v = rng.randint(2, 9)
    form = rng.choice([f"({v})", f"({v},)"])
    code = f"print(type({form}).__name__)"
    return q(
        f"What is the type of {form}?",
        "",
        run(code),
        "tuple" if run(code) == "int" else "int",
        "list",
        "str",
    )


def dicts(rng: random.Random) -> Question | None:
    keys = rng.sample(WORDS, 3)
    vals = ints(rng, 3, 1, 20)
    d = dict(zip(keys, vals, strict=True))
    missing = rng.choice([w for w in WORDS if w not in d])
    kind = rng.randrange(6)
    if kind == 0:
        k, v = rng.choice(keys), rng.randint(30, 50)
        code = f"d = {d}\nd['{k}'] = {v}\nprint(len(d), d['{k}'])"
        return q(stem(rng), code, run(code), f"4 {v}", f"3 {d[k]}", f"4 {d[k]}", f"3 {d[k] + v}")
    if kind == 1:
        k = rng.choice([rng.choice(keys), missing])
        code = f"d = {d}\nprint(d.get('{k}', 0))"
        return q(
            stem(rng),
            code,
            run(code),
            d.get(k, "None") if k in d else "None",
            "KeyError",
            vals[0] if k != keys[0] else vals[1],
            -1,
        )
    if kind == 2:
        expr, wrong = rng.choice(
            [
                ("sum(d.values())", [len(d), sum(vals) - vals[0], max(vals)]),
                ("list(d.keys())", [vals, sorted(keys), next(iter(d.items()))]),
                ("max(d, key=d.get)", [max(vals), max(keys), min(d, key=d.__getitem__)]),
                (f"'{keys[0]}' in d", ["False", "None", vals[0]]),
                (f"{vals[0]} in d", ["True", "None", keys[0]]),
            ]
        )
        code = f"d = {d}\nprint({expr})"
        return q(stem(rng), code, run(code), *cast(list[object], wrong), "KeyError")
    if kind == 3:
        code = f"d = {d}\nprint(d['{missing}'])"
        return q(
            "What happens when this code runs?",
            code,
            raised(code),
            "None",
            0,
            "IndexError",
            "ValueError",
        )
    if kind == 4:
        t = rng.randint(5, 15)
        code = f"d = {d}\ntotal = 0\nfor k, v in d.items():\n    if v > {t}:\n        total += v\nprint(total)"
        r = int(run(code))
        return q(
            stem(rng),
            code,
            r,
            sum(vals),
            sum(v for v in vals if v <= t),
            sum(1 for v in vals if v > t),
            *near(r),
        )
    w = word(rng, 6)
    c = rng.choice(w)
    code = f'counts = {{}}\nfor ch in "{w}":\n    counts[ch] = counts.get(ch, 0) + 1\nprint(counts["{c}"])'
    r = int(run(code))
    return q(stem(rng), code, r, len(w), len(set(w)), *near(r))


def sets(rng: random.Random) -> Question | None:
    a = set(rng.sample(range(1, 10), 4))
    b = set(rng.sample(range(1, 10), 4))
    kind = rng.randrange(4)
    if kind == 0:
        op = rng.choice(["|", "&", "-", "^"])
        code = f"a = {sorted(a)}\nb = {sorted(b)}\nprint(sorted(set(a) {op} set(b)))"
        results = {"|": sorted(a | b), "&": sorted(a & b), "-": sorted(a - b), "^": sorted(a ^ b)}
        return q(
            stem(rng), code, run(code), *[results[o] for o in "|&-^" if o != op], sorted(b - a)
        )
    if kind == 1:
        lst = [rng.randint(1, 5) for _ in range(rng.randint(6, 9))]
        code = f"print(len(set({lst})))"
        r = int(run(code))
        return q(stem(rng), code, r, len(lst), *near(r))
    if kind == 2:
        x, y = rng.randint(10, 20), rng.choice(sorted(a))
        code = f"s = set({sorted(a)})\ns.add({x})\ns.add({y})\ns.discard({y})\nprint(sorted(s))"
        return q(
            stem(rng),
            code,
            run(code),
            sorted(a | {x}),
            sorted(a),
            [*sorted((a | {x}) - {y}), y],
            "KeyError",
        )
    x = rng.randint(1, 9)
    code = f"a = set({sorted(a)})\nb = set({sorted(b)})\nprint({x} in a & b, {x} in a | b)"
    return q(stem(rng), code, run(code), "True True", "False False", "True False", "False True")


# --- weeks 6-7 ---------------------------------------------------------------------------


def functions(rng: random.Random) -> Question | None:
    a, b, c = ints(rng, 3, 1, 9)
    kind = rng.randrange(5)
    if kind == 0:
        code = f"def f(x, y={b}):\n    return x * y + {c}\n\nprint(f({a}), f({a}, {c}))"
        return q(
            stem(rng),
            code,
            run(code),
            f"{a * b + c} {a * b + c}",
            f"{a + c} {a * c + c}",
            f"{a * (b + c)} {a * (c + c)}",
            "TypeError",
        )
    if kind == 1:
        code = f"def double(x):\n    x * 2\n\nprint(double({a}))"
        return q(stem(rng), code, "None", a * 2, a, "0", "TypeError")
    if kind == 2:
        t = rng.randint(3, 7)
        code = (
            f'def size(n):\n    if n > {t}:\n        return "big"\n    return "small"\n\n'
            f"print(size({a}), size({t}))"
        )
        return q(
            stem(rng),
            code,
            run(code),
            "big big",
            "small small",
            "big small",
            "small big",
            "None small",
        )
    if kind == 3:
        code = f"def f(a, b, c):\n    return a - b * c\n\nprint(f(c={c}, a={a + 20}, b={b}))"
        return q(
            stem(rng),
            code,
            run(code),
            c - b * (a + 20),
            (a + 20 - b) * c,
            a + 20 - c * c,
            "TypeError",
        )
    code = f"def sq(x):\n    return x * x\n\ndef total(p, q):\n    return sq(p) + sq(q)\n\nprint(total({a}, {b}))"
    r = int(run(code))
    return q(stem(rng), code, r, (a + b) ** 2, a * 2 + b * 2, a * a, *near(r))


def scope(rng: random.Random) -> Question | None:
    a, b = rng.randint(1, 9), rng.randint(10, 20)
    kind = rng.randrange(5)
    if kind == 0:
        code = f"x = {a}\n\ndef f():\n    x = {b}\n\nf()\nprint(x)"
        return q(stem(rng), code, a, b, "None", "NameError", a + b)
    if kind == 1:
        code = f"x = {a}\n\ndef f():\n    global x\n    x = x + {b}\n\nf()\nf()\nprint(x)"
        r = int(run(code))
        return q(stem(rng), code, r, a + b, a, "UnboundLocalError", b * 2)
    if kind == 2:
        code = f"def f(n):\n    n = n + {b}\n    return n\n\nv = {a}\nf(v)\nprint(v)"
        return q(stem(rng), code, a, a + b, "None", b)
    if kind == 3:
        data = rng.sample(range(1, 9), rng.randint(2, 4))
        code = f"def f(lst):\n    lst.append({b})\n\ndata = {data}\nf(data)\nprint(len(data))"
        r = int(run(code))
        return q(
            stem(rng), code, r, len(data) - 1 if r == len(data) else len(data), r + 1, "None", "0"
        )
    code = f"x = {a}\n\ndef f():\n    print(x)\n    x = {b}\n\nf()"
    return q("What happens when this code runs?", code, raised(code), a, b, "NameError", "None")


def recursion(rng: random.Random) -> Question | None:
    kind = rng.randrange(6)
    n = rng.randint(3, 7)
    if kind == 0:
        code = (
            f"def f(n):\n    if n <= 1:\n        return 1\n    return n * f(n - 1)\n\nprint(f({n}))"
        )
        r = int(run(code))
        return q(stem(rng), code, r, r // n, r * (n + 1), sum(range(1, n + 1)), n * (n - 1))
    if kind == 1:
        code = f"def total(n):\n    if n == 0:\n        return 0\n    return n + total(n - 1)\n\nprint(total({n + 3}))"
        r = int(run(code))
        return q(stem(rng), code, r, r - (n + 3), r + n + 4, (n + 3) ** 2, *near(r))
    if kind == 2:
        m = rng.randint(5, 12)
        code = f"def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n\nprint(fib({m}))"
        r = int(run(code))
        return q(
            stem(rng),
            code,
            r,
            int(run(code.replace(f"fib({m}))", f"fib({m - 1}))"))),
            int(run(code.replace(f"fib({m}))", f"fib({m + 1}))"))),
            m,
            *near(r),
        )
    if kind == 3:
        base, e = rng.randint(2, 4), rng.randint(2, 5)
        code = f"def power(b, e):\n    if e == 0:\n        return 1\n    return b * power(b, e - 1)\n\nprint(power({base}, {e}))"
        r = int(run(code))
        return q(stem(rng), code, r, base * e, base ** (e - 1), base ** (e + 1), e**base)
    if kind == 4:
        w = word(rng)
        code = f'def rev(s):\n    if s == "":\n        return ""\n    return rev(s[1:]) + s[0]\n\nprint(rev("{w}"))'
        return q(stem(rng), code, run(code), w, w[1:] + w[0], w[-1] + w[:-1], "RecursionError")
    code = (
        f"calls = 0\n\ndef down(n):\n    global calls\n    calls += 1\n    if n > 0:\n"
        f"        down(n - 1)\n\ndown({n})\nprint(calls)"
    )
    r = int(run(code))
    return q("How many times is down() called in total?", code, r, n, r + 1, n - 1, 2 * n)


# --- weeks 8-10 --------------------------------------------------------------------------


class _File(io.StringIO):
    """In-memory stand-in for open() so file questions can be executed."""


def _fake_open(content: str) -> Callable[..., io.StringIO]:
    writes: dict[str, io.StringIO] = {}

    def open_(name: str, mode: str = "r", *_: object, **__: object) -> io.StringIO:
        if "w" in mode or "a" in mode:
            writes[name] = _File()
            return writes[name]
        return _File(content)

    return open_


def files(rng: random.Random) -> Question | None:
    lines = rng.sample(WORDS, rng.randint(3, 6))
    content = "\n".join(lines) + "\n"
    header = "# data.txt contains these lines:\n" + "\n".join(f"#   {w}" for w in lines) + "\n"
    env = {"open": _fake_open(content)}
    kind = rng.randrange(6)
    if kind == 0:
        code = header + 'with open("data.txt") as f:\n    lines = f.readlines()\nprint(len(lines))'
        r = int(run(code, env))
        return q(stem(rng), code, r, r + 1, r - 1, len(content), 1)
    if kind == 1:
        i = rng.randint(0, len(lines) - 1)
        code = (
            header
            + f'with open("data.txt") as f:\n    lines = f.readlines()\nprint(lines[{i}].strip().upper())'
        )
        return q(
            stem(rng),
            code,
            run(code, env),
            lines[i],
            lines[(i + 1) % len(lines)].upper(),
            lines[i - 1].upper() if i else lines[-1].upper(),
            "IndexError",
        )
    if kind == 2:
        letter = rng.choice("aeiou")
        code = (
            header
            + f'count = 0\nwith open("data.txt") as f:\n    for line in f:\n        if "{letter}" in line:\n            count += 1\nprint(count)'
        )
        r = int(run(code, env))
        return q(
            stem(rng),
            code,
            r,
            len(lines),
            sum(w.count(letter) for w in lines)
            + (1 if r == sum(w.count(letter) for w in lines) else 0),
            *near(r),
        )
    if kind == 3:
        text = " ".join(rng.sample(WORDS, rng.randint(2, 4)))
        code = f'with open("out.txt", "w") as f:\n    n = f.write("{text}")\nprint(n)'
        r = int(run(code, env))
        return q(
            f"f.write() returns the number of characters written. {stem(rng)}",
            code,
            r,
            len(text.split()),
            r + 1,
            "None",
        )
    if kind == 4:
        code = (
            header
            + 'with open("data.txt") as f:\n    text = f.read()\nprint(type(text).__name__, len(text.split()))'
        )
        out = run(code, env)
        return q(
            stem(rng),
            code,
            out,
            f"list {len(lines)}",
            f"str {len(content)}",
            f"str {len(lines) + 1}",
            f"list {len(content)}",
        )
    facts = [
        (
            "Which mode opens a file to add text at the end, keeping what is already there?",
            "'a'",
            ["'w'", "'r'", "'x'", "'r+'"],
        ),
        (
            "Which mode empties an existing file before writing to it?",
            "'w'",
            ["'a'", "'r'", "'x'", "'rb'"],
        ),
        (
            "Which mode is used when you call open(name) without a mode?",
            "'r'",
            ["'w'", "'a'", "'r+'", "'x'"],
        ),
        (
            "Which mode creates a new file and fails if it already exists?",
            "'x'",
            ["'w'", "'a'", "'r'", "'w+'"],
        ),
        (
            "What does a with block do for a file when the block ends?",
            "It closes the file",
            ["It deletes the file", "It saves a backup", "Nothing", "It reopens the file"],
        ),
        (
            "What does f.readlines() return?",
            "A list of strings, one per line",
            ["One string with all the text", "The number of lines", "A tuple of words", "None"],
        ),
        (
            "What does f.read() return for a text file?",
            "One string with all the text",
            ["A list of lines", "The number of characters", "Bytes", "None"],
        ),
        (
            "What happens when you open a missing file in mode 'r'?",
            "FileNotFoundError",
            ["An empty file is created", "It returns None", "ValueError", "PermissionError"],
        ),
    ]
    stem_, correct, wrong = rng.choice(facts)
    rng.shuffle(wrong)
    return q(stem_, "", correct, *wrong)


def exceptions(rng: random.Random) -> Question | None:
    a, b = rng.randint(1, 9), rng.randint(10, 20)
    w = word(rng)
    kind = rng.randrange(4)
    if kind == 0:
        stmt = rng.choice(
            [
                f"{a} / 0",
                f"[{a}, {b}][{a + 2}]",
                f"{{'{w}': {a}}}['x']",
                f"int('{w}')",
                f"'{w}' + {a}",
                f"{w}_value + 1",
                f"'{w}'.push('x')",
                f"{a} % 0",
                "[][0]",
                f"float('{w}')",
                f"({a}, {b})[5]",
                f"len({a})",
            ]
        )
        code = f"x = {stmt}"
        names = EXCEPTIONS[:]
        rng.shuffle(names)
        return q(f"Which exception does {stmt} raise?", code, raised(code), *names)
    if kind == 1:
        bad = rng.random() < 0.5
        risky = f"x = {a} / 0" if bad else f"x = {a} / {b}"
        code = (
            f'try:\n    print("A", end="")\n    {risky}\n    print("B", end="")\n'
            'except ZeroDivisionError:\n    print("C", end="")\nelse:\n    print("D", end="")\n'
            'finally:\n    print("E")'
        )
        return q(stem(rng), code, run(code), "ABDE", "ACE", "ABCE", "AC", "ABD", "ACDE")
    if kind == 2:
        value = rng.choice([f'"{a}"', f'"{w}"', "None", f'"{a}.5"'])
        code = (
            f'try:\n    n = int({value})\n    print(n * 2)\nexcept ValueError:\n    print("value")\n'
            'except Exception:\n    print("other")'
        )
        return q(
            stem(rng), code, run(code), a * 2, "value", "other", "None", f"{a}{a}", "TypeError"
        )
    n = rng.choice([a, -a])
    code = (
        f'def check(n):\n    if n < 0:\n        raise ValueError("negative")\n    return n * 2\n\n'
        f"try:\n    print(check({n}))\nexcept ValueError as e:\n    print(e)"
    )
    return q(stem(rng), code, run(code), abs(n) * 2, "negative", "ValueError", "None", -abs(n) * 2)


def classes(rng: random.Random) -> Question | None:
    a, b = rng.randint(1, 9), rng.randint(2, 9)
    kind = rng.randrange(6)
    if kind == 0:
        code = (
            f"class Counter:\n    def __init__(self, start):\n        self.n = start\n\n"
            f"    def inc(self, k=1):\n        self.n += k\n\nc = Counter({a})\nc.inc()\nc.inc({b})\nprint(c.n)"
        )
        r = int(run(code))
        return q(stem(rng), code, r, a + b, a + 2, r + 1, a)
    if kind == 1:
        k = rng.randint(2, 6)
        code = (
            "class Dog:\n    count = 0\n\n    def __init__(self):\n        Dog.count += 1\n\n"
            f"dogs = [Dog() for _ in range({k})]\nprint(Dog.count, dogs[0].count)"
        )
        return q(stem(rng), code, run(code), f"{k} 1", "1 1", f"{k} 0", f"0 {k}")
    if kind == 2:
        x, y = rng.sample(["woof", "meow", "tweet", "moo", "hiss"], 2)
        code = (
            f'class Animal:\n    def speak(self):\n        return "{x}"\n\nclass Pet(Animal):\n'
            f'    def speak(self):\n        return "{y}"\n\nprint(Pet().speak(), Animal().speak())'
        )
        return q(stem(rng), code, run(code), f"{x} {x}", f"{y} {y}", f"{x} {y}", "AttributeError")
    if kind == 3:
        code = (
            "class Base:\n    def __init__(self, v):\n        self.v = v\n\nclass Child(Base):\n"
            f"    def __init__(self, v):\n        super().__init__(v * {b})\n\nprint(Child({a}).v)"
        )
        r = int(run(code))
        return q(stem(rng), code, r, a, b, a + b, "AttributeError")
    if kind == 4:
        code = (
            "class Point:\n    def __init__(self, x):\n        self.x = x\n\n    def __str__(self):\n"
            f'        return f"Point({{self.x}})"\n\nprint(Point({a}))'
        )
        return q(stem(rng), code, run(code), "<Point object>", a, f"Point(x={a})", "Point")
    shared = rng.random() < 0.5
    body = (
        "class Box:\n    items = []\n"
        if shared
        else "class Box:\n    def __init__(self):\n        self.items = []\n"
    )
    code = body + f"\na = Box()\nb = Box()\na.items.append({a})\nprint(len(b.items))"
    return q(stem(rng), code, run(code), 0 if run(code) == "1" else 1, 2, "AttributeError")


def complexity(rng: random.Random) -> Question | None:
    kind = rng.randrange(2)
    n = rng.choice(["n", "size", "length"])
    k = rng.randint(5, 100)
    if kind == 0:
        forms = [
            (f"for i in range({n}):\n    total += i", "O(n)"),
            (f"for i in range({n}):\n    for j in range({n}):\n        total += i * j", "O(n^2)"),
            (f"i = {n}\nwhile i > 1:\n    i //= 2\n    total += 1", "O(log n)"),
            (f"for i in range({k}):\n    total += i", "O(1)"),
            (f"for i in range({n}):\n    total += i\nfor j in range({n}):\n    total -= j", "O(n)"),
            (f"for i in range({n}):\n    for j in range({k}):\n        total += j", "O(n)"),
            (
                f"for i in range({n}):\n    for j in range({n}):\n        for m in range({n}):\n            total += 1",
                "O(n^3)",
            ),
            (
                f"for i in range({n}):\n    j = 1\n    while j < {n}:\n        j *= 2\n        total += 1",
                "O(n log n)",
            ),
            (f"for i in range({n}):\n    for j in range(i):\n        total += 1", "O(n^2)"),
            (f"total = {n} * ({n} + 1) // 2", "O(1)"),
        ]
        code, correct = rng.choice(forms)
        code = "total = 0\n" + code
        others = [o for o in BIG_O if o != correct]
        rng.shuffle(others)
        return q(
            f"What is the time complexity of this code in terms of {n}?", code, correct, *others
        )
    size = rng.randint(4, 12)
    form = rng.choice(
        [
            "for i in range(n):\n    for j in range(i):\n        count += 1",
            "for i in range(n):\n    for j in range(n):\n        count += 1",
            "i = n\nwhile i > 1:\n    i //= 2\n    count += 1",
            "for i in range(n):\n    for j in range(i, n):\n        count += 1",
        ]
    )
    code = f"n = {size}\ncount = 0\n{form}\nprint(count)"
    r = int(run(code))
    return q(
        f"How many times is count increased when n = {size}?",
        code,
        r,
        size * size,
        size * (size + 1) // 2 if r != size * (size + 1) // 2 else size * (size - 1) // 2,
        size,
        *near(r),
    )


GENERATORS: dict[str, Template] = {
    "variables": variables,
    "types": types,
    "expressions": expressions,
    "io": io_questions,
    "conditionals": conditionals,
    "boolean_logic": boolean_logic,
    "while_loops": while_loops,
    "for_loops": for_loops,
    "strings": strings,
    "lists": lists,
    "tuples": tuples,
    "dicts": dicts,
    "sets": sets,
    "functions": functions,
    "scope": scope,
    "recursion": recursion,
    "files": files,
    "exceptions": exceptions,
    "classes": classes,
    "complexity": complexity,
}


def item_text(question: Question, options: list[str]) -> str:
    lines = [question.stem]
    if question.code:
        lines.append(question.code)
    lines += [
        f"({letter}) {opt}" for letter, opt in zip(string.ascii_uppercase, options, strict=False)
    ]
    return "\n".join(lines)


def generate_bank(
    n_per_concept: int = 50, seed: int = 2026, graded_every: int = 5
) -> list[dict[str, Any]]:
    """``n_per_concept`` distinct MCQs per concept; every ``graded_every``-th one is graded."""
    rng = random.Random(seed)
    items: list[dict[str, Any]] = []
    for concept, gen in GENERATORS.items():
        seen: set[tuple[str, str]] = set()
        made = 0
        attempts = 0
        while made < n_per_concept:
            attempts += 1
            if attempts > n_per_concept * 400:
                raise RuntimeError(f"{concept}: only {made} distinct questions")
            question = gen(rng)
            if question is None or (question.stem, question.code) in seen:
                continue
            seen.add((question.stem, question.code))
            options = [question.correct, *question.distractors]
            rng.shuffle(options)
            made += 1
            items.append(
                {
                    "external_id": f"qb-{concept}-{made:03d}",
                    "text": item_text(question, options),
                    "answer_key": string.ascii_uppercase[options.index(question.correct)],
                    "item_type": "mcq",
                    "concepts": [concept],
                    "graded": made % graded_every == 0,
                }
            )
    return items
