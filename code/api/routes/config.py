# api/routes/config.py
"""Configuration discovery routes for available personas, LLM providers, and TTS engines."""

import json
import logging
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter

from api.models import (
    LLMProviderInfo,
    LLMProvidersResponse,
    PersonaInfo,
    PersonasResponse,
    TTSEngineInfo,
    TTSEnginesResponse,
    VerbosityLevel,
    VerbosityLevelsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["Configuration"])

# Cache for system prompts config
_system_prompts_cache = None


def _load_system_prompts() -> dict:
    """Load and cache system prompts configuration."""
    global _system_prompts_cache

    if _system_prompts_cache is not None:
        return _system_prompts_cache

    # Try to load from file
    config_path = Path(__file__).parent.parent.parent / "system_prompts.json"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _system_prompts_cache = json.load(f)
            logger.info(f"Loaded system prompts from {config_path}")
    except FileNotFoundError:
        logger.warning(f"system_prompts.json not found at {config_path}, using defaults")
        _system_prompts_cache = {
            "personas": {"default": {"name": "Default", "base_prompt": "You are a helpful assistant."}},
            "verbosity_levels": {
                "brief": {"name": "Brief", "instruction": "Keep responses very short and concise."},
                "normal": {"name": "Normal", "instruction": "Provide balanced responses."},
                "detailed": {"name": "Detailed", "instruction": "Provide comprehensive, detailed responses."},
            },
        }
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing system_prompts.json: {e}")
        _system_prompts_cache = {"personas": {}, "verbosity_levels": {}}

    return _system_prompts_cache


@router.get(
    "/personas",
    response_model=PersonasResponse,
)
async def list_personas() -> PersonasResponse:
    """
    List available conversation personas.

    Personas define the AI's personality and communication style.

    Returns:
        List of available personas with their metadata.
    """
    config = _load_system_prompts()
    personas_config = config.get("personas", {})

    personas = []
    for persona_id, persona_data in personas_config.items():
        # Extract a brief description from the base_prompt if available
        base_prompt = persona_data.get("base_prompt", "")
        description = base_prompt[:100] + "..." if len(base_prompt) > 100 else base_prompt

        personas.append(
            PersonaInfo(
                id=persona_id,
                name=persona_data.get("name", persona_id.title()),
                description=description or None,
            )
        )

    return PersonasResponse(personas=personas)


@router.get(
    "/verbosity-levels",
    response_model=VerbosityLevelsResponse,
)
async def list_verbosity_levels() -> VerbosityLevelsResponse:
    """
    List available verbosity levels.

    Verbosity levels control how detailed the AI's responses are.

    Returns:
        List of available verbosity levels.
    """
    config = _load_system_prompts()
    verbosity_config = config.get("verbosity_levels", {})

    levels = []
    for level_id, level_data in verbosity_config.items():
        levels.append(
            VerbosityLevel(
                id=level_id,
                name=level_data.get("name", level_id.title()),
                description=level_data.get("instruction"),
            )
        )

    return VerbosityLevelsResponse(levels=levels)


@router.get(
    "/llm-providers",
    response_model=LLMProvidersResponse,
)
async def list_llm_providers() -> LLMProvidersResponse:
    """
    List available LLM providers and their models.

    Returns information about configured LLM backends and
    whether they appear to be available.

    Returns:
        List of LLM providers with availability status.
    """
    providers = []

    # OpenAI
    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    providers.append(
        LLMProviderInfo(
            id="openai",
            name="OpenAI",
            models=[
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-4",
                "gpt-3.5-turbo",
            ],
            available=openai_available,
        )
    )

    # Ollama - check if base URL is configured
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    providers.append(
        LLMProviderInfo(
            id="ollama",
            name="Ollama (Local)",
            models=[
                "llama3.2",
                "llama3.1",
                "mistral",
                "mixtral",
                "codellama",
                "phi3",
            ],
            available=True,  # Availability checked at runtime
        )
    )

    # LM Studio
    lmstudio_url = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    providers.append(
        LLMProviderInfo(
            id="lmstudio",
            name="LM Studio (Local)",
            models=[
                "local-model",  # LM Studio serves whatever model is loaded
            ],
            available=True,  # Availability checked at runtime
        )
    )

    return LLMProvidersResponse(providers=providers)


@router.get(
    "/tts-engines",
    response_model=TTSEnginesResponse,
)
async def list_tts_engines() -> TTSEnginesResponse:
    """
    List available TTS engines and their voices.

    Returns information about configured text-to-speech engines
    and available voices.

    Returns:
        List of TTS engines with voice options.
    """
    engines = []

    # Kokoro (recommended, lightweight)
    engines.append(
        TTSEngineInfo(
            id="kokoro",
            name="Kokoro (Recommended)",
            voices=[
                "af_heart",
                "af_bella",
                "af_nicole",
                "af_sarah",
                "am_adam",
                "am_michael",
                "bf_emma",
                "bf_isabella",
                "bm_george",
                "bm_lewis",
            ],
            available=True,
        )
    )

    # Coqui XTTS (high quality but requires more resources)
    engines.append(
        TTSEngineInfo(
            id="coqui",
            name="Coqui XTTS",
            voices=[
                "reference_audio",  # Uses reference audio file
            ],
            available=True,  # Requires model download
        )
    )

    # Orpheus (GGUF-based)
    engines.append(
        TTSEngineInfo(
            id="orpheus",
            name="Orpheus",
            voices=[
                "tara",
                "dan",
                "josh",
                "emma",
            ],
            available=True,  # Requires model download
        )
    )

    return TTSEnginesResponse(engines=engines)


@router.get(
    "/languages",
    response_model=dict,
)
async def list_languages() -> dict:
    """
    List supported languages for STT/TTS.

    Returns:
        Dictionary of language codes and names.
    """
    return {
        "languages": [
            {"code": "en", "name": "English"},
            {"code": "es", "name": "Spanish"},
            {"code": "fr", "name": "French"},
            {"code": "de", "name": "German"},
            {"code": "it", "name": "Italian"},
            {"code": "pt", "name": "Portuguese"},
            {"code": "zh", "name": "Chinese"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
        ]
    }
