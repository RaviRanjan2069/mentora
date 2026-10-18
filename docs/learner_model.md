# Learner model and policy state

`LearnerTracker` (`mentora/learner_model/tracker.py`) consumes each logged xAPI
statement and keeps everything the state builder needs. It can be rebuilt at any time by
replaying the event log.

## Components

| Component | File | Notes |
|---|---|---|
| Knowledge tracing | `kt/models.py`, `kt/train.py` | DKT (LSTM) and an AKT-style attention model whose interaction embedding adds behaviour features b = (response time, hint use, attempts). AUC is computed on held-out learners. `scripts/train_learner_models.py` trains both. |
| Mastery | `kt/mastery.py` | `mastery_model: count` uses a Beta posterior per concept and needs no training. `dkt` / `akt` use a trained model from `model_dir`. |
| Tactic HMM | `hmm_tactics.py`, `tactics.py` | Events are coded READ / QUIZ / HINT / PLAN / CHAT / REFLECT. Fitted with Baum-Welch (hmmlearn), with H chosen by BIC in 3–6. The online forward filter is our own code, tested against hmmlearn. Before a fit exists, a 1-state model is used. |
| SRL phase | `srl_phase.py` | Rules on session context, corrected by the tagger. |
| SRL tagger | `srl_tagger.py` | 8 indicators, goal SMART and reflection rubrics. `llm` mode, or `trace_only` (keyword rules, no LLM). `auto` picks `llm` only for hosted or local back-ends. See `docs/coding_manual.md`. |
| Calibration | `calibration.py` | c̄_t = (1−η)c̄_{t−1} + η·\|ĉ − y\|, with η = 0.2. Lower is better. |
| Engagement | `engagement.py` | Sessions per week, time on task, idle ratio, logistic dropout risk (placeholder weights in config). |
| Requests | `requests.py` | Message category: answer, hint, explanation, plan, question or none. The text itself never reaches the policy. |

## State vector s_t (28 features with the default H_max = 6)

Every feature is scaled to [0, 1].

| # | Feature | Definition |
|---|---|---|
| 1 | `goal_mastery` | mean mastery over the active goal's concepts (mean mastery if no goal) |
| 2 | `mean_mastery` | mean mastery over all course concepts |
| 3–5 | `phase_forethought/performance/reflection` | one-hot SRL phase |
| 6–11 | `tactic_state_0..5` | normalised forward posterior α_t of the tactic HMM, zero-padded to H_max |
| 12–19 | `srl_<indicator>` | count of each indicator over the last w = 10 learner turns, divided by w |
| 20 | `calibration_error` | c̄_t |
| 21 | `sessions_per_week` | ÷ 7 (`norm_sessions_per_week`) |
| 22 | `time_on_task` | hours in the last 14 days ÷ 10 (`norm_time_on_task_hours`) |
| 23 | `idle_ratio` | idle share of the current session |
| 24 | `dropout_risk` | logistic score |
| 25 | `plan_progress` | ρ_t, completed share of the active plan's steps |
| 26 | `sdl_stage` | Grow stage (1–4) from the learner-initiated share of SRL actions, as (stage−1)/3 |
| 27 | `hint_before_attempt_rate` | hints or answer requests before any attempt ÷ items started |
| 28 | `answer_request_rate` | answer requests ÷ learner messages |

The authoritative list is `feature_names()` in `mentora/learner_model/state.py`.
