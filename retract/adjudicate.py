"""Adjudication: deciding whether a contested claim is a rephrasing or a change.

The database's guarantee is that exactly one agent holds a claim key at a time
and that the verdict is recorded atomically. It is NOT that the verdict is
right. Something has to actually judge, and we measured that embedding distance
cannot: a negation can sit closer than a paraphrase (0.296 vs 0.323).

So a model judges. Two backends behind one interface, same reason as embeddings:
the whole pipeline must run for someone who has no AWS account.

    bedrock    Claude via the Bedrock Converse API. The real adjudicator.
    heuristic  Negation- and antonym-marker matching. A STAND-IN, not a model.

The heuristic is deliberately crude and says so. It exists so the pipeline runs
offline; it must never be presented as the product's reasoning, and `is_model`
is False on it precisely so the demo and the write-up cannot claim otherwise.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Verdict:
    resolution: str        # 'duplicate' | 'superseded' | 'rejected'
    confidence: float
    reasoning: str
    by: str


PROMPT = """You adjudicate a contested fact in a shared agent memory.

Two agents asserted something about the SAME subject and predicate.

SUBJECT:   {subject}
PREDICATE: {predicate}

INCUMBENT (already believed): {incumbent}
CHALLENGER (newly asserted):  {challenger}

Decide exactly one:
- "duplicate"  - same fact, different wording. Nothing changes.
- "superseded" - a genuine CHANGE or CORRECTION. The challenger replaces the incumbent.
- "rejected"   - the challenger contradicts the incumbent and is less credible, \
or is about something the predicate does not cover. The incumbent stands.

A negation ("failed" vs "verified"), a different amount, or a change of tense \
("lives in" vs "used to live in") is NEVER a duplicate.

Reply with JSON only: {{"resolution": "...", "confidence": 0.0-1.0, "reasoning": "one sentence"}}"""


class Adjudicator(ABC):
    name: str
    is_model: bool

    @abstractmethod
    def judge(self, subject: str, predicate: str, incumbent: str, challenger: str) -> Verdict: ...


class HeuristicAdjudicator(Adjudicator):
    """STAND-IN. Marker matching, not reasoning. Never claim otherwise."""

    name = "heuristic (stand-in, not a model)"
    is_model = False

    NEG = re.compile(r"\b(not|no longer|failed|fail|denied|declined|rejected|invalid|"
                     r"revoked|cancelled|canceled|unverified|refused)\b", re.I)
    TENSE = re.compile(r"\b(used to|formerly|previously|was|were|had been)\b", re.I)
    MONEY = re.compile(r"[$€£]\s?([\d,]+(?:\.\d+)?)")

    def judge(self, subject, predicate, incumbent, challenger) -> Verdict:
        a_neg, b_neg = bool(self.NEG.search(incumbent)), bool(self.NEG.search(challenger))
        if a_neg != b_neg:
            return Verdict("superseded", 0.6, "one side is negated and the other is not", self.name)
        if bool(self.TENSE.search(challenger)) != bool(self.TENSE.search(incumbent)):
            return Verdict("superseded", 0.55, "tense differs, so the claim changed", self.name)
        a_amt = {m.replace(",", "") for m in self.MONEY.findall(incumbent)}
        b_amt = {m.replace(",", "") for m in self.MONEY.findall(challenger)}
        if a_amt and b_amt and a_amt != b_amt:
            return Verdict("superseded", 0.7, f"amounts differ: {a_amt} vs {b_amt}", self.name)
        return Verdict("duplicate", 0.4, "no negation, tense shift or amount change detected", self.name)


class BedrockAdjudicator(Adjudicator):
    name = "bedrock:claude"
    is_model = True

    # The bare model id is NOT invocable on demand -- Bedrock returns
    # "Invocation of model ID ... with on-demand throughput isn't supported.
    # Retry with an inference profile." The "us." prefix IS that profile.

    def __init__(self, model_id: str | None = None, region: str | None = None):
        import boto3

        self.model_id = model_id or os.environ.get(
            "RETRACT_ADJUDICATOR_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        self._client = boto3.client(
            "bedrock-runtime", region_name=region or os.environ.get("AWS_REGION", "us-east-1")
        )

    def judge(self, subject, predicate, incumbent, challenger) -> Verdict:
        prompt = PROMPT.format(subject=subject, predicate=predicate,
                               incumbent=incumbent, challenger=challenger)
        resp = self._client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(f"adjudicator returned no JSON: {text[:200]}")
        data = json.loads(m.group())
        if data["resolution"] not in ("duplicate", "superseded", "rejected"):
            raise ValueError(f"invalid resolution: {data['resolution']}")
        return Verdict(data["resolution"], float(data.get("confidence", 0.0)),
                       data.get("reasoning", ""), f"{self.name}:{self.model_id}")


def get_adjudicator(backend: str | None = None) -> Adjudicator:
    choice = backend or os.environ.get("RETRACT_ADJUDICATOR", "auto")
    if choice == "heuristic":
        return HeuristicAdjudicator()
    if choice == "bedrock":
        return BedrockAdjudicator()
    if choice != "auto":
        raise ValueError(f"unknown adjudicator backend: {choice!r}")
    try:
        a = BedrockAdjudicator()
        a.judge("customer:1", "test", "the sky is blue", "the sky is blue")
        return a
    except Exception as exc:  # noqa: BLE001
        print(f"[adjudicate] bedrock unavailable ({type(exc).__name__}), using heuristic stand-in")
        return HeuristicAdjudicator()
