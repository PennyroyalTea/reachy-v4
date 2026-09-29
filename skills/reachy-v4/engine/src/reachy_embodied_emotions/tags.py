"""Parse `[tag] text` scripts and map free-form v4 audio tags to demo emotions."""

import re

from pydantic import BaseModel

from .emotions import EMOTIONS

TAG_RE = re.compile(r"\[([^\[\]]+)\]")

WEAKER = {"slightly", "a bit", "a little", "somewhat", "mildly", "kind of", "soft", "softly", "light", "lightly", "gently", "quietly"}
STRONGER = {"very", "really", "extremely", "incredibly", "so", "super", "totally", "deeply", "loudly", "hysterically", "wildly", "absolutely"}

# Tags that shape delivery but carry no emotion: the robot keeps its current mood.
NEUTRAL_TAGS = {"pause", "long pause", "short pause", "beat", "casual", "measured", "calm", "calmly", "neutral", "normal", "clears throat"}


class Tag(BaseModel):
    raw: str
    emotion: str | None  # key into EMOTIONS; None = no embodiment (pause, sound effect, unknown)
    intensity: float
    char_start: int  # index of the tag in the original text
    clean_pos: int  # index in the tag-free text where the tag sits


class Script(BaseModel):
    text: str
    clean: str
    tags: list[Tag]


def _alias_index() -> list[tuple[str, str]]:
    pairs = [(e.name, e.name) for e in EMOTIONS.values()]
    pairs += [(alias, e.name) for e in EMOTIONS.values() for alias in e.aliases]
    return sorted(pairs, key=lambda p: -len(p[0]))  # longest phrase first


def classify(raw: str) -> tuple[str | None, float]:
    """Map a free-form tag like 'slightly annoyed' to (emotion, intensity 0..1.2)."""
    t = raw.strip().lower()
    if t in NEUTRAL_TAGS:
        return None, 0.0
    emotion = next((name for phrase, name in _alias_index() if re.search(rf"\b{re.escape(phrase)}\b", t)), None)
    if emotion is None:
        return None, 0.0
    intensity = 1.0
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in WEAKER):
        intensity = 0.6
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in STRONGER):
        intensity = 1.2
    return emotion, intensity


def parse(text: str) -> Script:
    tags: list[Tag] = []
    clean_parts: list[str] = []
    clean_len = 0
    last = 0
    for m in TAG_RE.finditer(text):
        chunk = text[last : m.start()]
        clean_parts.append(chunk)
        clean_len += len(chunk)
        emotion, intensity = classify(m.group(1))
        tags.append(Tag(raw=m.group(1), emotion=emotion, intensity=intensity, char_start=m.start(), clean_pos=clean_len))
        last = m.end()
    clean_parts.append(text[last:])
    clean = "".join(clean_parts)
    return Script(text=text, clean=clean, tags=tags)
