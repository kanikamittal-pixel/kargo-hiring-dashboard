from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CRITERION_IDS = ("A", "B", "C", "D", "E", "F")
RED_FLAG_IDS = ("F1", "F2", "F3", "F4")


class Role(BaseModel):
    title: str
    company: str
    start: str
    end: str
    is_product_management_role: bool


class OwnershipField(BaseModel):
    value: bool
    evidence: str


class Ownership(BaseModel):
    end_to_end_ownership: OwnershipField
    no_senior_pm_layer: OwnershipField


class CriterionScore(BaseModel):
    matched_anchor: Literal[1, 3, 5]
    score: int = Field(ge=1, le=5)
    evidence: str
    rationale: str

    @model_validator(mode="after")
    def evidence_required_for_score_2_or_more(self):
        no_evidence = self.evidence.strip().lower() in ("", "none found")
        if self.score >= 2 and no_evidence:
            raise ValueError(
                "score >= 2 requires quoted CV evidence; got no evidence. "
                "Score must be 1 when there is no evidence."
            )
        word_count = len(self.evidence.split())
        if word_count > 25:
            raise ValueError(f"evidence must be 25 words or fewer, got {word_count}")
        return self


class RedFlag(BaseModel):
    id: str
    present: bool
    evidence: str


class CVScoreResult(BaseModel):
    roles: list[Role]
    ownership: Ownership
    pm_criteria: dict[str, CriterionScore]
    spm_criteria: dict[str, CriterionScore]
    red_flags: list[RedFlag]

    @model_validator(mode="after")
    def check_all_criteria_and_flags_present(self):
        for label, criteria in (("pm_criteria", self.pm_criteria), ("spm_criteria", self.spm_criteria)):
            missing = set(CRITERION_IDS) - set(criteria.keys())
            if missing:
                raise ValueError(f"{label} missing criterion ids: {sorted(missing)}")
        got_flag_ids = {f.id for f in self.red_flags}
        missing_flags = set(RED_FLAG_IDS) - got_flag_ids
        if missing_flags:
            raise ValueError(f"red_flags missing ids: {sorted(missing_flags)}")
        return self
