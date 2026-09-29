"""ElevenLabs API: Eleven v4 speech with word timings, and forced alignment for existing audio.

Word timings decide when each tag's emotion hits the body. The with-timestamps
endpoint returns them with the audio; for audio made elsewhere, the forced
alignment endpoint aligns the tag-free transcript to it.
"""

import base64
import os

import httpx
from pydantic import BaseModel

from .align import Word, words_from_char_alignment
from .tags import parse

DEFAULT_VOICE_ID = "wIzYfKZE8c87XZD7bDLH"  # Zibby: quirky, very expressive; any voice works
DEFAULT_MODEL = "eleven_v4"


class Speech(BaseModel):
    audio: bytes
    words: list[Word]
    request_id: str | None = None


class ApiError(RuntimeError):
    pass


def _base_url() -> str:
    # data residency workspaces use their own host, for example https://api.eu.residency.elevenlabs.io
    return os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise ApiError("ELEVENLABS_API_KEY is not set")
    return key


def _check(r: httpx.Response, what: str) -> None:
    if r.is_success:
        return
    try:
        detail = r.json().get("detail")
        msg = detail.get("message") if isinstance(detail, dict) else detail
    except ValueError:
        msg = r.text[:200]
    raise ApiError(f"{what} failed ({r.status_code}): {msg}")


def synthesize(text: str, voice_id: str = DEFAULT_VOICE_ID, model_id: str = DEFAULT_MODEL) -> Speech:
    """Speak tagged text with Eleven v4 and return mp3 bytes plus word timings."""
    r = httpx.post(
        f"{_base_url()}/v1/text-to-speech/{voice_id}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": api_key()},
        json={"text": text, "model_id": model_id},
        timeout=180,
    )
    _check(r, "text to speech")
    data = r.json()
    audio = base64.b64decode(data["audio_base64"])
    alignment = data.get("alignment") or data.get("normalized_alignment")
    words = words_from_char_alignment(alignment) if alignment else force_align(audio, text)
    return Speech(audio=audio, words=words, request_id=r.headers.get("request-id"))


def force_align(audio: bytes, text: str) -> list[Word]:
    """Word timings for existing speech; tags are stripped because they are not spoken."""
    r = httpx.post(
        f"{_base_url()}/v1/forced-alignment",
        headers={"xi-api-key": api_key()},
        files={"file": ("speech.mp3", audio, "audio/mpeg")},
        data={"text": parse(text).clean},
        timeout=180,
    )
    _check(r, "forced alignment")
    return [Word(text=w["text"], start=w["start"], end=w["end"]) for w in r.json()["words"] if w["text"].strip()]
