# Runbook

Everything a new teammate needs to run, test and operate Mentora. Commands assume the
repository root. On Windows Git Bash use `.venv/Scripts/...`; on macOS/Linux use
`.venv/bin/...`.

## 1. First-time setup (about 10 minutes)

Requires Python 3.11+, Node 20+ and git.

```bash
python -m venv .venv
.venv/Scripts/activate                       # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[ml]"   # ~1 GB, CPU PyTorch
cd frontend && npm install && npm run build && cd ..
```

## 2. Run the demo locally (no Docker, no API key)

```bash
python scripts/seed_demo.py --with-history   # course, items + 1000-question bank, material, history
python scripts/train_learner_models.py       # optional: KT models + tactic HMM (~1 min)
uvicorn mentora.api.main:app --reload        # http://127.0.0.1:8000
```

- `http://127.0.0.1:8000/`: redirects to the web app
- `http://127.0.0.1:8000/app/`: the web app, with a sidebar of pages.
  - **Student**: Home (study streak, topics mastered, quiz average, learning time, SRL
    progress by phase, current strategy, recent activity, next steps), AI Tutor (chat with
    "Why this suggestion?", starter prompts, quick requests, copyable code, learning context
    and related resources; an open session's transcript comes back after a reload; "End
    session" offers a three-question reflection that feeds the self-reflection score),
    My Learning (goals and plan, teacher replies, remembered notes), Practice
    (question-by-question quiz with a navigator, hint card, related concepts and a results
    summary comparing confidence with accuracy), Resources (course material by week,
    search), Progress (study-activity heatmap, calibration and mastery charts), Settings
    (theme, download my data as JSON, delete memory).
  - **Everyone**: Ctrl+K opens a palette to jump to a page, search the course notes or
    (students) ask the tutor; the bell lists teacher replies or open escalations; the
    avatar menu switches light/dark/auto theme. On phones the sidebar becomes a menu.
  - **Teacher**: Teacher Console (class stats, weekly progress chart, topic performance,
    recent activity, system status), Escalations, Students (at-risk flags, search; select a
    row for a drawer with activity heatmap, SRL phases, goals and mastery), Learning
    Analytics (tutor decisions and safety filter), Content Management (upload or remove
    course files; instruction-like passages are quarantined; items with answer keys;
    course-memory review), Model Training (run offline training; approve or reject
    candidates), Reports (class CSV, policy reports), Settings (tutor rules).
  - Students are shown by pseudonym. Simulated demo learners (`sim_…`) are labelled.
- `http://127.0.0.1:8000/docs`: API reference

The default LLM back-end is `auto`: Claude (`llm.hosted_model`, default claude-opus-5-5)
when an API key is configured, otherwise `offline` template replies with a small,
closable "Demo mode" notice in the UI. For real replies, put the key in `.env` (or the
environment) and restart the server:

```bash
# in .env:
ANTHROPIC_API_KEY=sk-ant-...                 # or MENTORA_HOSTED_LLM_API_KEY
```

Free alternative: a local model with [Ollama](https://ollama.com) (no key, works offline;
answers are simpler and the first reply after a restart takes a while on a laptop CPU):

```bash
winget install Ollama.Ollama        # or the installer from ollama.com
ollama pull llama3.2:3b             # ~2 GB
# in .env:
MENTORA_LLM__BACKEND=local
MENTORA_LLM__LOCAL_MODEL=llama3.2:3b
MENTORA_LLM__TIMEOUT_S=180
```

`GET /health` and the teacher's System status show which back-end is in use; for a local
model, System status also checks that Ollama is reachable and the model is downloaded.

With a real model the tutor answers any question (`rag.answer_mode: open`): course
questions are answered from the notes with citations (labelled "From your course notes"),
anything else from general knowledge (labelled "General knowledge, not from your course
notes"). Replies stream into the chat as they are written (`POST
/api/sessions/{id}/messages/stream`, server-sent events). Graded tasks still get hints
only, distress still goes to the teacher, and a reply that cites the notes but cannot be
verified is shown labelled rather than escalated (`rag.unverified: label`; set `escalate`
for the stricter behaviour). `rag.answer_mode: course_only` restores the "outside this
course" reply for off-topic questions.

The first course search or RAG move after a server start loads the embedding and
reranker models (about 20 seconds); later requests are fast.

## 3. Tests and checks (all offline)

| What | Command |
|---|---|
| Everything (SQLite + FakeLLM, ~2 min) | `pytest` |
| Lint | `ruff check mentora tests scripts alembic` and `ruff format --check mentora tests scripts alembic` |
| Types | `mypy mentora scripts` |
| Frontend type-check + build | `cd frontend && npm run build` |
| Real ML models (downloads ~250 MB once) | `pytest -m models` |
| PostgreSQL migration + pgvector (needs a DB) | `MENTORA_DATABASE_URL=postgresql+psycopg://mentora:mentora@localhost:5432/mentora pytest -m postgres` |
| Red-team suite only | `pytest tests/redteam` |
| Regenerate agent golden files after a prompt change | `UPDATE_GOLDEN=1 pytest tests/unit/agents`, then review the diff |

## 4. Full stack with Docker Compose

```bash
cp .env.example .env                         # set MENTORA_SESSION_SECRET, keys, LTI values
docker compose up --build                    # api :8000 (serves /app), worker, postgres, redis
docker compose exec api python scripts/seed_demo.py
```

The API container runs `alembic upgrade head` on start. With compose, end-of-session
memory jobs run in the Celery worker (`MENTORA_JOBS__MODE=celery`).

## 5. Moodle (LTI 1.3)

1. Start a dev Moodle: `git clone --depth 1 -b MOODLE_405_STABLE https://github.com/moodle/moodle.git lms/moodle`,
   then `docker compose --profile lms up`, and finish the Moodle installer at
   http://localhost:8080.
2. In Moodle go to *Site administration > Plugins > Activity modules > External tool >
   Manage tools > Configure a tool manually*:
   - Tool URL: `http://localhost:8000/lti/launch`
   - LTI version: 1.3; Public key type: Keyset URL (leave blank for now)
   - Initiate login URL: `http://localhost:8000/lti/login`
   - Redirection URI: `http://localhost:8000/lti/launch`
3. Moodle then shows the Platform ID (issuer), Client ID, Deployment ID, the
   authentication request URL and the public keyset URL. Put them in `.env`:
   `MENTORA_LTI_ISSUER`, `MENTORA_LTI_CLIENT_ID`, `MENTORA_LTI_DEPLOYMENT_IDS=["<id>"]`,
   `MENTORA_LTI_AUTH_LOGIN_URL`, `MENTORA_LTI_KEY_SET_URL`.
4. Add the tool to a course as an activity. Students launch as learners. Teachers and
   managers launch into the teacher console.
5. Inside the Moodle iframe, browsers need `MENTORA_COOKIE_SAMESITE=none` and
   `MENTORA_COOKIE_HTTPS_ONLY=true`, so serve Mentora over HTTPS.
6. In production, set `MENTORA_DEV_LOGIN=false`.

Roster and grade passback are not implemented (see docs/decisions.md D31).

## 6. Your course

- Concepts: replace `data/concepts.yaml` (20–40 concepts, prerequisites as a DAG,
  `starts_on` for course weeks).
- Quiz items: a YAML file like `data/sample/items.yaml`, then
  `python scripts/seed_demo.py --items <file>`.
- Question bank: `data/sample/question_bank.yaml` holds 1000 generated multiple-choice
  questions (50 per sample concept, 1 in 5 marked graded). `seed_demo.py` loads it
  automatically (`--bank <file>` to use another). Regenerate with
  `python scripts/generate_question_bank.py [--per-concept N --seed S]`. Every answer key is
  computed by running the question's code, and `tests/unit/test_question_bank.py` re-checks
  each key independently from the stored text. Practice rounds draw 5, 10 or 20 random
  questions from a topic, unseen ones first.
- Course weeks: the tutor uses notes up to the current course week, or up to the week of
  the topic the learner is working on if that is later.
- Explicit requests: with `policy.explore_on_requests: false` (default), collect mode gives
  a learner who asks for a hint, example, explanation, practice question or answer the
  rule policy's choice (logged with propensity 1) instead of exploring on that turn.
- Material (md, txt, pdf, pptx, FAQ yaml): `python scripts/ingest_corpus.py --corpus <dir>`.
  Passages that look like instructions to the tutor are quarantined and listed.
- Retrieval audit: write about 200 questions with `expected_passage_ids`, then run
  `python scripts/rag_audit.py --retrieval-only`. The full audit (with the LLM) costs money
  on `hosted`.

## 7. The learning loop

| Step | Command |
|---|---|
| Replay a scripted session and see every decision | `python scripts/replay_session.py data/sample/sessions/demo_session.yaml` |
| Simulated logs in a separate DB (debugging only) | `python scripts/simulate_logs.py --sessions 120 --db sqlite:///./simulated.db` |
| Train + evaluate + gate a policy | `python scripts/train_policy.py` (add `--db ... --label simulation` for simulated data) |
| Reward λ-sensitivity (simulation) | `python scripts/reward_sensitivity.py` |
| Train KT models and the tactic HMM | `python scripts/train_learner_models.py [--assistments <csv>] [--hmm-from-db]` |

A candidate that passes the gate appears in *Teacher console > Policies* with its report.
It changes nothing until a teacher approves it. Approval activates it and retires the
previous policy; restart the API to load it. If the gate fails, the reasons are stored
and the current policy stays.

ASSISTments 2009-2010 skill-builder data: download it from the ASSISTments website
(registration required), save it under `data/assistments/` (git-ignored), and pass
`--assistments`.

## 8. Operations

- **Load test** against a running server: `python scripts/load_test.py --learners 30`.
  SQLite serialises writes, so use PostgreSQL for real numbers.
- **Configuration**: every tunable value is in `mentora/config/defaults.yaml`. Override
  with `MENTORA_<SECTION>__<KEY>` (e.g. `MENTORA_SAFETY__THETA_PRE=0.6`,
  `MENTORA_APP__MODE=static` for the control arm).
- **Privacy**: learner IDs are salted pseudonyms (set `MENTORA_PSEUDONYM_SALT` once and
  keep it). Learner memory older than `privacy.retention_days` is purged at session end.
  Learners can view and delete their memory on *My learning*.
- **Before the pilot**: verify the support resources (`safety.support_resources`), have
  the distress lexicon and coding manual reviewed, set the reward weights, and replace the
  synthetic course data.

## 9. Data rules

Only synthetic data goes in `data/`. Real learner data is never committed: `*.db`,
`data/private/`, `models/` and `reports/` are git-ignored.
