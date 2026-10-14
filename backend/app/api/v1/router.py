from fastapi import APIRouter

from app.api.v1 import admin, analytics, auth, billing, cases, llm, pipeline, public, reports, users

api_router = APIRouter(prefix="/api/v1")
for module_router in (
    auth.router,
    users.router,
    cases.router,
    pipeline.router,
    reports.router,
    admin.analytics_router,
    admin.billing_router,
    admin.admin_router,
    admin.health_router,
    billing.router,
    analytics.router,
    llm.router,
    llm.admin_router,
    public.router,
):
    api_router.include_router(module_router)
