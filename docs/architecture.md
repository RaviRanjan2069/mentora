# Mentora architecture

Mentora (Python package `mentora`) is one FastAPI service plus a Celery worker, with
MongoDB, Redis, and a React frontend that the API serves at `/app`.

## One tutoring turn (`mentora/orchestrator/turn.py`)

```
Learner message / quiz answer / LMS event (session start, item presented)
  1. log it as an xAPI statement (SRL tags attached)          logging_xapi/
  2. update the learner model (mastery, phase, tactic,         learner_model/tracker.py
     SRL indicators, calibration, engagement)
  3. build numeric state s_t (28 features)                      learner_model/state.py
  4. close the previous step: reward r_{t-1}, s' = s_t          reward/reward.py
  5. safety filter F(s_t): well-being, integrity,              safety/feasibility.py
     prerequisites, load, teacher rules
  6. policy picks a_t in F(s_t) with propensity mu              policy/ (rule | learned) +
     (collect: safe softmax; deploy: argmax)                    policy/collect.py
  7. recall top-5 memory items; retrieve passages (RAG moves)   memory/, rag/
  8. the chosen agent phrases a_t with the LLM                  agents/
  9. grounding check (regenerate once, else "not certain"       rag/grounding.py
     + escalation) and integrity check (regenerate once,        safety/integrity_check.py
     else a fixed safe reply); fixed "why this suggestion"
 10. log the tutor action (policy version, action, mu, full     logging_xapi/statements.py
     distribution, F(s), passages, memory ids, reason)
 11. store transition (s_t, a_t, mu, -, -) for offline RL       transitions table
WAIT: send nothing, or a grounded literal answer (off-topic questions get a fixed reply).
ESCALATE: escalation row for the teacher; support resources if distress.
```

After each session (inline or Celery): `memory/reflect_curate.py` updates item quality from
the session return, proposes new insights, curates them (vetoes for instruction-like,
sensitive or unevidenced text), merges, prunes, and sends course-wide items to the teacher
queue.

Between policy versions: `offline/train.py` builds the dataset (split by learner), trains a
candidate (ensemble CQL or tabular), runs doubly robust OPE against the current policy, a
fairness check, an overlap (ESS) check and a constraint check in simulation, then registers
the candidate (awaiting teacher approval) or records why the current policy stays.

## Package map

| Package | What it does |
|---|---|
| `api/` | FastAPI app, signed-cookie sessions, LTI 1.3 launch, learner and teacher routes |
| `orchestrator/` | the turn, runtime rebuild from the log, session builder, scripted replay |
| `learner_model/` | DKT / AKT-style KT, tactic HMM, SRL tagger, phase rules, calibration, engagement, state |
| `policy/` | frozen action catalogue, rule policy, Collect/Deploy behaviour policy, registry |
| `safety/` | feasibility filter, integrity check, distress detection, teacher rules |
| `agents/` | five agents and the team facade (WAIT/ESCALATE never call the LLM) |
| `rag/` | ingest (with injection quarantine), hybrid retrieval, rerank, grounding, audit |
| `memory/` | store, recall, reflect-and-curate, Celery-queued wrapper |
| `reward/` | reward function and the (s, a, mu, r, s') dataset builder |
| `offline/` | simulator (debugging only), tabular + ensemble CQL, DR OPE, fairness, report, pipeline |
| `llm/` | provider-agnostic client; hosted (Claude), local (OpenAI-compatible), offline templates, fake |
| `redteam.py`, `loadtest.py` | adversarial suite and concurrent-learner load test |

## Invariants and where they are enforced

| Rule | Enforcement | Test |
|---|---|---|
| The policy decides, the LLM only phrases | agents receive a chosen action; prompts are per action | `tests/unit/agents` golden files |
| The safety filter is deterministic Python | `safety/feasibility.py`; agents refuse actions outside F(s) | `tests/unit/safety/test_filter_properties.py` (hypothesis) |
| Every tutor action logged with propensity | `TutorActionExtension` validates mu, full distribution and F(s); DB CHECK | `tests/unit/orchestrator/test_turn_e2e.py` |
| No exploration beyond a safe softmax inside F(s) | `policy/collect.py`; ESCALATE is never explored | `tests/unit/policy` |
| New policies only after OPE, fairness and teacher approval | `offline/train.py` gate + `policy/registry.py` | `tests/unit/offline` |
| Free text never enters the policy state | state vector of 28 floats; requests become a category | `tests/unit/learner_model` |
| Academic integrity | filter (no Directive / worked example on graded items) + output check | `tests/redteam` with a malicious LLM |
| Well-being | distress -> only ESCALATE + resources | `tests/redteam`, `tests/unit/safety` |
| No motivational pep talks | guard prompt; templates give specific feedback only | golden files |
| Privacy | pseudonyms, retention purge, learner memory view/delete | `tests/unit/memory`, `tests/unit/api` |
| Every number in config | `mentora/config/defaults.yaml` | `tests/unit/test_settings.py` |

## Modes

`app.mode = adaptive` is the full system. `app.mode = static` is the study's control
condition: same agents, RAG and UI, the fixed rule policy in deploy mode, and no memory.
`sessions.mode` records which mode each session ran in.
