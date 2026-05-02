from fastapi import APIRouter

from app.api.routes import audit, auth, coverage, directory, document, export, gaps, generation, materials, ocr, outline, parse, projects, review, settings, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(parse.router)
api_router.include_router(directory.router)
api_router.include_router(outline.router)
api_router.include_router(gaps.router)
api_router.include_router(review.router)
api_router.include_router(generation.router)
api_router.include_router(coverage.router)
api_router.include_router(document.router)
api_router.include_router(export.router)
api_router.include_router(materials.router)
api_router.include_router(ocr.router)
api_router.include_router(audit.router)
api_router.include_router(settings.router)
