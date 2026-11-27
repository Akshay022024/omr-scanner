"""Pydantic models: template geometry, scan results, answer keys and grades."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldGroup = Literal["roll_no", "paper_set", "answers"]
FieldState = Literal["single", "blank", "multiple", "ambiguous"]
ScanStatus = Literal["ok", "needs_review", "failed"]
RegistrationMethod = Literal["ecc", "orb", "anchors", "identity"]
QuestionOutcome = Literal["correct", "wrong", "blank", "multiple", "no_key"]


# --------------------------------------------------------------------------- template


class TemplateBubble(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str = Field(min_length=1, max_length=4)
    x: float
    y: float
    r: float = Field(gt=0)


class TemplateField(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    group: FieldGroup
    type: Literal["digit", "choice"]
    question: int | None = None
    bubbles: list[TemplateBubble] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> TemplateField:
        values = [b.value for b in self.bubbles]
        if len(set(values)) != len(values):
            raise ValueError(f"field {self.id}: duplicate bubble values")
        if self.group == "answers" and self.question is None:
            raise ValueError(f"field {self.id}: answers field needs a question number")
        return self


class PageSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(gt=0)
    paper: str = "letter"


class TemplateSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str
    version: int = 1
    page: PageSpec
    print_color: Literal["magenta", "orange"] = "magenta"
    reference_image: str
    # Panel boxes (x, y, w, h) used to refine and verify registration, and whether their outlines
    # are printed in the print colour ("print") or in black ("dark").
    anchors: dict[str, tuple[int, int, int, int]] = Field(default_factory=dict)
    anchor_source: Literal["print", "dark"] = "print"
    num_questions: int = Field(gt=0)
    options: list[str] = Field(min_length=2)
    fields: list[TemplateField] = Field(min_length=1)
    # Per-template EngineConfig overrides (e.g. ink sensitivity for pencil-filled forms), applied on
    # top of the caller's config. Keys must be EngineConfig field names.
    engine_overrides: dict[str, float | int | bool] = Field(default_factory=dict)
    source: str | None = None  # provenance / attribution of the reference image

    @model_validator(mode="after")
    def _check(self) -> TemplateSpec:
        ids = [f.id for f in self.fields]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate field ids")
        questions = sorted(f.question for f in self.fields if f.group == "answers" and f.question)
        if questions != list(range(1, self.num_questions + 1)):
            raise ValueError("answers fields must cover questions 1..num_questions exactly once")
        w, h = self.page.width_px, self.page.height_px
        for f in self.fields:
            for b in f.bubbles:
                if not (b.r <= b.x <= w - b.r and b.r <= b.y <= h - b.r):
                    raise ValueError(f"field {f.id}: bubble {b.value} outside the page")
            if f.group == "answers" and any(b.value not in self.options for b in f.bubbles):
                raise ValueError(f"field {f.id}: bubble value not in options")
        for name, (x, y, bw, bh) in self.anchors.items():
            if bw <= 0 or bh <= 0 or x < 0 or y < 0 or x + bw > w or y + bh > h:
                raise ValueError(f"anchor {name} outside the page")
        if sum(1 for f in self.fields if f.group == "paper_set") > 1:
            raise ValueError("at most one paper_set field is allowed")
        return self


# --------------------------------------------------------------------------- scan result


class FieldResult(BaseModel):
    id: str
    group: FieldGroup
    question: int | None = None
    state: FieldState
    value: str
    confidence: float
    scores: dict[str, float]


class RegistrationInfo(BaseModel):
    method: RegistrationMethod
    quality: float  # IoU of the warped print-colour mask vs the template mask
    homography: list[list[float]] | None = None  # template px -> original image px
    layout_score: float | None = None  # coarse correlation with the template layout
    geometry_ok: bool | None = None  # anchor-box edges re-found where expected after warping
    anchor_coverage: float | None = None  # min over directions of the edge segments found
    anchor_residual_px: float | None = None  # robust RMS edge offset, template px
    print_lock: float | None = None  # dark-print correlation at zero offset
    print_lock_margin: float | None = None  # ... minus the best one-bubble-pitch-shifted correlation


class ScanResult(BaseModel):
    template_id: str
    status: ScanStatus
    error: str | None = None
    roll_no: str = ""
    paper_set: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    fields: list[FieldResult] = Field(default_factory=list)
    review_flags: list[str] = Field(default_factory=list)
    registration: RegistrationInfo | None = None
    threshold: float | None = None
    aligned_size: tuple[int, int]
    timings_ms: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- grading


class AnswerKey(BaseModel):
    id: str
    name: str
    template_id: str
    keys: dict[str, dict[str, str]]
    marks_correct: float = 1.0
    marks_wrong: float = 0.0
    marks_blank: float = 0.0

    @field_validator("keys")
    @classmethod
    def _normalise(cls, v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return {
            s.strip().upper(): {q.strip(): a.strip().upper() for q, a in answers.items() if a.strip()}
            for s, answers in v.items()
        }


class GradeResult(BaseModel):
    answer_key_id: str
    paper_set_used: str | None
    score: float
    max_score: float
    correct: int
    wrong: int
    blank: int
    multiple: int
    per_question: dict[str, QuestionOutcome]
