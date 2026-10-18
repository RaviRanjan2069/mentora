# Mentora

**Mentora** is a Self-Learning Strategy Agent: an LLM- and RAG-based tutor that helps
university students plan, monitor and reflect on their learning (Zimmerman's Forethought,
Performance and Self-reflection phases). It improves its tutoring strategy from logged
interactions with conservative offline reinforcement learning, but only behind a
deterministic safety filter, off-policy evaluation, a fairness check and teacher approval.

> **Status:** all build milestones (M1–M9) are implemented and tested on synthetic data.
> **Nothing has been evaluated with real learners.** The course content, quiz items,
> history and policy results in this repository are synthetic or simulated.

## Try it (no Docker, no API key)

Needs a MongoDB server (local, default `mongodb://localhost:27017/mentora`, or Atlas).

```bash
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[ml]"
cd frontend && npm install && npm run build && cd ..
python scripts/seed_demo.py --with-history
uvicorn mentora.api.main:app --reload                  # open http://127.0.0.1:8000/app/
```

Sign in as a **Student** to chat with the tutor, practise quiz items with confidence
ratings, and see goals, calibration, mastery and "my memory". Sign in as a **Teacher** to
answer escalations, inspect every decision and why it was made, edit rules, review
course-memory proposals, and approve or reject policy candidates.

## What is inside

- **Tutoring turn**: xAPI logging, learner model, a 28-feature numeric state, the safety
  filter F(s), policy choice with logged propensity, an agent reply grounded in course
  passages, integrity and grounding checks, and a fixed "why this suggestion" line.
- **42 actions**: Planner, Monitor, ReflectionCoach, ContentTutor and PeerBroker moves in
  Socratic or Directive style, plus WAIT and ESCALATE. The policy decides; the LLM only
  phrases.
- **Learner model**: DKT and AKT-style knowledge tracing, a study-tactic HMM, an SRL
  indicator tagger, calibration, engagement, and a self-directedness stage.
- **Safety**: well-being escalation with support resources, academic integrity on graded
  items, prerequisites, load limits, teacher rules, prompt-injection defences, and
  quarantine of poisoned course files.
- **Reflective memory** with a curator that blocks poisoning, a teacher review queue for
  course-wide items, and learner view/delete.
- **Offline loop**: dataset builder, simulator (debugging only), tabular and ensemble-CQL
  policies, doubly robust OPE with a bootstrap lower bound, fairness and overlap checks,
  a teacher report, and approval.
- **Integration**: LTI 1.3 launch from Moodle, a React web app, Docker Compose and CI.

LLM back-ends: `auto` (default: Claude when `ANTHROPIC_API_KEY` is set in the environment
or `.env`, otherwise `offline` templates), `hosted` (Claude via the Anthropic SDK), `local`
(any OpenAI-compatible endpoint such as Ollama), `offline`, and `fake` (tests).

## Documentation

| Doc | For |
|---|---|
| [docs/runbook.md](docs/runbook.md) | running, testing, Moodle setup, your course, the learning loop |
| [docs/deploy.md](docs/deploy.md) | free public demo on Render + MongoDB Atlas (₹0) |
| [docs/architecture.md](docs/architecture.md) | the tutoring turn, package map, invariants and their tests |
| [docs/schema.md](docs/schema.md) | MongoDB collections (schema v1-mongo) and xAPI statements |
| [docs/learner_model.md](docs/learner_model.md) | learner-model components and the state vector |
| [docs/coding_manual.md](docs/coding_manual.md) | SRL indicator definitions for human coders |
| [docs/decisions.md](docs/decisions.md) | every non-obvious design decision |

## Layout

```
mentora/      Python package: api, orchestrator, learner_model, policy, safety, agents,
              rag, memory, reward, offline, llm, logging_xapi, config, prompts, db
frontend/     React + TypeScript + Vite app (served by the API at /app)
data/         concepts.yaml + synthetic sample course (material, items, a scripted session)
scripts/      seed_demo, generate_question_bank, ingest_corpus, rag_query, rag_audit, replay_session,
              train_learner_models, simulate_logs, train_policy, reward_sensitivity, load_test
tests/        unit/, redteam/, models/ (real ML models), mongo/ (real MongoDB server)
docs/         see the table above
```

The previous Java "InterviewMentor" app is archived on the `legacy-interviewmentor` branch.
