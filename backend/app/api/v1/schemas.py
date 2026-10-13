"""Request and response models. Inputs forbid unknown fields and bound every length."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("control characters are not allowed")
    return value.strip()


Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CleanText(StrictModel):
    """Base for models whose string fields must be free of control characters."""

    @field_validator("*", mode="before")
    @classmethod
    def _no_control_chars(cls, value: Any) -> Any:
        return _clean(value) if isinstance(value, str) else value


# ---- auth ---------------------------------------------------------------------


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=12)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    totp_enabled: bool
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class AcceptInviteRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


class ChangePasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpCodeRequest(StrictModel):
    code: str = Field(min_length=6, max_length=12)


class PasswordRequest(StrictModel):
    password: str = Field(min_length=1, max_length=256)


# ---- users --------------------------------------------------------------------

RoleName = Literal["admin", "attorney", "analyst", "viewer"]


class InviteRequest(CleanText):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: RoleName


class InviteResponse(BaseModel):
    user: UserOut
    invite_token: str
    expires_at: datetime


class UserUpdate(CleanText):
    role: RoleName | None = None
    is_active: bool | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


class ResetResponse(BaseModel):
    reset_token: str
    expires_at: datetime


# ---- cases --------------------------------------------------------------------

LlmMode = Literal["auto", "groq", "gemini", "local_only"]


class CaseCreate(CleanText):
    title: str = Field(min_length=1, max_length=300)
    priority_date: date | None = None
    jurisdiction: str = Field(default="US", min_length=2, max_length=8)
    llm_mode: LlmMode = "auto"
    confidential: bool = True
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class CaseUpdate(CleanText):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    priority_date: date | None = None
    llm_mode: LlmMode | None = None
    confidential: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class CasePermissions(BaseModel):
    edit: bool
    delete: bool
    share: bool
    review: bool


class CaseOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    stage: str | None
    risk_level: str | None
    risk_score: float | None
    priority_date: date | None
    jurisdiction: str
    llm_mode: str
    confidential: bool
    retention_days: int | None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    permissions: CasePermissions


class CaseList(BaseModel):
    items: list[CaseOut]
    total: int


class ShareRequest(StrictModel):
    user_id: uuid.UUID
    permission: Literal["read", "write"] = "read"


class ShareOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    permission: str


# ---- disclosure ---------------------------------------------------------------


class ElementIn(CleanText):
    text: str = Field(min_length=1, max_length=1000)
    source: Literal["user", "llm"] = "user"


class DisclosureIn(CleanText):
    title: str = Field(min_length=1, max_length=300)
    technical_field: str = Field(default="", max_length=2000)
    problem: str = Field(default="", max_length=8000)
    solution: str = Field(default="", max_length=8000)
    elements: list[ElementIn] = Field(default_factory=list, max_length=30)


class ElementOut(BaseModel):
    id: str
    position: int
    text: str
    source: str


class DisclosureOut(BaseModel):
    title: str
    technical_field: str
    problem: str
    solution: str
    elements: list[ElementOut]
    content_hash: str | None


class UploadOut(BaseModel):
    filename: str
    characters: int
    text: str


# ---- pipeline, results, chart -------------------------------------------------


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class ResultOut(BaseModel):
    rank: int
    patent_id: str
    title: str | None
    source: str | None
    assignee: str | None
    publication_date: date | None
    cpc_subclasses: list[str]
    url: str | None
    score: float
    fused_score: float | None
    rerank_score: float | None
    matched_chunk_ids: list[str]
    excluded: bool
    in_chart: bool


class ResultsOut(BaseModel):
    run_id: uuid.UUID | None
    suggested_cpc: list[Any]
    results: list[ResultOut]


class CellOut(BaseModel):
    id: uuid.UUID
    element: str
    patent_id: str
    status: str
    confidence: float
    passage_id: str | None
    excerpt: str | None
    rationale: str | None
    method: str
    overridden: bool
    original: dict[str, Any] | None
    override_reason: str | None


class ChartOut(BaseModel):
    chart_status: str | None
    elements: list[ElementOut]
    references: list[str]
    cells: list[CellOut]


class CellOverride(CleanText):
    status: Literal["disclosed", "partial", "not_found"]
    reason: str = Field(min_length=5, max_length=1000)


# ---- report and review --------------------------------------------------------


class ReportEdit(StrictModel):
    content: dict[str, Any]


class VersionInfo(BaseModel):
    version: int
    content_hash: str
    created_at: datetime
    approved_at: datetime | None


class ReportOut(BaseModel):
    state: str
    version: int
    content_hash: str
    content: dict[str, Any]
    versions: list[VersionInfo]
    approval: dict[str, Any] | None


class ReviewComment(CleanText):
    comment: str | None = Field(default=None, max_length=2000)


class ChangesRequest(CleanText):
    comment: str = Field(min_length=3, max_length=2000)


class ReviewEventOut(BaseModel):
    id: int
    event_type: str
    user_id: uuid.UUID | None
    cell_id: uuid.UUID | None
    comment: str | None
    created_at: datetime


# ---- admin --------------------------------------------------------------------


class AuditOut(BaseModel):
    id: int
    user_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    ip_address: str | None
    detail: dict[str, Any]
    created_at: datetime


class PlanOut(BaseModel):
    id: int
    code: str
    name: str
    monthly_price: float
    included_reports: int
    overage_price: float
    seats: int
