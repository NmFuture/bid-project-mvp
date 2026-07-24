from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.auth_service import auth_service
from app.services.ocr_service import ocr_service
from app.services.system_settings import system_settings_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    # Ensure MinIO buckets exist
    for bucket in settings.minio_buckets.values():
        minio_client.ensure_bucket(bucket)
    await auth_service.ensure_bootstrap_admin()
    await system_settings_service._ensure_tables()
    await ocr_service.start_worker()
    try:
        yield
    finally:
        await ocr_service.stop_worker()


app = FastAPI(
    title="SEWPG Bid MVP Backend",
    version="0.1.0",
    description="MVP FastAPI backend skeleton for frontend integration.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(KeyError)
async def handle_key_error(_, exc: KeyError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": f"资源不存在: {exc.args[0]}",
            "code": "NOT_FOUND",
        },
    )


@app.exception_handler(PeripheralError)
async def handle_peripheral_error(_, exc: PeripheralError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


app.include_router(api_router)
