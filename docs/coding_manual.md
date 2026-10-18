# SRL coding manual

This manual is for human coders who label learner messages, so that the automatic tagger
(`mentora/learner_model/srl_tagger.py`) can be checked against human judgement. The
tagger's LLM prompt (`mentora/prompts/learner_model/srl_tagger/v1.md`) uses the same
definitions.

## Unit of coding

One learner chat message. Code only what the message says, not what the learner might
mean. A message can have several indicators, or none. The previous tutor turn is
context: it can resolve a pronoun but must not add an indicator the message doesn't
express.

## The eight indicators

| Indicator | Code 1 when the learner… | Examples (1) | Not this (0) |
|---|---|---|---|
| `goal_stated` | states something they want to achieve: a target, outcome or aim | "My goal is to finish the loop exercises tonight." "I want to understand slicing." | "Loops are hard." (no aim) |
| `plan_stated` | states steps, an order, or when they will do something | "First I'll re-read the slides, then try the quiz." | "I want to finish." (goal only) |
| `strategy_named` | names a specific learning strategy | "I'll practise more examples." "Let me trace the code by hand." | "I'll study." (too general) |
| `monitoring_statement` | comments on their own current understanding, progress or difficulty | "I think I get it now." "I'm lost on range." | "What is range?" (question only) |
| `help_request` | asks for help, a hint, an explanation or an answer | "Can you give me a hint?" "Just tell me the answer." | "I'll ask my friend later." (plan, not a request) |
| `self_evaluation` | judges how well they did on a completed task or result | "I did badly on that quiz." "I got 4 out of 5." | "This is hard." (monitoring, task not done) |
| `attribution` | gives a cause for a result: effort, strategy, understanding or time | "…because I didn't practise slicing." | "I failed." (no cause) |
| `adaptation_intent` | says what they will do differently next time | "Next time I'll do the examples first." | "I'll try again." (no change named) |

## Rubrics

**Goal SMART quality (0–1).** 0.2 for each of: specific (names a topic or task),
measurable (amount or check), achievable (fits a session), relevant (course material),
time-bound (by when or for how long).

**Reflection quality (0–1).** 0.25 for each of: description (what happened), evaluation
(went well or badly), attribution (why), adaptation (a concrete change).

## Procedure

1. Two coders independently code the same random sample (at least 200 messages from the
   pilot, pseudonymised).
2. Report Cohen's κ per indicator. Discuss disagreements and refine this manual (add
   examples, keep the definitions).
3. Compare the tagger with the agreed labels: κ and F1 per indicator. Report the tagger's
   agreement with humans before using its outputs in the reward.

Both `llm` and `trace_only` tagger modes should be evaluated. `trace_only` uses keyword
rules and is the fallback when no LLM is available.
