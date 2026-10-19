# Decision log

Each entry records a non-obvious choice: what was decided and why.

## D1 — One name everywhere: Mentora (M1, renamed after M2)
The product, website, API title, Python package (`mentora`), environment variables
(`MENTORA_*`), database user and name, and logger names all use **Mentora**. The package
folder is lowercase because Python package names are conventionally lowercase. The project
design documents describe the same system under its earlier working name.

## D2 — Legacy Java app archived, not merged (M1)
The repo previously held a Spring Boot "InterviewMentor" app. None of it fitted Mentora: its
interview MCQs are not course material. It is archived on the `legacy-interviewmentor`
branch. The bundled JDK, build output and H2 database were not committed, because the
database may have held real user records (design rule 9).

## D3 — SQLite for unit tests, PostgreSQL in CI (M1)
*Superseded by D39 (MongoDB; tests use mongomock, CI a `mongo:7` service).*
`pytest` must run offline with no Docker. Models use portable types (`mentora/db/types.py`):
`jsonb` → JSON and `vector(384)` → JSON list on SQLite, plus a UTC-aware datetime type.
Postgres-only behaviour (migrations, pgvector) is covered by `tests/postgres/`, marked
`@pytest.mark.postgres`. CI runs those against a `pgvector/pgvector:pg16` service.

## D4 — Migration 0001 written out in full (M1)
*Superseded by D39 (no migrations; indexes are the schema).*
The migration does not call `metadata.create_all()`, which would silently change v1
whenever a model changes. It lists every table explicitly. A unit test compares its
offline SQL with the DDL compiled from the models, so the two cannot drift.

## D5 — `events.statement` is the source of truth (M1)
The full xAPI statement is stored as a JSON document (jsonb before D39). Columns such as `action_id`, `propensity` and
`policy_version` are denormalised copies for querying, written by `SqlLRSClient` only.

## D6 — xAPI IRIs use a placeholder root `https://mentora.example/xapi` (M1)
xAPI only needs IRIs to be unique and stable. Replace this with a domain the team controls
before collecting study data. After that, never change it, because old statements keep
the old IRIs.

## D7 — Tutor statements use the learner as actor (M1)
Each tutor action is logged as "learner *received* action X" (custom verb `…/verbs/received`)
so every statement belongs to one learner. That makes per-learner queries, deletion and
retention simple.

## D8 — Policy status adds `retired` (M1)
The spec lists candidate / approved / rejected / active. `retired` marks a formerly active
policy after a newer one is approved, so the registry keeps the full history.

## D9 — Reward λ weights are placeholders (M1)
The values in `defaults.yaml` (`lambda_k` 1.0, `lambda_s` 0.5, …) are starting points, not
tuned values. The team sets them before M8, and they are frozen per policy version.

## D10 — Dev Moodle is an opt-in compose profile (M1)
Bitnami's Moodle images are no longer freely maintained. The `moodle` service uses
`moodlehq/moodle-php-apache` with a Moodle checkout mounted from `./lms/moodle`, under
`--profile lms`, so a plain `docker compose up` does not depend on it. Full setup comes
in M7.

## D11 — pgvector ANN indexes deferred to M2 (M1)
*Superseded by D17 and D39.*
Corpus and memory sizes are small (hundreds to low thousands of rows), so exact search is
fine for now. If needed, M2 adds an HNSW index through migration 0002.

## D12 — Hosted LLM: Claude Opus 5.5 via the official SDK, refusal fallbacks on (M2)
The hosted back-end uses the `anthropic` Python SDK with `claude-opus-5-5` at
`effort: medium`, and server-side refusal fallbacks (`fallbacks: "default"`, beta
`server-side-fallback-2026-07-01`). If the model declines, the API re-runs the request on
the model Anthropic recommends for that refusal category. A refusal that survives the
fallback raises `LLMRefusalError`. Model, effort and fallbacks are config values
(`llm.hosted_*`), so switching to `claude-sonnet-5-5` to cut cost is a one-line change that
is the team's call. `LLMClient` owns retries (exponential backoff on 429/5xx/timeouts), so
the SDK's own retries are off and nothing is retried twice.

