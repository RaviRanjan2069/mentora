# Schema v1 (frozen)

Source of truth: `mentora/db/models.py`. The migration `alembic/versions/0001_schema_v1.py`
is written out in full, and `tests/unit/test_migration_matches_models.py` checks that it
emits exactly the DDL the models produce. **Any change after v1 needs a new Alembic
migration.** Do not edit 0001.

Conventions: all timestamps are `timestamptz` in UTC. JSON columns are `jsonb` on
PostgreSQL. Embeddings are `vector(384)` (pgvector, `all-MiniLM-L6-v2`). Constraint names
follow `pk_/fk_/uq_/ck_<table>_…`.

## Tables

| Table | Purpose | Key columns |
|---|---|---|
| `learners` | Pseudonymous learner | `id` (salted-HMAC pseudonym), `gender`, `prior_achievement_tercile` (fairness check only) |
| `courses` | Course | `code` (unique), `lti_context_id` |
| `concepts` | Knowledge components | `course_id`, `key` (unique per course) |
| `concept_prerequisites` | Prerequisite edges (DAG) | `concept_id`, `prerequisite_id`, no self-edges |
| `items` | Quiz items | `graded` (integrity rules apply), `item_type`, `answer_key` |
| `item_concepts` | Item ↔ concept tags | |
| `sessions` | One tutoring session | `mode` ∈ {adaptive, static}, `policy_version` |
| `events` | One xAPI statement each | `statement` (full jsonb, source of truth) + denormalised `verb`, `turn`, `action_id`, `propensity`, `policy_version`, `escalated` |
| `goals` | Learner goals | `concept_keys`, `smart_score`, `status` ∈ {active, attained, abandoned} |
| `plans` | Plan for a goal | `steps` (jsonb), `progress` ρ ∈ [0, 1] |
| `memory_items` | Reflective memory | `scope` ∈ {learner, course}, `embedding`, `n_plus`, `n_minus`, `quality`, `status` ∈ {active, pending_review, pruned} |
| `transitions` | Offline-RL data (s, a, μ, r, s′) | `state`/`next_state` (float lists), `action_id`, `propensity` ∈ (0, 1], `reward`, `policy_version`; unique (`session_id`, `t`) |
| `policies` | Policy registry | `version`, `type`, `config`, `metrics`, `status` ∈ {candidate, approved, rejected, active, retired}, `approved_by`, `reasons` |
| `escalations` | Teacher inbox | `reason`, `status` ∈ {open, answered, closed}, `teacher_response` |
| `teacher_rules` | Structured rules for the filter | `rule` (jsonb, e.g. `{"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}`) |
| `corpus_passages` | RAG passages | `id` (citable), `embedding`, `concept_keys`, `section`, `week` |
| `consents` | Consent records | `consent_type` ∈ {tutoring, research_logging}, `granted`, `form_version` |

`transitions.reward` and `next_state` are NULL when the row is written. They are filled
in at the next step, once the reward is known.

## xAPI statements

Every learner, LMS and tutor event is an xAPI statement (`mentora/logging_xapi/statements.py`):

- **actor**: `Agent` with `account = {homePage: <XAPI_BASE>, name: <pseudonym>}`
- **context.registration**: the session id
- **context.extensions[`…/extensions/turn`]**: the turn index

| Event | Verb | Object |
|---|---|---|
| Learner chat message | `adlnet …/commented` | `…/sessions/<id>/chat`, text in `result.response` |
| Quiz answer | `adlnet …/answered` | `…/items/<id>`, `result.success`, confidence in `result.extensions[…/confidence]` |
| Tutor action | `…/verbs/received` | `…/actions/<action_id>`, reply text in `result.response` (absent for a silent WAIT) |

Tutor statements carry `context.extensions[…/extensions/tutor-action]`:

```json
{
  "policy_version": "rule-v1",
  "action": {"agent": "ContentTutor", "move": "graded_hint", "style": "Socratic"},
  "propensity": 0.62,
  "filter_outcome": {
    "feasible_action_ids": ["ContentTutor.graded_hint.Socratic", "WAIT", "ESCALATE"],
    "removed": {"integrity": ["ContentTutor.worked_example.Socratic"]}
  },
  "retrieved_passage_ids": ["syn-w2-p03"],
  "escalated": false,
  "prompt_version": "content_tutor/graded_hint/v1",
  "model": "fake"
}
```

Validation rejects a propensity outside (0, 1], an action outside
`feasible_action_ids`, and ESCALATE without `escalated: true`. Action ids are
`<Agent>.<move>.<Style>`, or `WAIT` / `ESCALATE`.

The `LRSClient` protocol (`store`, `store_many`, `query`) is implemented by
`SqlLRSClient` on the `events` table. Storing the same statement twice is a no-op. Reusing
an id with different content raises `StatementConflictError`, the equivalent of xAPI 409.

## Additions after v1 (no table changes)

These were added inside xAPI statements, so the frozen tables did not change.

| Where | Field | Meaning |
|---|---|---|
| tutor-action extension | `action_probs` | the full behaviour distribution over F(s); validated to sum to 1, to stay inside F(s), and to give `propensity` for the chosen action |
| tutor-action extension | `memory_item_ids` | memory items recalled into the prompt (their quality is updated at session end) |
| tutor-action extension | `decision_reason` | why the policy chose the action (shown in the teacher console) |
| learner message `result.extensions` | `…/extensions/srl-tags` | the 8 SRL indicators for the message |
| quiz answer | `result.duration`, `…/extensions/hints-used`, `…/extensions/attempt`, `…/extensions/confidence` | behaviour features for knowledge tracing and calibration |
| LMS events | verbs `initialized` / `terminated` (session), `launched` (item presented), `experienced` (material opened) | |

Course weeks come from `course.starts_on` in `data/concepts.yaml`. MCQ options are part of
`items.text`, one `(A) …` line per option.
