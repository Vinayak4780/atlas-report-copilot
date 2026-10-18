"""Typed request/response models for the public API."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ClientId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^C-\d{2,4}$")]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]
HistoryItem = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: ClientId = Field(examples=["C-01"])
    question: Question = Field(examples=["What was the global smart water meter market size in 2024?"])
    history: list[HistoryItem] = Field(default_factory=list, max_length=6,
                                       description="Earlier questions in this chat, oldest first")
    session_id: str | None = Field(default=None, max_length=64)


class Citation(BaseModel):
    id: str
    kind: Literal["metric", "excerpt", "derived", "sql"]
    report_id: str | None
    title: str
    publisher: str
    page: int | None
    snippet: str


class ConflictValue(BaseModel):
    report_id: str
    publisher: str
    value: float
    display: str
    period: str
    scope_note: str
    page: int
    citation_id: str


class Conflict(BaseModel):
    market: str
    metric: str
    region: str
    period: str
    kind: str
    label: str
    values: list[ConflictValue]
    note: str
    resolution: str


class DerivedInput(BaseModel):
    name: str
    value: str
    report_id: str
    page: int
    citation_id: str


class DerivedAlternative(BaseModel):
    label: str
    value: float
    display: str
    formula: str


class DerivedValue(BaseModel):
    id: str
    kind: Literal["derived_estimate"] = "derived_estimate"
    label: str
    basis_report_id: str
    value: float
    unit: str
    display: str
    formula: str
    inputs: list[DerivedInput]
    assumptions: list[str]
    base_year_ambiguity: str | None
    alternatives: list[DerivedAlternative]
    forecast_window: str
    extrapolated_years: int


class LockedReport(BaseModel):
    report_id: str
    title: str
    publisher: str
    published: str
    access: str
    upgrade_hint: str


class TokenStats(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int


class ChatResponse(BaseModel):
    request_id: str
    client_id: str
    route: str
    answer: str
    citations: list[Citation]
    confidence: float = Field(ge=0, le=1)
    confidence_reasons: list[str]
    conflicts: list[Conflict]
    derived_values: list[DerivedValue]
    escalated: bool
    escalation_id: int | None
    locked_reports: list[LockedReport]
    sql_query: str | None
    injection_detected: bool
    cached: bool
    latency_ms: int
    tokens: TokenStats
    cost_usd: float


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reset: bool = Field(default=True, description="Rebuild the collection from data/reports")


class IngestResponse(BaseModel):
    reports: list[str]
    chunks: int
    injection_flags: list[dict]


class Escalation(BaseModel):
    id: int
    request_id: str | None
    client_id: str
    question: str
    reason: str
    confidence: float | None
    source: str
    status: str
    created_at: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mysql: bool
    qdrant: bool
    vector_points: int
    llm_configured: bool
    cache_entries: int
