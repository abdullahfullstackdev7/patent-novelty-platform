"""Cases: CRUD, sharing, encrypted disclosure and upload parsing."""

# No `from __future__ import annotations` here: slowapi wraps the endpoints and FastAPI would
# then fail to resolve the string annotations against the wrapper's globals.
import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select

from app.api.deps import PrincipalDep, SessionDep, SettingsDep, ip_of, require
from app.api.v1.schemas import (
    CaseCreate,
    CaseList,
    CaseOut,
    CasePermissions,
    CaseUpdate,
    DisclosureIn,
    DisclosureOut,
    ElementOut,
    ExtractOut,
    ShareOut,
    ShareRequest,
    UploadOut,
)
from app.db.models import Case, CaseShare, Role, User
from app.pipeline.intake import extract_elements
from app.security import policy
from app.security.http import limiter, llm_limit
from app.services import audit
from app.services.access import forbidden, load_case, not_found, visible_cases
from app.services.disclosures import load_disclosure, save_disclosure

router = APIRouter(tags=["cases"])

ALLOWED_UPLOAD_SUFFIXES = (".txt", ".md")
ALLOWED_UPLOAD_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/octet-stream",  # some browsers send this for .md
}
LOCKED_MESSAGE = "This case is approved and can no longer be changed"


def case_out(case: Case, principal: policy.Principal, share: CaseShare | None) -> CaseOut:
    return CaseOut(
        id=case.id,
        title=case.title,
        status=case.status,
        stage=case.stage,
        risk_level=case.risk_level,
        risk_score=float(case.risk_score) if case.risk_score is not None else None,
        priority_date=case.priority_date,
        jurisdiction=case.jurisdiction,
        llm_mode=case.llm_mode,
        confidential=case.confidential,
        retention_days=case.retention_days,
        owner_id=case.owner_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        permissions=CasePermissions(
            edit=policy.can_edit_case(principal, case, share),
            delete=policy.can_delete_case(principal, case),
            share=policy.can_share_case(principal, case),
            review=policy.can_review_case(principal, case, share),
        ),
    )


def ensure_editable(case: Case) -> None:
    if case.status == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED_MESSAGE)


# ---- cases --------------------------------------------------------------------


