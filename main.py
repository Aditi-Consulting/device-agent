"""Entry point for the Device Agent API server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(override=False)  # must run before any src.* imports read os.getenv()

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.device_agent.api.routes import router
from src.device_agent.config import settings
from src.device_agent.store.db import ensure_tables

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Device Agent API starting up...")
    ensure_tables()
    yield
    logger.info("Device Agent API shutting down...")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    _configure_logging()

    application = FastAPI(
        title="Device Agent",
        description="LangGraph-powered device unlock workflow API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — allows external services and browsers to call the API
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Uniform validation error response — same shape as UnlockResponse
    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        message = (
            errors[0]["msg"].replace("Value error, ", "")
            if errors
            else "Invalid input."
        )
        logger.warning("Validation error on %s: %s", request.url.path, message)
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "alert_id": 0,
                "alert_name": "",
                "imei": "",
                "eligible": False,
                "result": "",
                "error": message,
                "workflow_type": "infrastructure",
                "workflow_status": "failed",
                "email_sent": False,
                "confidence_score": 0.0,
            },
        )

    # Health check — standard for monitoring / load balancers / k8s probes
    @application.get("/health", tags=["Health"])
    async def health_check() -> dict:
        return {"status": "ok"}

    application.include_router(router, prefix="/api/v1")

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True)