## D13 — Token counts are approximate (M2)
Chunk sizes use a model-free count (words + punctuation) so ingest needs no tokenizer
download. One catch: `all-MiniLM-L6-v2` embeds at most 256 word-pieces, so the tail of a
long 300-token passage is not in its embedding. BM25 and the cross-encoder still see the
full text. If recall suffers on real material, lower `rag.chunk_tokens` to ~220.

## D14 — Claim detection is a strict heuristic (M2)
The grounding check treats a sentence as a factual claim unless it is a question or opens
like an instruction or social phrase ("Try…", "What…", "You…", "Great…"). This is
deliberately strict on statements, so most mistakes lead to regeneration or escalation, not
an unchecked claim. Known gap: a claim phrased as "You can use // for floor division" is
treated as non-factual. The M9 red-team suite should measure this. If needed, swap in an
LLM claim detector behind the `ClaimDetector` protocol.

## D15 — Default grounding judge is a local NLI model (M2)
`cross-encoder/nli-deberta-v3-small` runs locally and for free, and is deterministic. The
LLM judge (`rag.grounding_judge: llm`) is available but adds one hosted call per cited
sentence. Citation tags are stripped before judging, because `[id]` tokens flip the NLI
model to "neutral".

## D16 — Offline stand-ins are for tests only (M2)
`HashingEmbedder`, `LexicalReranker` and `LexicalEntailmentJudge` exist so that `pytest`
needs no model downloads. Production config uses the real models. `tests/models/`
(`pytest -m models`) checks the real models directly.

## D17 — Retrieval scores in memory, not in pgvector (M2)
A course has hundreds of passages, so BM25 and cosine scores are computed in numpy over
an index loaded from `corpus_passages`. Embeddings are stored with the passages (a pgvector
column before D39, a float array since), so a vector index could be added later.
This supersedes D11.

## D18 — Concept tags on passages come from keyword matching (M2)
A passage is tagged with a concept when its name, key or alias appears in the text
(singular or plural). Tags are noisy: "a built-in function" tags `functions`. They are
retrieval hints only and never feed the safety filter. Item ↔ concept tags for the
prerequisite rule come from `item_concepts`, which the teacher sets. Add `aliases` to
`concepts.yaml` to improve tags.

## D19 — `/api/rag/search` is unauthenticated for now (M2)
The search endpoint powers the home-page demo and returns course passages only (no learner
data). It is placed behind LTI session auth in M7.

## D20 — Action catalogue v1: 42 actions (M3)
22 moves × 2 styles, except four question-only moves that are Socratic-only
(`elicit_smart_goal`, `socratic_reflection`, `attribution_question`, `confidence_check`).
That gives 40 agent actions plus WAIT and ESCALATE. Unsolicited moves (counted by the load
limit) are all Monitor and PeerBroker moves plus `recall_past_goals`. RAG moves are
`graded_hint`, `worked_example`, `concept_explanation` and `textbook_link`. Each move's
phase is a hint for the rule policy; the safety filter does not restrict by phase. The id
list is pinned by `tests/golden/catalogue_v1.txt`. Any change means catalogue v2.

## D21 — Agent prompts are composed from versioned fragments (M3)
The design asks for a template per agent × move × style. Mentora builds each action's
prompt from one shared turn template plus four fragment files: guards, role, move and
style (31 files in total). 40 hand-copied templates would drift apart. Every action's full
prompt is still pinned by its own golden file in `tests/golden/agents/`, and the composite
version tag (e.g. `agents/turn@v1;…;agents/styles/Socratic@v1`) is logged as
`prompt_version` on the tutor-action statement.

## D22 — WAIT and ESCALATE are always available; teacher rules cannot remove them (M3)
The filter applies well-being, integrity, prerequisites, load and teacher rules, in that
order. Only well-being can remove WAIT (distress leaves only ESCALATE). A teacher rule that
targets WAIT or ESCALATE is rejected when it is loaded. A malformed rule raises instead of
being skipped, so a teacher's instruction is never silently ignored.

