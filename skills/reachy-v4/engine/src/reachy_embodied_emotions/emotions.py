"""The 10 demo emotions and how the robot embodies each one.

Every emotion has:
- clips: Pollen emotion-library moves used for the onset gesture, or
- keyframes: a hand-made onset gesture (the sigh's breath), used instead of clips
- hold: the posture the robot keeps while it speaks in that mood
- idle: a small periodic motif layered on the hold so the pose stays alive

Pose units: degrees for angles, millimetres for x/y/z. Pitch > 0 looks down.
Antennas are [right, left]; neutral is [-10, 10], |angle| grows as they droop back.
Antenna language: sad fully drooped, sighs sink on the exhale, angry stiff horns,
scared straight up and trembling, whispers asymmetric, excited flapping.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["state", "event"]


class Pose(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    ant_r: float = -10.0
    ant_l: float = 10.0
    body_yaw: float = 0.0


class Wave(BaseModel):
    """A sine motif: channel += amp * sin(2*pi*hz*t + phase)."""

    channel: Literal["x", "y", "z", "roll", "pitch", "yaw", "ant_r", "ant_l", "body_yaw", "ants", "ants_mirror"]
    amp: float
    hz: float
    phase: float = 0.0


class Keyframe(BaseModel):
    """A pose at `t` seconds after the cue; poses in between are eased."""

    t: float
    pose: Pose


class Emotion(BaseModel):
    name: str
    label: str
    kind: Kind
    color: str
    aliases: list[str] = Field(default_factory=list)
    clips: list[str] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    hold: Pose = Field(default_factory=Pose)
    idle: list[Wave] = Field(default_factory=list)
    # How far into a clip to start (skips slow wind-ups), seconds.
    clip_offset: dict[str, float] = Field(default_factory=dict)


EMOTIONS: dict[str, Emotion] = {
    e.name: e
    for e in [
        Emotion(
            name="happy",
            label="Happy",
            kind="state",
            color="#f5b700",
            aliases=["cheerful", "joyful", "glad", "warm", "warmly", "smiling", "delighted", "pleased", "content"],
            clips=["cheerful1", "enthusiastic2"],
            hold=Pose(z=6, pitch=-6, roll=3, ant_r=-4, ant_l=4),
            idle=[Wave(channel="roll", amp=4, hz=0.7), Wave(channel="ants", amp=7, hz=1.8)],
        ),
        Emotion(
            name="excited",
            label="Excited",
            kind="state",
            color="#ff7a00",
            aliases=["ecstatic", "thrilled", "enthusiastic", "hyped", "energetic", "eager", "overjoyed", "elated"],
            clips=["enthusiastic1"],
            hold=Pose(z=12, pitch=-10, ant_r=0, ant_l=0),
            idle=[Wave(channel="z", amp=4, hz=2.4), Wave(channel="ants_mirror", amp=22, hz=4.0), Wave(channel="yaw", amp=5, hz=1.1), Wave(channel="body_yaw", amp=10, hz=1.4)],
        ),
        Emotion(
            name="laughs",
            label="Laughs",
            kind="event",
            color="#ffd23f",
            aliases=["laughing", "laugh", "giggles", "giggle", "giggling", "chuckles", "chuckle", "chuckling", "soft chuckle", "snickers", "cackles"],
            clips=["laughing1", "laughing2"],
            hold=Pose(z=4, pitch=-4, ant_r=-6, ant_l=6),
            idle=[Wave(channel="pitch", amp=5, hz=4.5), Wave(channel="ants", amp=10, hz=4.5)],
            clip_offset={"laughing1": 1.8},
        ),
        Emotion(
            name="sad",
            label="Sad",
            kind="state",
            color="#3d6bd6",
            aliases=["sadly", "sorrowful", "melancholy", "heartbroken", "upset", "gloomy", "disappointed", "crying", "tearful", "downcast"],
            clips=["downcast1", "sad2"],
            hold=Pose(x=-9, z=-6, pitch=14, yaw=8, roll=-4, body_yaw=6, ant_r=-145, ant_l=145),
            idle=[Wave(channel="pitch", amp=1.5, hz=0.25), Wave(channel="ants", amp=5, hz=0.3)],
            clip_offset={"downcast1": 2.0, "sad2": 3.0},
        ),
        Emotion(
            name="sighs",
            label="Sighs",
            kind="event",
            color="#7d8597",
            aliases=["sigh", "sighing", "exhales", "exhale", "exasperated", "weary", "tired", "resigned"],
            keyframes=[
                Keyframe(t=0.0, pose=Pose(z=2, pitch=0, ant_r=-15, ant_l=15)),
                Keyframe(t=0.5, pose=Pose(x=-3, z=10, pitch=-8, ant_r=-5, ant_l=5)),  # inhale: rise, look up
                Keyframe(t=2.0, pose=Pose(x=-6, z=-5, pitch=13, roll=-3, ant_r=-115, ant_l=115)),  # long exhale
            ],
            hold=Pose(x=-6, z=-5, pitch=13, roll=-3, ant_r=-115, ant_l=115),
            idle=[Wave(channel="z", amp=1.5, hz=0.25), Wave(channel="ants", amp=4, hz=0.25)],
        ),
        Emotion(
            name="angry",
            label="Angry",
            kind="state",
            color="#e63946",
            aliases=["angrily", "furious", "annoyed", "irritated", "mad", "frustrated", "outraged", "shouting", "yelling", "grumpy"],
            clips=["irritated1", "furious1"],
            hold=Pose(z=2, pitch=8, x=-2, ant_r=-40, ant_l=40),
            idle=[Wave(channel="yaw", amp=2, hz=3.2), Wave(channel="ants", amp=4, hz=7.0)],
        ),
        Emotion(
            name="gasps",
            label="Gasps",
            kind="event",
            color="#00b4d8",
            aliases=["gasp", "gasping", "surprised", "shocked", "amazed", "astonished", "stunned", "wow"],
            clips=["surprised1", "amazed1"],
            hold=Pose(z=14, pitch=-14, x=-6, ant_r=0, ant_l=0),
            idle=[],
        ),
        Emotion(
            name="scared",
            label="Scared",
            kind="state",
            color="#7b2cbf",
            aliases=["afraid", "fearful", "frightened", "terrified", "nervous", "nervously", "anxious", "worried", "panicked"],
            clips=["fear1", "scared1"],
            hold=Pose(z=-6, x=-8, pitch=4, yaw=-18, roll=6, body_yaw=-14, ant_r=-3, ant_l=3),
            idle=[Wave(channel="ants", amp=7, hz=9.0), Wave(channel="yaw", amp=2, hz=7.0), Wave(channel="yaw", amp=10, hz=0.4)],
            clip_offset={"scared1": 0.4},
        ),
        Emotion(
            name="curious",
            label="Curious",
            kind="state",
            color="#2a9d8f",
            aliases=["curiously", "intrigued", "inquisitive", "wondering", "quietly curious", "interested", "puzzled", "thoughtful"],
            clips=["inquiring1", "inquiring2"],
            hold=Pose(x=-3, z=8, pitch=4, roll=14, yaw=10, ant_r=-35, ant_l=5),
            idle=[Wave(channel="roll", amp=3, hz=0.35), Wave(channel="ant_r", amp=8, hz=0.9)],
        ),
        Emotion(
            name="whispers",
            label="Whispers",
            kind="state",
            color="#9a8c98",
            aliases=["whisper", "whispering", "quietly", "softly", "hushed", "under his breath", "under her breath", "secretive", "conspiratorial"],
            clips=[],
            # the whole body turns with the head, and the head stays back and up, so it clears the torso rim
            hold=Pose(x=-1, z=8, pitch=10, yaw=26, roll=12, body_yaw=22, ant_r=-150, ant_l=25),
            idle=[Wave(channel="pitch", amp=1.2, hz=0.5), Wave(channel="yaw", amp=1.5, hz=0.3)],
        ),
    ]
}

NEUTRAL = Pose()


def load_custom(path: Path) -> list[str]:
    """Add or replace emotions from a JSON file (one Emotion object or a list); returns their names."""
    raw = json.loads(Path(path).read_text())
    added = []
    for item in raw if isinstance(raw, list) else [raw]:
        emotion = Emotion.model_validate(item)
        EMOTIONS[emotion.name] = emotion
        added.append(emotion.name)
    return added
