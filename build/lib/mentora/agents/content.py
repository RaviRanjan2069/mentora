from __future__ import annotations

from mentora.agents.base import TutorAgent


class ContentTutor(TutorAgent):
    """Performance: hints, worked examples, explanations, practice, pointers to material.
    Grounded in retrieved course passages. (The base task text names the target concept.)"""

    name = "ContentTutor"