@router.get("/cases", response_model=CaseList)
def list_cases(
    principal: PrincipalDep,
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CaseList:
    query = visible_cases(principal)
    if status_filter:
        query = query.where(Case.status == status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    cases = session.scalars(
        query.order_by(Case.created_at.desc()).limit(limit).offset(offset)
    ).all()
    shares = {
        s.case_id: s
        for s in session.scalars(
            select(CaseShare).where(
                CaseShare.user_id == principal.id, CaseShare.case_id.in_([c.id for c in cases])
            )
        )
    }
    return CaseList(items=[case_out(c, principal, shares.get(c.id)) for c in cases], total=total)


@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    request: Request,
    body: CaseCreate,
    session: SessionDep,
    principal: policy.Principal = Depends(require(policy.can_create_case)),
) -> CaseOut:
    owner = session.get(User, principal.id)
    case = Case(
        owner_id=principal.id,
        client_id=owner.client_id if owner else None,
        title=body.title,
        priority_date=body.priority_date,
        jurisdiction=body.jurisdiction.upper(),
        llm_mode=body.llm_mode,
        confidential=body.confidential,
        retention_days=body.retention_days,
    )
    session.add(case)
    session.flush()
    audit.record(
        session, audit.CASE_CREATE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case.id,
    )  # fmt: skip
    session.commit()
    session.refresh(case)
    return case_out(case, principal, None)


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(
    case_id: uuid.UUID, request: Request, principal: PrincipalDep, session: SessionDep
) -> CaseOut:
    case, share = load_case(session, principal, case_id)
    audit.record(
        session, audit.CASE_VIEW, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case.id,
    )  # fmt: skip
    session.commit()
    return case_out(case, principal, share)


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(
    case_id: uuid.UUID,
    body: CaseUpdate,
    principal: PrincipalDep,
    session: SessionDep,
) -> CaseOut:
    case, share = load_case(session, principal, case_id)
    if not policy.can_edit_case(principal, case, share):
        raise forbidden()
    ensure_editable(case)
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None and field in {"title", "llm_mode", "confidential"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be empty")
        setattr(case, field, value)
    case.updated_at = datetime.now(UTC)
    session.commit()
    return case_out(case, principal, share)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(
    case_id: uuid.UUID, request: Request, principal: PrincipalDep, session: SessionDep
) -> Response:
    """Hard delete. Foreign keys cascade to the disclosure, runs, chart, reports and jobs."""
    case, _ = load_case(session, principal, case_id)
    if not policy.can_delete_case(principal, case):
        raise forbidden()
    audit.record(
        session, audit.CASE_DELETE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case.id,
    )  # fmt: skip
    session.delete(case)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- sharing ------------------------------------------------------------------


@router.get("/cases/{case_id}/shares", response_model=list[ShareOut])
def list_shares(case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> list[ShareOut]:
    load_case(session, principal, case_id)
    rows = session.execute(
        select(CaseShare, User)
        .join(User, User.id == CaseShare.user_id)
        .where(CaseShare.case_id == case_id)
    ).all()
    return [ShareOut(user_id=u.id, email=u.email, full_name=u.full_name, permission=s.permission)
            for s, u in rows]  # fmt: skip


@router.post(
    "/cases/{case_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED
)
def share_case(
    case_id: uuid.UUID,
    request: Request,
    body: ShareRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> ShareOut:
    case, _ = load_case(session, principal, case_id)
    if not policy.can_share_case(principal, case):
        raise forbidden()
    target = session.get(User, body.user_id)
    if target is None or not target.is_active:
        raise not_found()
    if target.id == case.owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The owner already has access")
    target_role = session.scalars(select(Role.name).where(Role.id == target.role_id)).one()
    if body.permission == "write" and target_role not in policy.CASE_WORKERS | {policy.ADMIN}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This role cannot be given write access")
    share = session.get(CaseShare, (case_id, target.id))
    if share is None:
        share = CaseShare(case_id=case_id, user_id=target.id, permission=body.permission)
        session.add(share)
    else:
        share.permission = body.permission
    audit.record(
        session, audit.CASE_SHARE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id,
        detail={"shared_with": str(target.id), "permission": body.permission},
    )  # fmt: skip
    session.commit()
    return ShareOut(
        user_id=target.id, email=target.email, full_name=target.full_name,
        permission=body.permission,
    )  # fmt: skip


@router.delete("/cases/{case_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_case(
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> Response:
    case, _ = load_case(session, principal, case_id)
    if not policy.can_share_case(principal, case):
        raise forbidden()
    share = session.get(CaseShare, (case_id, user_id))
    if share is None:
        raise not_found()
    session.delete(share)
    audit.record(
        session, audit.CASE_UNSHARE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"removed": str(user_id)},
    )  # fmt: skip
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- disclosure ---------------------------------------------------------------


def _disclosure_out(data) -> DisclosureOut:
    return DisclosureOut(
        title=data.title,
        technical_field=data.technical_field,
        problem=data.problem,
        solution=data.solution,
        elements=[ElementOut(id=e.key, position=e.position, text=e.text, source=e.source)
                  for e in data.elements],
        content_hash=data.content_hash,
    )  # fmt: skip


@router.get("/cases/{case_id}/disclosure", response_model=DisclosureOut)
def get_disclosure(
    case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> DisclosureOut:
    load_case(session, principal, case_id)
    data = load_disclosure(session, settings, case_id)
    if data is None:
        raise not_found()
    return _disclosure_out(data)


@router.put("/cases/{case_id}/disclosure", response_model=DisclosureOut)
def put_disclosure(
    case_id: uuid.UUID,
    body: DisclosureIn,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> DisclosureOut:
    case, share = load_case(session, principal, case_id)
    if not policy.can_edit_case(principal, case, share):
        raise forbidden()
    ensure_editable(case)
    if case.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "The case is running, wait for it to finish")
    save_disclosure(
        session, settings, case_id,
        title=body.title, technical_field=body.technical_field,
        problem=body.problem, solution=body.solution,
        elements=[(e.text, e.source) for e in body.elements],
    )  # fmt: skip
    case.updated_at = datetime.now(UTC)
    session.commit()
    return _disclosure_out(load_disclosure(session, settings, case_id))


@router.post("/disclosure/parse-upload", response_model=UploadOut)
@limiter.limit("30/minute")
async def parse_upload(
    request: Request,
    settings: SettingsDep,
    principal: policy.Principal = Depends(require(policy.can_parse_upload)),
    file: UploadFile = File(...),
) -> UploadOut:
    """Read a .txt or .md file and return its text for the wizard. Nothing is stored."""
    name = (file.filename or "").strip()
    if not name.lower().endswith(ALLOWED_UPLOAD_SUFFIXES):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .txt and .md files")
    if (file.content_type or "").split(";")[0].strip().lower() not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported content type")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
    if b"\x00" in data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Binary content is not allowed")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be UTF-8 text") from None
    safe_name = name.replace("\\", "/").rsplit("/", 1)[-1][:120]
    return UploadOut(filename=safe_name, characters=len(text), text=text)


@router.post("/cases/{case_id}/disclosure/extract-elements", response_model=ExtractOut)
@limiter.limit(llm_limit)
def extract_disclosure_elements(
    request: Request,
    case_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    replace: bool = Query(default=False, description="Replace elements that already exist"),
) -> ExtractOut:
    """Intake checkpoint: derive 6 to 10 elements from the disclosure with one LLM call (or a
    local fallback in local_only mode). The user reviews and edits them before running."""
    case, share = load_case(session, principal, case_id)
    if not policy.can_edit_case(principal, case, share):
        raise forbidden()
    ensure_editable(case)
    if case.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "The case is running, wait for it to finish")
    data = load_disclosure(session, settings, case_id)
    if data is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save the disclosure first")
    if data.elements and not replace:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Elements already exist, use replace=true to extract again"
        )
    extraction = extract_elements(
        request.app.state.llm_gateway,
        title=data.title,
        technical_field=data.technical_field,
        problem=data.problem,
        solution=data.solution,
        case_id=case.id,
        case_mode=case.llm_mode,
    )
    if not extraction.elements:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No elements could be derived, please enter the key elements by hand",
        )
    save_disclosure(
        session, settings, case_id,
        title=data.title, technical_field=data.technical_field,
        problem=data.problem, solution=data.solution,
        elements=[(text, extraction.source) for text in extraction.elements],
    )  # fmt: skip
    audit.record(
        session,
        audit.ELEMENTS_EXTRACTED,
        user_id=principal.id,
        ip=ip_of(request),
        entity_type="case",
        entity_id=case_id,
        detail={
            "source": extraction.source,
            "count": len(extraction.elements),
            "used": extraction.tokens,
        },  # fmt: skip
    )
    case.updated_at = datetime.now(UTC)
    session.commit()
    saved = load_disclosure(session, settings, case_id)
    return ExtractOut(
        elements=[ElementOut(id=e.key, position=e.position, text=e.text, source=e.source)
                  for e in saved.elements],
        source=extraction.source,
        tokens=extraction.tokens,
        provider=extraction.provider,
        cache_hit=extraction.cache_hit,
        fallback_reason=extraction.fallback_reason,
    )  # fmt: skip
