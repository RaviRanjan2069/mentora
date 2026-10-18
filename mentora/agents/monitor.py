from __future__ import annotations

from mentora.agents.base import TutorAgent


class Monitor(TutorAgent):
    """Performance: progress, confidence (calibration), tactics, help-seeking, breaks."""

    name = "Monitor"
