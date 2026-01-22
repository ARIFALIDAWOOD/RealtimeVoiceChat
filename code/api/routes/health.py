# api/routes/health.py
"""Health check routes for monitoring service status."""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request

from api.models import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

# Version info (can be set from environment or package version)
API_VERSION = os.getenv("API_VERSION", "1.0.0")


@router.get(
    "",
    response_model=HealthResponse,
)
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint.

    Returns service status and version information.
    Use this for simple liveness probes.

    Returns:
        Health status with version and timestamp.
    """
    return HealthResponse(
        status="healthy",
        version=API_VERSION,
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
)
async def readiness_check(request: Request) -> ReadinessResponse:
    """
    Readiness check endpoint.

    Checks connectivity to all required services:
    - Database connection
    - Redis connection (if configured)
    - TTS engine availability
    - LLM provider availability

    Use this for readiness probes in container orchestration.

    Args:
        request: FastAPI request for accessing app state.

    Returns:
        Detailed readiness status for each service.
    """
    results = {
        "database": "unknown",
        "redis": "unavailable",
        "tts_engine": "unknown",
        "llm_provider": "unknown",
    }

    # Check database
    try:
        from database import get_engine

        engine = get_engine()
        if engine is not None:
            results["database"] = "connected"
        else:
            results["database"] = "not_initialized"
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        results["database"] = "error"

    # Check Redis (optional)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as redis

            r = redis.from_url(redis_url)
            await r.ping()
            await r.close()
            results["redis"] = "connected"
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            results["redis"] = "error"
    else:
        results["redis"] = "not_configured"

    # Check TTS engine (from app state if available)
    try:
        if hasattr(request.app.state, "SpeechPipelineManager"):
            pipeline = request.app.state.SpeechPipelineManager
            if pipeline and hasattr(pipeline, "audio_processor"):
                results["tts_engine"] = "available"
            else:
                results["tts_engine"] = "not_initialized"
        else:
            results["tts_engine"] = "not_configured"
    except Exception as e:
        logger.warning(f"TTS engine health check failed: {e}")
        results["tts_engine"] = "error"

    # Check LLM provider
    try:
        if hasattr(request.app.state, "SpeechPipelineManager"):
            pipeline = request.app.state.SpeechPipelineManager
            if pipeline and hasattr(pipeline, "llm"):
                results["llm_provider"] = "available"
            else:
                results["llm_provider"] = "not_initialized"
        else:
            # Check if API key is configured
            if os.getenv("OPENAI_API_KEY"):
                results["llm_provider"] = "configured"
            else:
                results["llm_provider"] = "not_configured"
    except Exception as e:
        logger.warning(f"LLM provider health check failed: {e}")
        results["llm_provider"] = "error"

    # Determine overall readiness
    # Ready if database is connected and at least one of TTS/LLM is available
    is_ready = (
        results["database"] in ["connected", "not_initialized"]
        and results["tts_engine"] in ["available", "not_configured"]
        and results["llm_provider"] in ["available", "configured", "not_configured"]
    )

    return ReadinessResponse(
        ready=is_ready,
        database=results["database"],
        redis=results["redis"],
        tts_engine=results["tts_engine"],
        llm_provider=results["llm_provider"],
    )


@router.get(
    "/live",
)
async def liveness_check() -> dict:
    """
    Simple liveness probe.

    Returns 200 OK if the service is running.
    Use this for Kubernetes liveness probes.

    Returns:
        Simple status object.
    """
    return {"status": "alive"}
