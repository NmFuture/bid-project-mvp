from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.services.peripheral import PeripheralError

app = FastAPI(
    title="SEWPG Bid MVP Backend",
    version="0.1.0",
    description="MVP FastAPI backend skeleton for frontend integration.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()


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