## D23 — Distress detection is a reviewed lexicon, and everyday study stress does not escalate (M3)
`mentora/safety/distress_lexicon.yaml` holds two tiers of patterns: crisis (self-harm,
suicidal thoughts) and distress (can't cope, hopeless, panic attacks, overwhelmed). Plain
exam stress ("I'm stressed about the quiz") is deliberately *not* matched, so the
escalation rate stays near the 5% target. This is a reading of "any expression of
distress" that the team and the university counselling service must confirm before the
pilot. The support-resource list includes Tele-MANAS (14416). Verify it and add the campus
contact.

## D24 — Output-side integrity check is heuristic (M3)
For graded items, a reply fails if it contains the answer key, a giveaway phrase ("the
answer is…", "option B is…") or a code block longer than `safety.max_solution_code_lines`.
A failing reply is regenerated once, then replaced by a fixed safe reply. The answer key
is never sent to the LLM. Known gap: a paraphrased answer that avoids the key's exact
wording. The M9 red-team suite should probe this.

## D25 — The filter receives prerequisite mastery from its caller (M3)
`FilterContext.prereq_mastery` is the lowest mastery among the practice target's
prerequisites, computed by the orchestrator from the learner model (M4) and the concept
graph. `None` means the target has no prerequisites. This keeps the filter pure and
easy to test exhaustively.

## D26 — Knowledge tracing is concept-level; AKT is simplified (M4)
Both models predict correctness per concept, since items are tagged with concepts and
"one representative item per concept" is simply that concept. The AKT-style model keeps
the core ideas (attention over past interactions, learned distance decay, behaviour
features in the interaction embedding) but has one layer and no Rasch difficulty term.
The training script reports held-out-learner AUC. On synthetic data both models reach
about 0.74–0.77, which is a sanity check only. Real AUC needs ASSISTments or course
data. Until a model is trained, `mastery_model: count` (a Beta posterior) is used.

## D27 — Tactic HMM uses several EM restarts (M4)
Baum-Welch finds local optima. With one start, BIC picked 4 states on data generated from
3. Each H is now fitted from `hmm_restarts` initialisations and the best likelihood is
kept. The online forward filter is our own code and is tested against hmmlearn.

## D28 — Tagger and reflector fall back to rules without an LLM (M4, M6)
`auto` mode uses the LLM only for the hosted or local back-ends. Otherwise the SRL tagger,
the rubric scores and the memory reflector use keyword and checklist heuristics. These are
weaker and must be checked against human coding (`docs/coding_manual.md`) before they
feed the reward in a study.

## D29 — Rule policy details (M5)
The rules, in order: elicit a goal at session start; revisit an open goal at the start of
a new session (`recall_past_goals`); planning requests; reflection after a completed quiz;
a hint after two wrong answers or a hint/answer request; an explanation when asked; a
confidence check before every third item; otherwise WAIT. Collect mode uses temperature
0.2, so the rule's choice gets about 80% probability.

## D30 — How the reward is computed in practice (M5)
ΔK and the calibration term are read from consecutive state vectors. The goal, reflection
and learner-initiative flags come from the events in between. A goal is attained when
every goal concept reaches `goals.attain_mastery` (0.7), and plan progress is the share of
goal concepts at that level. If the server restarts mid-session, the "help before
attempt" flag of the one open step is lost (it is recomputed as false).

## D31 — LTI 1.3 implemented with PyJWT, not PyLTI1p3 (M7)
PyLTI1p3 ships adapters for Django and Flask, not FastAPI. The launch needs only OIDC
login initiation, state + nonce, and RS256 id_token validation against the platform JWKS,
so it is implemented directly in `api/lti.py` (about 150 lines) and tested with a
simulated platform that signs real tokens. Roster (NRPS) and grade passback (AGS) are not
implemented yet. The dev Moodle in docker compose has not been run, because Docker is not
available on the development machine.

## D32 — An offline template back-end makes the demo work without an API key (M7)
`llm.backend: offline` (the default) fills fixed per-move templates with the course
passage and concept. The UI shows a banner saying replies are templates, not AI. Every
other component (policy, filter, grounding, memory, logging) runs for real. Set
`MENTORA_LLM__BACKEND=hosted` and an Anthropic key for real replies.

## D33 — Memory curator: three vetoes plus weights (M6)
A candidate is admitted only if it is evidenced (its quote appears in the learner's own
words), non-sensitive and not instruction-like. Any failure gives score 0. Otherwise the
score is a weighted sum (`memory.curator_weights`) and must reach the 0.6 gate, which
rejects non-specific items. Known cost: a genuine reflection containing "always" or
"never" is rejected.

## D34 — Frontend served by the API, with hash routing and dev sign-in (M7)
The web app is served at `/app` (plain HTML/CSS/JS since D40), so there is one origin and no CORS. Hash routing
avoids server-side fallbacks. Dev sign-in (`MENTORA_DEV_LOGIN`) lets you test without
Moodle and must be off in production.

## D35 — Exploration never escalates by chance (M8)
In Collect mode, ESCALATE gets probability only when the proposer chose it, so teachers
never receive exploratory escalations. Learned policies therefore cannot be credited for
escalating where the logs never did (no support); that is the conservative direction.

## D36 — OPE gate also requires overlap (M8)
Doubly robust estimates for a candidate that rarely agrees with the logged actions are
mostly model extrapolation. The gate therefore also requires the per-decision effective
sample size to be at least `offline.min_ess_fraction` of the evaluation steps. The
fairness check counts as failed when no attribute has two groups with enough data.

## D37 — λ-sensitivity is measured in simulation (M8)
Transitions store only the total reward. `scripts/reward_sensitivity.py` records the
per-term rewards of simulated sessions and recomputes returns with each λ halved and
doubled. In simulation, λ_S moved the mean return most, while session rankings stayed
stable (Spearman ≥ 0.96).

## D38 — Red-team fixes (M9)
The suite attacks the system with a malicious LLM that always leaks answers. It led to:
answer-key detection for "the answer to the quiz is C", "pick C" and yes/no keys (outside
questions only); quarantine at ingest for course text that instructs the tutor; and a
fixed "outside this course" reply for off-topic questions, with no teacher escalation. A
mutation test switches the safety layer off and checks that the suite then fails.

## D39 — MongoDB instead of PostgreSQL/SQLite (deployment)
Requested for the public demo. All persistence moved from SQLAlchemy/Alembic to MongoDB
(`pymongo`; MongoDB Atlas free M0 in production, a local server in development, `mongomock`
in tests and for throwaway policy simulations). Same entities and field names as SQL
schema v1; link tables became embedded id lists (`Concept.prerequisite_ids`,
`Item.concept_ids`). `mentora/db/store.py` keeps the unit-of-work behaviour the code relied
on: identity map, dirty tracking (load, change attributes, commit), integer ids from a
`counters` collection, references checked on insert, set-based cascade / set-null deletes,
the old CHECK constraints in `validate()`, unique indexes, savepoints, and rollback from an
undo journal. Trade-offs: no multi-document transactions on a standalone server, so a
crash mid-commit can leave a partial write (Postgres was atomic); timestamps keep
milliseconds, so events carry a `seq` to keep insertion order on equal timestamps; Atlas
M0 allows 100 operations per second (a tutor turn uses about 25) and has no backups.
Schema v1 and its Alembic history are retired; the version is now `v1-mongo`.

## D40 — Web app in plain HTML, CSS and JavaScript (deployment)
Requested: no framework and no build step. The React/TypeScript/Vite app was rewritten as
native ES modules (`frontend/js`), one module per page, with the same CSS, pages, API calls
and behaviour. A small `h()` helper builds DOM nodes (text is never parsed as HTML) and
`render()` redraws a container while keeping the focused input and its caret, so pages can
redraw after any state change. The tutoring session is a small shared store (`session.js`)
that the Tutor, Practice and command palette subscribe to. FastAPI serves `frontend/` as is
with `Cache-Control: no-cache` (file names are not fingerprinted, so browsers revalidate by
ETag after a deploy). The Docker image lost its Node build stage; CI syntax-checks the
modules with `node --check`.

## D41 — Accounts with a permanent user id (deployment)
Requested: real sign-up and sign-in for students and teachers (user id, email, password, name,
gender, photo) and a way for students to join a teacher. `accounts` holds the person; learning
data stays keyed by the pseudonym `Account.learner_id`, so analytics and the offline loop are
unchanged. Passwords are hashed with scrypt; 5 wrong passwords lock an account for 15 minutes;
sign-up, sign-in and email requests are rate-limited per IP; the session cookie carries the
account's `session_version`, so a password change or reset signs out every other device.
Anyone can sign up as a teacher (no shared code since 2026-10-19); each teacher gets a permanent random 10-digit class code. A student finds a teacher by user id and sends a request;
the teacher accepts or declines (`teacher_links`). A teacher with an account sees only their
accepted students; escalations from students without a teacher go to every teacher so a distress
message always reaches someone. Moodle and development-sign-in teachers still see everyone.
Verification and password-reset links are sent through Brevo (only the token's hash is stored;
links expire and work once); without a Brevo key they are logged and accounts count as verified.
Photos are cropped and resized in the browser, checked by content on the server, and shown only
to the owner and linked teachers/students.
Each teacher gets one permanent class code at sign-up: 10 random digits, suggested on the form
(the teacher can ask for another before signing up), unique, never changed afterwards, and stored
with the teacher's user id and name. Teachers from before this get one on first visit; earlier
word codes keep working. A student who enters it sends the same request as searching by
user id, so the teacher still accepts; code attempts are rate-limited against guessing.

## D42 — Subjects with teachers' folders, material and quizzes

Mentora is organised by subject (Java, Python, DBMS, Machine Learning, ...). A teacher opens one
folder per subject ("Java by Dr. Ravi Singh"), picking a subject from the list or adding a new
one (names that differ only in capitals or spaces are the same subject). Students enrol in any
folder with one click, and the teacher can remove them. A folder holds material (uploaded files,
links, typed notes) and quizzes; only its teacher and enrolled students can open them.
Uploaded files are stored in MongoDB in 1 MB chunks, up to 10 MB each and 300 MB in total
(`subjects.*` settings), because Atlas M0 holds 512 MB for everything and Render's free disk is
wiped on every deploy; bigger material goes in as a link. File types are checked against the
file's first bytes and served with `nosniff` and a sandbox CSP.
Quizzes have single-answer, multiple-answer, true/false and short typed questions, each with
points and a topic. Grading is all or nothing per question; short answers ignore capitals,
spacing and surrounding punctuation. A quiz can have a time limit (answers after it plus a minute
are still graded but marked late), several attempts, and can show the right answers after
submitting. Once a student has taken a quiz its questions are frozen, so results stay comparable.
The analysis uses each student's best attempt per quiz; topics at 75% or more are strengths,
below 50% weaknesses. The AI tutor still works on the existing course; tying it to each
folder's material is later work.

## D43 — My Learning: adaptive practice from subject question banks

My Learning is now subject practice; the earlier goals, plans and tutor-memory page moved to
Goals & Plans. Every subject has a question bank: 100 Mentora starter multiple-choice questions
per subject (ten topics of ten, in `mentora/subjects_data/*.json`, loaded at start-up; only
missing ones are added, and questions a teacher edited or hid are never overwritten) plus
questions its teachers add one by one or by CSV. Starter questions are marked as such and have
not been reviewed by a teacher; any teacher of the subject may fix or hide them, while
teachers' own questions can be changed only by their author.
A student practises in rounds of 10 with immediate feedback and explanations. Rounds adapt:
topic mastery is (right + 1) / (answered + 2); slots go to topics in proportion to
(1 - mastery) plus a small share for every topic, with diminishing weight for repeated slots so
rounds stay mixed; within a topic, questions answered wrong come back first, then unseen ones;
the previous round's questions are avoided. Options are shuffled per round, so the stored
option order never gives answers away. A topic is a strength at 75% mastery and a weakness
below 60%, both after at least three answers. The dashboard shows subject and topic
percentages, strengths and weaknesses, and each round's score over time; a folder's Analysis
tab shows its enrolled students' practice in that subject.

## D44 — Goals & Plans: week-by-week roadmaps that adapt

Goals & Plans starts with a goal search ("How to learn Java from basic to advanced"). A goal
about one of the eight subjects (matched by name and common aliases such as DSA, SQL or full
stack) gets a hand-written roadmap (`mentora/subjects_data/roadmaps.json`): units from basics
through intermediate and advanced topics to a project, each with study topics, practice on the
subject's question-bank topics and a hands-on exercise, plus a checkpoint at the end of each
stage. The student's level shortens or skips the basics; the pace puts one or two units in a
week. Other goals are drafted by the AI tutor model when it is online (checked against a
schema, labelled as AI-written and possibly wrong, and taking up to a minute); when it is
offline the student is told which subjects have ready-made roadmaps.
Practice, review and checkpoint tasks tick themselves from My Learning answers given after the
roadmap was made (10 answers at 60%, checkpoints 15 at 70%); the rest the student ticks.
Adapting is rule-based and logged with its reason: a topic from the weeks so far scored below
60% (three or more answers) gets a review task in the current week; a future week whose topics
the student already masters (80%+ with five or more answers) becomes optional; falling two or
more weeks behind moves the dates. The page shows roadmaps only; the notes the tutor remembers
are listed (and can be deleted) in Settings → Privacy, and teacher messages open from the bell.

## D45 — Progress shows real performance across all subjects

The Progress page no longer shows the course-concept mastery and confidence-calibration charts;
it is built from the student's real results: every My Learning answer (all subjects), quiz
scores from teachers' folders, and roadmap progress. It shows accuracy, answers, study streak and
quiz average for a chosen period (7, 30, 90 days or all time); accuracy over time as line graphs
(all subjects together, and each subject, per day, or per week for long periods, with a running
average option); answers per day; a subject table with accuracy, a trend sparkline, the change
over the last 7 days, strongest and weakest topics; topics to focus on (with one-click practice);
strongest topics; recent activity; and roadmaps. Days are counted in the browser's time zone.

## D46 — AI Tutor page: a simple chat for any question

The AI Tutor page is a full-screen chat, like a general chat assistant: it welcomes the student
by name, suggests starter questions, streams answers (Markdown with code blocks), keeps each
conversation (History, New chat) in `chat_threads`, and sends the last 12 messages along for
context. It calls the language model directly with a general tutoring prompt instead of the
research tutor pipeline (orchestrator: policy, Socratic moves, course-grounded answers), which
remains in the code and still serves the hidden practice page. Safety stays: messages that
match the distress lexicon are never sent to the model; the student gets the support message
and an escalation reaches their teachers. While the local model is unreachable the chat says
it is offline instead of replying with offline templates. 20 messages a minute per student.

## D47 — Home: animated product tour and a dashboard of real numbers

Home opens with a hero: a greeting, three actions (practise, ask the AI tutor, set a goal) and a
video-like product tour (four scenes: AI tutor, practice feedback, progress, roadmap) with a
progress bar per scene, play/pause and scene buttons. It is built from HTML/CSS animation rather
than a video file, so it stays sharp, small, follows the light/dark theme and pauses for
prefers-reduced-motion (which shows each scene's finished frame). Below it, a dashboard from
the student's real data: accuracy over 14 days, answers this week, streak and roadmap progress;
a 14-day accuracy line graph; "Up next" (an unfinished round, the roadmap's current week,
teachers' quizzes not yet taken, the weakest topic); subject cards; quizzes; recent activity.
New students get a four-step getting-started list instead. Chart colours use a categorical
palette validated for colour-vision deficiency in light and dark (tokens `--cat-1..8`).

