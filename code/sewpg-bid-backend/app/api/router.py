from fastapi import APIRouter

from app.api.routes import auth, business, business_gaps, dashboard, performance, project_info, settings, system, technical

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(performance.router)
api_router.include_router(project_info.router)
api_router.include_router(business.router)
api_router.include_router(business_gaps.router)
api_router.include_router(technical.router)
api_router.include_router(settings.router)
