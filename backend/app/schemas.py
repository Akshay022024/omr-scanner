"""API request/response models. Engine models (ScanResult, GradeResult, ...) are reused as-is."""

from __future__ import annotations

from pydantic import BaseModel, Field

from omr_engine import GradeResult, ScanResult


class HealthResponse(BaseModel):
    status: str
    engine_version: str
    templates: int


class TemplateSummary(BaseModel):
    id: str
    name: str
    version: int
    num_questions: int
    options: list[str]
    paper_sets: list[str]


class AnswerKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_id: str = Field(min_length=1, max_length=64)
    keys: dict[str, dict[str, str]]
    marks_correct: float = Field(default=1.0, ge=-1000, le=1000)
    marks_wrong: float = Field(default=0.0, ge=-1000, le=1000)
    marks_blank: float = Field(default=0.0, ge=-1000, le=1000)


class AnswerKeyOut(BaseModel):
    id: str
    name: str
    template_id: str
    keys: dict[str, dict[str, str]]
    marks_correct: float
    marks_wrong: float
    marks_blank: float
    created_at: str
    updated_at: str


class ScanRecord(BaseModel):
    id: str
    batch_id: str
    filename: str
    page: int
    created_at: str
    answer_key_id: str | None
    result: ScanResult
    grade: GradeResult | None
    corrected: bool


class ScanUploadResponse(BaseModel):
    batch_id: str
    scans: list[ScanRecord]


class ScanCorrection(BaseModel):
    """Only the fields that are present are applied; ``paper_set: null`` clears the set."""

    roll_no: str | None = Field(default=None, max_length=32)
    paper_set: str | None = Field(default=None, max_length=4)
    answers: dict[str, str] | None = None


class RegradeRequest(BaseModel):
    answer_key_id: str


class BatchSummary(BaseModel):
    id: str
    template_id: str
    answer_key_id: str | None
    created_at: str
    scan_count: int
    status_counts: dict[str, int]
    corrected_count: int
    mean_score: float | None


class BatchDetail(BatchSummary):
    scans: list[ScanRecord]
