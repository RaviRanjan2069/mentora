"""Confidence calibration: c_t = (1 - eta) * c_{t-1} + eta * |confidence - correct|.

Lower is better calibrated (0 = confidence always matched the outcome)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CalibrationTracker:
    eta: float
    value: float
    points: list[tuple[float, bool]] = field(default_factory=list)  # (confidence, correct)

    def update(self, confidence: float, correct: bool) -> float:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        error = abs(confidence - (1.0 if correct else 0.0))
        self.value = (1 - self.eta) * self.value + self.eta * error
        self.points.append((confidence, correct))
        return self.value

    def bins(self, n_bins: int = 5) -> list[dict[str, float]]:
        """Confidence-vs-accuracy bins for the learner dashboard chart."""
        out = []
        for b in range(n_bins):
            lo, hi = b / n_bins, (b + 1) / n_bins
            inside = [
                (c, y) for c, y in self.points if lo <= c < hi or (b == n_bins - 1 and c == 1.0)
            ]
            if inside:
                out.append(
                    {
                        "confidence": sum(c for c, _ in inside) / len(inside),
                        "accuracy": sum(1.0 for _, y in inside if y) / len(inside),
                        "n": float(len(inside)),
                    }
                )
        return out
