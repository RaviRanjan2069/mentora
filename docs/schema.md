# Schema v1-mongo

Source of truth: `mentora/db/models.py` (documents) and `mentora/db/client.py` (indexes).
Mentora stores its data in MongoDB (docs/decisions.md D39). The entities and field names
are those of the earlier SQL schema v1; a document's primary key is stored as `_id`.
There are no migrations: `ensure_schema()` creates the indexes (idempotent) on API start
and in `scripts/init_db.py`, and records `{"_id": "schema", "version": "v1-mongo"}` in the
`meta` collection. A change that needs existing documents rewritten needs a one-off script.

Conventions: all timestamps are timezone-aware UTC, stored with millisecond precision.
Embeddings are float arrays of length 384 (`all-MiniLM-L6-v2`); similarity is computed in
Python (D17). Integer ids come from the `counters` collection.

What SQL used to enforce is enforced by `mentora/db/store.py`:

- **references** (`Document.__refs__`): inserts fail with `IntegrityError` when a referenced
  document does not exist; deleting a document deletes its children (cascade) or clears
  the reference (set-null), set-based, one query per collection and level;
- **constraints** (`Document.validate()`): the old CHECK constraints (status values,
  propensity in (0, 1], memory scope, no self-prerequisite, embedding length);
- **unique indexes**: `courses.code`, `concepts (course_id, key)`, `transitions (session_id, t)`;
- **units of work**: `StoreFactory.begin()` commits on success and undoes everything written
  since the last commit on an error, from an undo journal. A standalone MongoDB has no
  multi-document transactions, so a crash in the middle of a write can leave it partial.

## Collections

| Collection | Purpose | Key fields |
|---|---|---|
| `learners` | Pseudonymous learner | `_id` (salted-HMAC pseudonym), `gender`, `prior_achievement_tercile` (fairness check only) |
| `courses` | Course | `code` (unique), `lti_context_id` |
| `concepts` | Knowledge components | `course_id`, `key` (unique per course), `prerequisite_ids` (DAG edges, no self-edges) |
| `items` | Quiz items | `graded` (integrity rules apply), `item_type`, `answer_key`, `concept_ids` (concept tags) |
| `sessions` | One tutoring session | `mode` ∈ {adaptive, static}, `policy_version` |
| `events` | One xAPI statement each | `statement` (full document, source of truth) + denormalised `verb`, `turn`, `action_id`, `propensity`, `policy_version`, `escalated`; `seq` (insertion order, breaks timestamp ties) |
| `goals` | Learner goals | `concept_keys`, `smart_score`, `status` ∈ {active, attained, abandoned} |
| `plans` | Plan for a goal | `steps`, `progress` ρ ∈ [0, 1] |
| `memory_items` | Reflective memory | `scope` ∈ {learner, course}, `embedding`, `n_plus`, `n_minus`, `quality`, `status` ∈ {active, pending_review, pruned} |
| `transitions` | Offline-RL data (s, a, μ, r, s′) | `state`/`next_state` (float lists), `action_id`, `propensity` ∈ (0, 1], `reward`, `policy_version`; unique (`session_id`, `t`) |
| `policies` | Policy registry | `_id` = `version`, `type`, `config`, `metrics`, `status` ∈ {candidate, approved, rejected, active, retired}, `approved_by`, `reasons` |
| `escalations` | Teacher inbox | `reason`, `status` ∈ {open, answered, closed}, `teacher_response` |
| `teacher_rules` | Structured rules for the filter | `rule` (e.g. `{"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}`) |
| `corpus_passages` | RAG passages | `_id` (citable passage id), `embedding`, `concept_keys`, `section`, `week` |
| `consents` | Consent records | `consent_type` ∈ {tutoring, research_logging}, `granted`, `form_version` |
| `accounts` | A person's sign-in identity (D41) | `username` (permanent user id, unique), `email` (unique), `email_verified`, `role`, `name`, `gender`, `password_hash` (scrypt), `session_version`, lockout fields, `learner_id` (the pseudonym) |
| `account_photos` | Profile photo | `_id` = account id, small JPEG/PNG/WebP bytes, `content_type` |
| `teacher_links` | Student → teacher requests | `student_id`, `teacher_id`, `status` ∈ {pending, accepted, declined}; unique pair |
| `class_codes` | A teacher's permanent class code, given at sign-up | `_id` = the code (10 random digits, unique), `teacher_id` (one code per teacher), `teacher_username`, `teacher_name` (copies for reading the data) |
| `subjects` | Subjects such as Java or DBMS (D42) | `key` (lower case name, unique), `name`, `created_by` (account id, or none for the starting list) |
| `folders` | One teacher's folder for one subject | `subject_id`, `teacher_id` (unique together), `about` |
| `enrollments` | A student enrolled in a folder | `folder_id`, `student_id` (unique together) |
| `resources` | Material in a folder | `folder_id`, `kind` (file, link, note), `title`, `description`, `url`, `text`, `file_name`, `content_type`, `size` |
| `resource_chunks` | Parts of an uploaded file (1 MB each) | `_id` = `<resource id>:<n>`, `resource_id`, `n`, `data` |
| `quizzes` | A teacher's quiz | `folder_id`, `title`, `questions` (embedded: id, kind, text, options, answer, points, topic), `time_limit_min`, `max_attempts`, `show_answers`, `published` |
| `quiz_attempts` | A student's attempt | `quiz_id`, `student_id`, `answers`, `results`, `score`, `max_score`, `started_at`, `submitted_at`, `late` |
| `bank_questions` | A subject's practice questions (D43) | `subject_id`, `topic`, `text`, `options`, `answer` (index), `explanation`, `difficulty`, `seed_key` (starter questions), `author_id` (teachers' questions), `edited`, `hidden` |
| `practice_rounds` | A student's round of 10 practice questions | `student_id`, `subject_id`, `plan` (question, topic, why chosen, shown option order), `results` (choice, correct, time), `focus`, `score`, `total`, `started_at`, `finished_at` |
| `roadmaps` | A student's week-by-week plan for a goal (D44) | `student_id`, `goal`, `subject`, `subject_id`, `level`, `pace`, `source` (curated or ai), `weeks` (embedded tasks with done state and progress), `adaptations` (what changed and why), `status`, `start_date` |
| `email_tokens` | One-time email links | `_id` = sha256 of the token, `purpose` ∈ {verify, reset}, `expires_at`, `used` |
| `counters`, `meta` | Integer id sequences; schema version | |

Deleting a learner removes their sessions, events, goals (and plans), memory, transitions,
escalations and consents. Deleting a session removes its events and transitions and clears
`session_id` on goals, escalations and course memory.

`transitions.reward` and `next_state` are null when the document is written. They are
filled in at the next step, once the reward is known.

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
`SqlLRSClient` on the `events` collection (the name predates MongoDB). Storing the same statement twice is a no-op. Reusing
an id with different content raises `StatementConflictError`, the equivalent of xAPI 409.

## Additions after v1 (inside statements)

These were added inside xAPI statements, so no collection changed.

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
