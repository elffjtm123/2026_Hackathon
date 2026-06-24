import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.base import GazeAdapter, SpeechAdapter
from app.ai.http import HTTPGazeAdapter, HTTPSpeechAdapter
from app.ai.mock import MockGazeAdapter, MockSpeechAdapter
from app.api.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.websocket import router as websocket_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db import models  # noqa: F401 -- registers SQLAlchemy metadata
from app.db.session import Database
from app.realtime.registry import PipelineRegistry
from app.realtime.state import SessionStateStore
from app.realtime.webrtc import WebRTCManager

logger = logging.getLogger(__name__)


def error_body(
    request: Request, code: str, message: str, details: object = None
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
            "details": details,
        }
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.app_env == "production" and settings.jwt_secret.startswith("development-"):
        raise RuntimeError("A secure JWT_SECRET is required in production")
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_url)
        state_store = SessionStateStore(settings.redis_url)
        http_clients: list[object] = []
        gaze: GazeAdapter
        speech: SpeechAdapter
        if settings.ai_mode == "http":
            http_gaze = HTTPGazeAdapter(settings)
            http_speech = HTTPSpeechAdapter(settings)
            gaze = http_gaze
            speech = http_speech
            http_clients = [http_gaze.client, http_speech.client]
        else:
            gaze = MockGazeAdapter()
            speech = MockSpeechAdapter()
        app.state.settings = settings
        app.state.database = database
        app.state.state_store = state_store
        app.state.pipelines = PipelineRegistry(settings, state_store, gaze, speech)
        app.state.webrtc = WebRTCManager(settings)
        app.state.websocket_counts = {}
        if settings.auto_create_tables:
            await database.create_tables()
        yield
        await app.state.webrtc.close()
        await app.state.pipelines.close()
        await state_store.close()
        for client in http_clients:
            await client.aclose()  # type: ignore[attr-defined]
        await database.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: object) -> object:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
        request.state.request_id = request_id
        response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                request, "VALIDATION_ERROR", "입력값이 올바르지 않습니다.", exc.errors()
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, "HTTP_ERROR", str(exc.detail)),
        )

    app.include_router(health_router)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(sessions_router, prefix=settings.api_prefix)
    app.include_router(websocket_router, prefix=settings.api_prefix)
    return app


app = create_app()
