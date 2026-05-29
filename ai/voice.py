"""Voice processing: Whisper STT (speech-to-text) and OpenAI TTS (text-to-speech)."""
import logging
import tempfile
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    """Lazily create and cache the OpenAI async client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


async def transcribe_audio(audio_bytes: bytes, suffix: str = ".ogg") -> str:
    """Transcribe voice audio bytes to text using OpenAI Whisper.

    Args:
        audio_bytes: Raw audio file bytes (ogg/opus from Telegram, or other formats).
        suffix: File extension for the temp file (e.g. .ogg, .webm, .mp3).

    Returns:
        Transcribed text string. Empty string on failure.
    """
    client = _get_client()
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )

        result = transcript.strip() if transcript else ""
        Path(tmp_path).unlink(missing_ok=True)
        return result

    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return ""


async def text_to_speech(text: str, voice: str = "alloy") -> Optional[bytes]:
    """Convert text to speech audio bytes using OpenAI TTS.

    Args:
        text: The text to vocalize (up to ~4096 chars).
        voice: TTS voice name (alloy, echo, fable, onyx, nova, shimmer).

    Returns:
        MP3 audio bytes, or None on failure.
    """
    try:
        client = _get_client()
        response = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return response.content
    except Exception as exc:
        logger.error("OpenAI TTS failed: %s", exc)
        return None
