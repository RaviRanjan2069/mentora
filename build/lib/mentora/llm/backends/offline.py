"""Offline demo back-end: template replies for each move, no model and no network.

It lets the full system (policy, safety filter, grounding, UI) run without an API key.
Replies are fixed templates filled with the course passage and concept from the prompt,
so they are clearly not AI-generated; the UI shows a banner while it is active.
"""

from __future__ import annotations

import json
import re

from mentora.llm.backends.fake import minimal_instance
from mentora.llm.types import Completion, LLMRequest
from mentora.rag.text import content_words, split_sentences

_PASSAGE_RE = re.compile(r"^\[([A-Za-z0-9][\w\-]*)\] (.+)$", re.MULTILINE)
_CONCEPT_RE = re.compile(r"^(?:Concept|Target concept): (.+)$", re.MULTILINE)
_GOAL_RE = re.compile(r"^- Goal: (.+)$", re.MULTILINE)
_MESSAGE_RE = re.compile(r"<learner_message>\s*(.*?)\s*</learner_message>", re.DOTALL)
_EXAMPLE_RE = re.compile(r"\bexamples?\b|\bshow me\b", re.IGNORECASE)
_EXPLAIN_RE = re.compile(r"\bexplain|\bagain\b|\bconfus|\bdon'?t (get|understand)", re.IGNORECASE)
_TASK_RE = re.compile(
    r"^Question: (.+?)(?=^Target concept:|^This is a GRADED|^The learner's latest|\Z)",
    re.DOTALL | re.MULTILINE,
)

# move -> (Socratic template, Directive template)
TEMPLATES: dict[str, tuple[str, str]] = {
    "elicit_smart_goal": (
        "What would you like to get done in this session? Try to make it specific: which "
        "topic, how much, and by when?",
        "",
    ),
    "decompose_plan": (
        "Which two or three small steps would get you to your goal, and which comes first?",
        "Let's split your goal into small steps: first review the notes on {concept}, then "
        "try one practice question, then check your answer. Does that order work for you?",
    ),
    "estimate_time": (
        "How long do you think each step will take, and does that fit the time you have?",
        "Give each step a time estimate in minutes, then add them up. Does the total fit today?",
    ),
    "set_schedule": (
        "When will you do each step: today, or later this week?",
        "Pick a time for each step and write it next to the step. When will you start?",
    ),
    "recall_past_goals": (
        "Last time your goal was: {goal}. How did that go, and what would you like to aim "
        "for today?",
        "Last time your goal was: {goal}. Decide whether to continue it or set a new one. "
        "Which will it be?",
    ),
    "confidence_check": (
        "Before you answer: how confident are you that you'll get this right, from 0 to "
        "100 percent?",
        "",
    ),
    "progress_nudge": (
        "You're partway through your plan. What's your next step?",
        "You're partway through your plan. Move on to your next step now. Which one is it?",
    ),
    "tactic_switch": (
        "You've been using the same approach for a while. Would testing yourself with a "
        "practice question help more right now?",
        "Try a different tactic for the next ten minutes: answer a practice question "
        "instead of re-reading. Which question will you try?",
    ),
    "help_seeking_prompt": (
        "What have you tried so far, and where exactly did you get stuck? That tells us "
        "what kind of help you need.",
        "Write down what you tried and where you got stuck, then ask for a hint, a "
        "classmate, or your teacher. Which will you ask?",
    ),
    "break_suggestion": (
        "You've been working for a while. Would a five-minute break help you focus?",
        "Take a five-minute break, then restart at your current step. Ready to pause?",
    ),
    "socratic_reflection": (
        "How did that go? What worked well, and what was harder than you expected?",
        "",
    ),
    "attribution_question": (
        "What do you think made the difference in that result: your strategy, your "
        "understanding of the idea, or the time you spent?",
        "",
    ),
    "compare_outcome_goal": (
        "Compare where you ended up with your goal ({goal}). How close did you get, and why?",
        "Your goal was: {goal}. Check off what you finished. What is left?",
    ),
    "record_lesson": (
        "What is one thing from today you want to remember for next time?",
        "Write one sentence: next time I will ... . What will you write?",
    ),
    # Factual sentences are exact sentences from the notes, each with its citation, so the
    # grounding check can confirm them; lead-ins open like instructions, not claims.
    "graded_hint": (
        "Look again at this part of the course notes. {sentence} [{pid}] How does that "
        "apply to your question?",
        "Read this part of the course notes again. {sentence} [{pid}] Compare it with your "
        "answer: what do you notice?",
    ),
    "worked_example": (
        "Look at how the notes put it. {sentence} [{pid}] How would you apply the same "
        "steps to your question?",
        "Study this idea from the notes. {sentence} [{pid}] Now use the same method on your "
        "question. What do you get?",
    ),
    "concept_explanation": (
        "Read how the course notes explain it. {sentences} Which part is new to you?",
        "Read what the course notes say. {sentences} Does that match what you expected?",
    ),
    "practice_item": (
        "Try this practice question on {concept}: in your own words, what does it do and "
        "when would you use it?",
        "Practice question on {concept}: write one small example and predict its output. "
        "What is your prediction?",
    ),
    "textbook_link": (
        "Look at this part of the course notes [{pid}]. What do you expect to find there?",
        "Read this part of the course notes [{pid}], then come back with one question about "
        "it. What will you look for?",
    ),
    "suggest_partner": (
        "Would it help to work through this with a classmate and explain it to each other?",
        "Find a classmate and explain this idea to each other. Who could you ask?",
    ),
    "suggest_thread": (
        "Could you ask about {concept} in the course forum? What exactly would you ask?",
        "Post a short question about {concept} in the course forum. What will you ask?",
    ),
    "share_peer_strategy": (
        "Many students find it useful to trace small examples by hand. Would that work for "
        "{concept}?",
        "A strategy many students use: trace a small example by hand, line by line. Try it "
        "on {concept}. What happens?",
    ),
}


