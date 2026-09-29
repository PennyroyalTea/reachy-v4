"""Find when each tag happens in the generated audio.

Word timings come from ElevenLabs character alignment when we have it, or from
local faster-whisper otherwise. Tags are then placed between the timed words:
a state tag starts with the next spoken word, an event tag (laugh, gasp, sigh)
fills the gap after the previous word.
"""

import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from .emotions import EMOTIONS
from .tags import Script

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


class Word(BaseModel):
    text: str
    start: float
    end: float


class Cue(BaseModel):
    emotion: str
    kind: str
    intensity: float
    raw: str
    t: float  # when the body should hit the emotion
    gap_start: float  # end of the previous spoken word
    gap_end: float  # start of the next spoken word


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel("small.en", device="cpu", compute_type="int8")


def whisper_words(audio: Path) -> list[Word]:
    segments, _ = _whisper().transcribe(str(audio), word_timestamps=True, beam_size=5)
    return [Word(text=w.word.strip(), start=w.start, end=w.end) for s in segments for w in s.words]


def words_from_char_alignment(alignment: dict) -> list[Word]:
    """Group ElevenLabs `alignment` characters into words (tags stay as their own words)."""
    words: list[Word] = []
    buf, start, end = "", 0.0, 0.0
    for ch, s, e in zip(
        alignment["characters"], alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    ):
        if ch.isspace():
            if buf:
                words.append(Word(text=buf, start=start, end=end))
            buf = ""
            continue
        if not buf:
            start = s
        buf += ch
        end = e
    if buf:
        words.append(Word(text=buf, start=start, end=end))
    return words


def place_cues(script: Script, words: list[Word], duration: float, lead: float = 0.12) -> list[Cue]:
    src = [(m.group(0), m.start(), m.end()) for m in WORD_RE.finditer(script.clean)]
    timed = [w for w in words if _norm(w.text)]
    sm = SequenceMatcher(a=[_norm(w) for w, _, _ in src], b=[_norm(w.text) for w in timed], autojunk=False)

    # src index -> (start, end); fill unmatched words by interpolating between neighbours
    times: list[tuple[float, float] | None] = [None] * len(src)
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            w = timed[block.b + k]
            times[block.a + k] = (w.start, w.end)
    known = [i for i, t in enumerate(times) if t]
    for i in range(len(src)):
        if times[i] is None:
            before = max((k for k in known if k < i), default=None)
            after = min((k for k in known if k > i), default=None)
            lo = times[before][1] if before is not None else 0.0
            hi = times[after][0] if after is not None else duration
            times[i] = (lo, hi)

    cues: list[Cue] = []
    for tag in script.tags:
        if tag.emotion is None:
            continue
        nxt = next((i for i, (_, s, _) in enumerate(src) if s >= tag.clean_pos), None)
        prv = max((i for i, (_, _, e) in enumerate(src) if e <= tag.clean_pos), default=None)
        gap_start = times[prv][1] if prv is not None else 0.0
        gap_end = times[nxt][0] if nxt is not None else duration
        kind = EMOTIONS[tag.emotion].kind
        t = gap_start + 0.04 if kind == "event" and prv is not None else gap_end - lead
        cues.append(
            Cue(
                emotion=tag.emotion,
                kind=kind,
                intensity=tag.intensity,
                raw=tag.raw,
                t=max(0.0, t),
                gap_start=gap_start,
                gap_end=gap_end,
            )
        )
    return cues
