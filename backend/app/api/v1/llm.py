"""LLM mode for every signed-in user, and the administrator's settings, quota and breaker views."""

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import PrincipalDep, SessionDep, ip_of, require
from app.llm.gateway import LLMGateway
from app.llm.store import VALID_MODES, LlmSettings
from app.security import policy
from app.services import audit

router = APIRouter(prefix="/llm", tags=["llm"])
admin_router = APIRouter(prefix="/admin/llm", tags=["admin"])
AdminDep = Depends(require(policy.can_manage_llm))

MODEL_ID = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"


def gateway_of(request: Request) -> LLMGateway:
    return request.app.state.llm_gateway


class LlmSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    groq_model: str = Field(pattern=MODEL_ID)
    gemini_model: str = Field(pattern=MODEL_ID)

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in VALID_MODES:
            raise ValueError(f"mode must be one of {', '.join(VALID_MODES)}")
        return value

    @field_validator("gemini_model")
    @classmethod
    def _not_deprecated(cls, value: str) -> str:
        if value.startswith("gemini-2.5"):
            raise ValueError("Gemini 2.5 models are scheduled for shutdown, choose a newer model")
        return value


@router.get("/mode")
def llm_mode(request: Request, _: PrincipalDep) -> dict:
    """What the wizard shows: the global mode and whether any provider can answer."""
    gateway = gateway_of(request)
    mode = gateway.store.get().mode
    configured = {name: name in gateway.providers for name in ("groq", "gemini")}
    return {
        "mode": mode,
        "providers_configured": configured,
        "llm_available": mode != "local_only" and any(configured.values()),
    }


@admin_router.get("/status")
def llm_status(request: Request, _: policy.Principal = AdminDep) -> dict:
    """Mode, models, per-provider quota meters (day and minute) and circuit breaker state."""
    return gateway_of(request).status()


@admin_router.get("/settings")
def get_llm_settings(request: Request, _: policy.Principal = AdminDep) -> dict:
    store = gateway_of(request).store
    current, defaults = store.get(), store.defaults()
    return {
        "mode": current.mode,
        "groq_model": current.groq_model,
        "gemini_model": current.gemini_model,
        "defaults": {
            "mode": defaults.mode,
            "groq_model": defaults.groq_model,
            "gemini_model": defaults.gemini_model,
        },
    }


@admin_router.put("/settings")
def put_llm_settings(
    request: Request,
    body: LlmSettingsIn,
    session: SessionDep,
    admin: policy.Principal = AdminDep,
) -> dict:
    gateway = gateway_of(request)
    previous = gateway.store.get()
    gateway.store.save(LlmSettings(body.mode, body.groq_model, body.gemini_model), admin.id)
    audit.record(
        session,
        audit.LLM_SETTINGS_CHANGE,
        user_id=admin.id,
        ip=ip_of(request),
        detail={
            "mode": f"{previous.mode} -> {body.mode}",
            "groq_model": f"{previous.groq_model} -> {body.groq_model}",
            "gemini_model": f"{previous.gemini_model} -> {body.gemini_model}",
        },
    )
    session.commit()
    return get_llm_settings(request, admin)


@admin_router.post("/breakers/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_breakers(
    request: Request, session: SessionDep, admin: policy.Principal = AdminDep
) -> None:
    for breaker in gateway_of(request).breakers.values():
        breaker.reset()
    audit.record(session, audit.LLM_BREAKER_RESET, user_id=admin.id, ip=ip_of(request))
    session.commit()