NO_GOAL = {
    "recall_past_goals": "What did you aim for in your last session, and how did it go? What "
    "would you like to aim for today?",
    "compare_outcome_goal": "What did you set out to do in this session, and how close did you "
    "get?",
}


def _first_sentence(text: str) -> str:
    sentence = (split_sentences(text) or [text.strip()])[0]
    return sentence if sentence.endswith((".", "!", "?")) else sentence + "."


def _stem(word: str) -> str:
    """Crude plural folding (strings -> string, classes -> class) for topic matching."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _relevant(
    passages: list[tuple[str, str]],
    query: str,
    k: int,
    prefer_code: bool = False,
    topic: str = "",
) -> tuple[str, list[str]]:
    """The passage and its ``k`` sentences that share the most content words with the query
    (the learner's message and the current question). Words of the topic name count triple
    and earlier passages (retrieval puts notes on the current topic first) get a head start,
    so code words such as print or None do not pull in another topic's notes."""
    wanted = {_stem(w) for w in content_words(query)}
    topic_words = {_stem(w) for w in content_words(topic)}
    best: tuple[float, str, list[str]] = (-1.0, "", [])
    for rank, (pid, text) in enumerate(passages):
        sentences = [s if s.endswith((".", "!", "?")) else s + "." for s in split_sentences(text)]
        if not sentences:
            continue

        def score(sentence: str) -> float:
            found = {_stem(w) for w in content_words(sentence)}
            bonus = 0.5 if prefer_code and "`" in sentence else 0.0
            return len(wanted & found) + 3 * len(topic_words & found) + bonus

        ranked = sorted(range(len(sentences)), key=lambda i: (-score(sentences[i]), i))[:k]
        on_topic = 3 * len(topic_words & {_stem(w) for w in content_words(text)})
        head_start = 2.0 * max(0, 2 - rank)  # first passage +4, second +2
        total = sum(score(sentences[i]) for i in ranked) + on_topic + head_start
        if total > best[0]:
            best = (total, pid, [sentences[i] for i in sorted(ranked)])
    return best[1], best[2]


class OfflineLLM:
    name = "offline"
    model = "offline-templates"

    def complete(self, request: LLMRequest) -> Completion:
        text = self._reply(request)
        prompt = request.system + " ".join(m.content for m in request.messages)
        return Completion(text, self.model, len(prompt.split()), len(text.split()))

    def _reply(self, request: LLMRequest) -> str:
        if request.json_schema is not None:
            return json.dumps(minimal_instance(request.json_schema, request.json_schema))
        user = request.messages[-1].content if request.messages else ""
        passages = _PASSAGE_RE.findall(user)
        pid, ptext = passages[0] if passages else ("", "")
        if request.prompt_id.startswith("rag/answer"):
            if not passages:
                return "I am not sure about that; you could ask your teacher."
            answer = (
                ptext.split(" A: ", 1)[1] if ptext.startswith("Q:") and " A: " in ptext else ptext
            )
            return f"{_first_sentence(answer)} [{pid}]"
        if not request.prompt_id.startswith("agents/turn:"):
            return "Okay."
        action = request.prompt_id.split(":", 1)[1]
        _agent, move, style = action.split(".")
        socratic, directive = TEMPLATES.get(move, ("What do you think?", ""))
        template = directive if style == "Directive" and directive else socratic
        if "{pid}" in template and not passages:
            template = "What part of this is unclear to you right now?"
        concept = (_CONCEPT_RE.search(user) or [None, "this topic"])[1]
        goal_match = _GOAL_RE.search(user)
        if goal_match is None and "{goal}" in template:
            template = NO_GOAL.get(move, "What would you like to aim for today?")
        goal = goal_match.group(1) if goal_match else ""
        sentence, sentences = (_first_sentence(ptext) if ptext else ""), ""
        quote = f"{sentence} [{pid}]" if sentence else ""
        if passages:
            message = m.group(1) if (m := _MESSAGE_RE.search(user)) else ""
            task = t.group(1) if (t := _TASK_RE.search(user)) else ""
            query = " ".join(str(x) for x in (message, task) if x and x != "(no message)")
            topic = str(concept) if concept != "this topic" else ""
            # React to what was asked: an example request prefers a code sentence, an
            # "explain again" request quotes two sentences instead of one.
            wants_example = bool(_EXAMPLE_RE.search(message))
            wants_more = bool(_EXPLAIN_RE.search(message))
            pid, chosen = _relevant(
                passages,
                query,
                2 if wants_more else 1,
                prefer_code=move == "worked_example" or wants_example,
                topic=topic,
            )
            if chosen:
                sentence = chosen[0]
                quote = " ".join(f"{s} [{pid}]" for s in chosen)
            best_pid, two = _relevant(passages, query, 2, topic=topic)
            sentences = " ".join(f"{s} [{best_pid}]" for s in two)
        return template.replace("{sentence} [{pid}]", "{quote}").format(
            pid=pid,
            quote=quote,
            sentence=sentence,
            sentences=sentences,
            concept=concept,
            goal=goal,
        )
