"""Text with tags + audio -> timed cues -> motion timeline -> robot."""

from collections.abc import Callable
from pathlib import Path

import soundfile as sf
from pydantic import BaseModel

from .align import Cue, Word, place_cues, whisper_words
from .choreo import Choreographer, to_move
from .robot import Robot
from .tags import parse


class Plan(BaseModel):
    text: str
    duration: float
    words: list[Word]
    cues: list[Cue]
    safety: dict = {}
    move: dict


def audio_duration(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate


def plan(text: str, audio: Path, words: list[Word] | None = None) -> Plan:
    script = parse(text)
    duration = audio_duration(audio)
    words = words if words is not None else whisper_words(audio)
    cues = place_cues(script, words, duration)
    choreo = Choreographer()
    t, pose = choreo.build(cues, duration, audio=audio)
    return Plan(
        text=text,
        duration=duration,
        words=words,
        cues=cues,
        safety=choreo.safety,
        move=to_move(t, pose, description=text[:200]),
    )


async def perform(
    robot: Robot, p: Plan, audio: Path, audio_lead_ms: float = 60.0, on_event: Callable[[dict], None] | None = None
) -> dict:
    await robot.set_motor_mode("enabled")
    # speech wobble is baked into the timeline (collision-checked), so the daemon must not add its own
    await robot.set_wobbling(False)
    return await robot.play_timeline(
        p.move,
        audio=audio.read_bytes(),
        audio_format=audio.suffix.lstrip(".") or "mp3",
        audio_lead_ms=audio_lead_ms,
        initial_goto_duration=0.5,
        on_event=on_event,
    )
