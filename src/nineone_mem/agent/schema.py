"""The shape of the RCA answer (harness part D).

Two parts, on purpose:
- RcaDecision: what the MODEL fills in (a choice and the names of its sources)
- the stored verdict: the decision PLUS fields the CODE adds (confidence, gate, abstained)

So the model can never set a confidence or a gate.
"""
from typing import Literal

from pydantic import BaseModel, Field

CATEGORIES = ("config_change", "fault", "coverage", "capacity", "interference",
              "neighbour_impact", "external_event")

Category = Literal["config_change", "fault", "coverage", "capacity", "interference",
                   "neighbour_impact", "external_event", "abstain"]


class RcaDecision(BaseModel):
    """Arguments of the emit_verdict tool. Every field name below is a box the model fills in."""

    category: Category = Field(description="One allowed category, or 'abstain' if you cannot decide.")
    considered: list[str] = Field(default_factory=list, description="Categories the findings support.")
    evidence_for: list[str] = Field(default_factory=list, description="Finding ids that support your choice.")
    evidence_against: list[str] = Field(default_factory=list, description="Finding ids that argue against it.")
    memories_used: list[str] = Field(default_factory=list, description="Ids of memories you relied on.")
    tied_with: list[str] = Field(default_factory=list, description="If abstaining because of a tie: the tied categories.")
    missing: list[str] = Field(default_factory=list, description="If abstaining: what was missing.")
    reason: str = Field(description="At most 60 words. Ids, not retold evidence.")
