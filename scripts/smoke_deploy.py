"""End-to-end smoke test against a running Mentora (local or deployed).

    python scripts/smoke_deploy.py https://mentora.onrender.com --teacher-code <code>

Uses dev sign-in, so it creates one demo learner and one demo teacher, a short tutoring
session, a quiz answer and an escalation (answered by the teacher). Synthetic data only;
never run it against a deployment that holds real learner data.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

import httpx

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def step(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:
        check(name, False, repr(exc))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base_url")
    ap.add_argument("--teacher-code", default="")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds; free hosts cold-start")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    kw = {"base_url": base, "timeout": args.timeout, "follow_redirects": True}
    anon, learner, teacher = httpx.Client(**kw), httpx.Client(**kw), httpx.Client(**kw)
    stamp = time.strftime("%H%M%S")

    t0 = time.monotonic()
    h = anon.get("/health").json()
    print(f"/health after {time.monotonic() - t0:.1f}s: {h}")
    check("health ok, database reachable", h.get("status") == "ok" and h["database"] == "ok", h)

    page = anon.get("/app/")
    check("/app/ serves the web app", page.status_code == 200 and "<div id=" in page.text)
    check("/ redirects to /app/", str(anon.get("/").url).rstrip("/").endswith("/app"))
    assets = [p.split('"')[0] for p in page.text.split('src="')[1:]]
    links = [p.split('"')[0] for p in page.text.split('href="')[1:]]
    assets += [a for a in links if a.endswith(".css")]
    for a in assets[:4]:
        url = a if a.startswith("/") else f"/app/{a}"  # the page's own files are relative
        check(f"asset {url}", anon.get(url).status_code == 200)
    check("built app has no localhost URLs", "localhost" not in page.text)
    check("anonymous /api/me is 401", anon.get("/api/me").status_code == 401)
    check(
        "anonymous teacher API is 401",
        anon.get("/api/teacher/escalations").status_code == 401,
    )

    hits = anon.get("/api/rag/search", params={"q": "for loop range"}).json()["hits"]
    check("course retrieval returns passages", len(hits) > 0, hits)

    r = learner.post("/api/dev/login", json={"role": "learner", "name": f"Smoke {stamp}"})
    check("learner dev sign-in", r.status_code == 200, r.text)
    check(
        "learner blocked from teacher API", learner.get("/api/teacher/policies").status_code == 403
    )

    nocode = anon.post("/api/dev/login", json={"role": "teacher", "name": "x"}).status_code
    if args.teacher_code:
        check("teacher sign-in without code is refused", nocode == 403, nocode)

    sid = ""

    def tutor() -> None:
        nonlocal sid
        start = learner.post("/api/sessions").json()
        sid = start["session_id"]
        check("tutor session starts", bool(sid and start["reply"]), start)
        msg = {"text": "Can you explain how a for loop with range works?"}
        turn = learner.post(f"/api/sessions/{sid}/messages", json=msg).json()
        check("tutor replies", bool(turn.get("reply")), turn)
        print(f"      tutor: {turn['action']} | {turn['reply'][:110]!r}")
        print(f"      sources={turn['sources']} answer_source={turn.get('answer_source')}")
        goal = {"text": "My goal is to finish 2 for loop exercises today"}
        check("goal message", learner.post(f"/api/sessions/{sid}/messages", json=goal).is_success)

    def quiz() -> None:
        items = learner.get("/api/items").json()
        check("quiz items listed without answer keys", items and "answer_key" not in items[0])
        item = next(i for i in items if not i["graded"])
        check(
            "quiz starts",
            learner.post(f"/api/sessions/{sid}/quiz", json={"item_ids": [item["id"]]}).is_success,
        )
        check(
            "item presented",
            learner.post(f"/api/sessions/{sid}/items/{item['id']}/present").is_success,
        )
        ans = {"response": "0", "confidence": 0.7, "seconds": 20}
        res = learner.post(f"/api/sessions/{sid}/items/{item['id']}/answer", json=ans)
        check(
            "answer with confidence rating",
            res.is_success and res.json()["correct"] is not None,
            res.text,
        )

    def escalate() -> None:
        msg = {"text": "I can't cope anymore, I feel hopeless"}
        esc = learner.post(f"/api/sessions/{sid}/messages", json=msg).json()
        check(
            "distress escalates with support resources",
            esc["escalated"] and esc["support_resources"],
            esc,
        )

    step("tutor", tutor)
    step("quiz", quiz)
    step("escalation", escalate)
    for path in (
        "/api/me/dashboard",
        "/api/me/home",
        "/api/me/memory",
        "/api/concepts",
        "/api/resources",
    ):
        check(f"learner GET {path}", learner.get(path).status_code == 200)

    def teacher_flow() -> None:
        body = {"role": "teacher", "name": "Smoke Teacher", "access_code": args.teacher_code}
        r = teacher.post("/api/dev/login", json=body)
        check("teacher sign-in with code", r.status_code == 200, r.text)
        check("teacher blocked from learner API", teacher.post("/api/sessions").status_code == 403)
        inbox = teacher.get("/api/teacher/escalations", params={"status": "open"}).json()
        mine = [e for e in inbox if e.get("session_id") == sid] or inbox
        check("escalation visible to teacher", bool(mine), inbox)
        if mine:
            a = teacher.post(
                f"/api/teacher/escalations/{mine[0]['id']}/answer",
                json={"response": "Smoke test reply"},
            )
            check("teacher answers escalation", a.is_success, a.text)
        for path in (
            "/api/teacher/overview",
            "/api/teacher/students",
            "/api/teacher/decisions",
            "/api/teacher/policies",
            "/api/teacher/memory-queue",
            "/api/teacher/status",
        ):
            check(f"teacher GET {path}", teacher.get(path).status_code == 200)

    step("teacher", teacher_flow)
    if sid:
        check("session ends", learner.post(f"/api/sessions/{sid}/end").is_success)

    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
