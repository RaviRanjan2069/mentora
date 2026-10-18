"""Knowledge-tracing models.

* ``DKT``: LSTM over (concept, correct) one-hots; outputs P(correct) for every concept at
  the next step (Piech et al., 2015).
* ``AKTStyle``: attention KT in the spirit of AKT (Ghosh et al., 2020): the query is the
  next question, keys/values are past interactions whose embedding adds behaviour
  features b = (response time, hint use, attempts), and attention decays monotonically
  with distance (a learned exponential decay). Simplified: one attention layer, concept
  (not item) embeddings, no Rasch difficulty term.

Both expose ``predict_next(batch) -> logits[B, T]`` where position t is the prediction
for interaction t+1 given interactions 0..t, and ``mastery(seq) -> [C]`` probabilities.
"""

from __future__ import annotations

from typing import Literal

import torch
from torch import nn

from mentora.learner_model.kt.data import Batch, Interaction, to_batch

KTKind = Literal["dkt", "akt"]


class DKT(nn.Module):
    def __init__(self, n_concepts: int, hidden: int) -> None:
        super().__init__()
        self.n_concepts = n_concepts
        self.emb = nn.Embedding(2 * n_concepts, hidden)
        self.lstm = nn.LSTM(hidden, hidden, batch_first=True)
        self.out = nn.Linear(hidden, n_concepts)

    def all_concept_logits(self, b: Batch) -> torch.Tensor:
        """[B, T, C]: after step t, logits for every concept at step t+1."""
        h, _ = self.lstm(self.emb(b.concepts + self.n_concepts * b.correct))
        out: torch.Tensor = self.out(h)
        return out

    def predict_next(self, b: Batch) -> torch.Tensor:
        logits = self.all_concept_logits(b)[:, :-1]  # predictions for steps 1..T-1
        nxt = b.concepts[:, 1:].unsqueeze(-1)
        return logits.gather(-1, nxt).squeeze(-1)

    @torch.no_grad()
    def mastery(self, seq: list[Interaction]) -> torch.Tensor:
        if not seq:
            return torch.sigmoid(self.out.bias)
        return torch.sigmoid(self.all_concept_logits(to_batch([seq]))[0, -1])


class AKTStyle(nn.Module):
    def __init__(self, n_concepts: int, hidden: int, heads: int) -> None:
        super().__init__()
        self.n_concepts = n_concepts
        self.heads = heads
        self.q_emb = nn.Embedding(n_concepts, hidden)
        self.qa_emb = nn.Embedding(2 * n_concepts, hidden)
        self.b_proj = nn.Linear(3, hidden)
        self.start = nn.Parameter(torch.zeros(1, 1, hidden))
        self.decay = nn.Parameter(torch.zeros(1))  # softplus(decay) = forgetting rate
        self.attn = nn.MultiheadAttention(hidden, heads, batch_first=True)
        self.head = nn.Sequential(nn.Linear(2 * hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def _keys(self, b: Batch) -> torch.Tensor:
        """Key j = interaction j-1 (key 0 is a learned 'no history' token)."""
        inter = self.qa_emb(b.concepts + self.n_concepts * b.correct) + self.b_proj(b.behaviour)
        start = self.start.expand(inter.size(0), 1, -1)
        return torch.cat([start, inter], dim=1)  # [B, T+1, H]

    def _attend(
        self, queries: torch.Tensor, keys: torch.Tensor, mask: torch.Tensor
    ) -> torch.Tensor:
        out, _ = self.attn(queries, keys, keys, attn_mask=mask.repeat_interleave(self.heads, 0))
        logits: torch.Tensor = self.head(torch.cat([out, queries], dim=-1)).squeeze(-1)
        return logits

    def _decay_mask(self, n_q: int, n_k: int, positions: torch.Tensor) -> torch.Tensor:
        """Additive mask: query at history length p sees keys 0..p, decayed by distance."""
        k = torch.arange(n_k).view(1, 1, n_k)
        p = positions.view(-1, n_q, 1)
        dist = (p - k).float()
        mask = -nn.functional.softplus(self.decay) * dist.clamp(min=0)
        return mask.masked_fill(k > p, float("-inf"))

    def logits_all_positions(self, b: Batch) -> torch.Tensor:
        """[B, T]: logit for interaction t given interactions 0..t-1."""
        bsz, t = b.concepts.shape
        keys = self._keys(b)[:, :t]  # keys 0..t-1 cover interactions -1..t-2
        positions = torch.arange(t).expand(bsz, t)
        return self._attend(self.q_emb(b.concepts), keys, self._decay_mask(t, t, positions))

    def predict_next(self, b: Batch) -> torch.Tensor:
        return self.logits_all_positions(b)[:, 1:]  # aligned with DKT: steps 1..T-1

    @torch.no_grad()
    def mastery(self, seq: list[Interaction]) -> torch.Tensor:
        c = self.n_concepts
        keys = self._keys(to_batch([seq])) if seq else self.start  # [1, n+1, H]
        queries = self.q_emb(torch.arange(c)).unsqueeze(0)
        n_k = keys.size(1)
        positions = torch.full((1, c), n_k - 1)
        mask = self._decay_mask(c, n_k, positions)
        return torch.sigmoid(self._attend(queries, keys, mask)[0])


def build_model(kind: KTKind, n_concepts: int, hidden: int, heads: int) -> DKT | AKTStyle:
    return DKT(n_concepts, hidden) if kind == "dkt" else AKTStyle(n_concepts, hidden, heads)
