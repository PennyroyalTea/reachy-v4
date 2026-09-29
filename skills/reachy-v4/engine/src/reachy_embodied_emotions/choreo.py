"""Turn timed emotion cues into one 50 Hz motion timeline for the daemon.

Layers, bottom to top:
1. breathing neutral pose before the first cue
2. one segment per cue: a Pollen clip for the onset gesture, then the emotion's
   hold pose with its idle motif; event emotions (laugh, gasp, sigh) keep the
   body when they have their own sentence, and hand back to the previous mood
   when the next tag follows closely
3. smoothstep crossfades between segments
4. speech wobble from the audio loudness, plus a short accent on every stressed
   syllable (jabs when angry, bounces when excited, bobs on each laugh burst)
5. clamp to joint ranges, pull unreachable poses toward neutral, lift the head
   wherever it would hit the torso, rate limit
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation as R

from . import speech
from .align import Cue
from .collision import make_reachable, make_safe, reachable, real_clearance
from .emotions import EMOTIONS, NEUTRAL, Emotion, Pose, Wave

DT = 0.02
CHANNELS = ["x", "y", "z", "roll", "pitch", "yaw", "ant_r", "ant_l", "body_yaw"]
IDX = {c: i for i, c in enumerate(CHANNELS)}
NEUTRAL_VEC = np.array([getattr(NEUTRAL, c) for c in CHANNELS])

LIMITS = {
    "x": (-15, 15),
    "y": (-15, 15),
    "z": (-20, 25),
    "roll": (-30, 30),
    "pitch": (-30, 30),
    "yaw": (-60, 60),
    "ant_r": (-170, 30),
    "ant_l": (-30, 170),
    "body_yaw": (-45, 45),
}
LO = np.array([LIMITS[c][0] for c in CHANNELS])
HI = np.array([LIMITS[c][1] for c in CHANNELS])

# per-channel speed caps (mm/s or deg/s), below what the motors can physically follow
MAX_SPEED = np.array([120, 120, 120, 220, 220, 260, 600, 600, 120])

FADE_IN = {"angry": 0.15, "gasps": 0.12, "scared": 0.15, "excited": 0.2}
DEFAULT_FADE = 0.3
EVENT_RETURN = 0.5  # seconds to blend from an event gesture back to the running mood
EVENT_OWNS_SPAN = 2.5  # seconds to the next tag from which an event keeps the body instead of handing back
EVENT_IDLE_SCALE = 0.4  # an event's idle motif (laugh bob, gasp) is calmer while it is held under speech
CLIP_TAIL_BLEND = 0.6  # last part of a clip blends into the hold pose


def _vec(p: Pose) -> np.ndarray:
    return np.array([getattr(p, c) for c in CHANNELS], dtype=float)


def _smooth(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3 - 2 * u)


@lru_cache(maxsize=1)
def _library() -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download("pollen-robotics/reachy-mini-emotions-library", repo_type="dataset"))


@lru_cache(maxsize=None)
def load_clip(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (times starting at 0, poses [n, 9]) for a Pollen emotion move."""
    move = json.loads((_library() / f"{name}.json").read_text())
    t = np.array(move["time"], dtype=float)
    frames = move["set_target_data"]
    head = np.array([f["head"] for f in frames], dtype=float)
    rpy = R.from_matrix(head[:, :3, :3]).as_euler("xyz", degrees=True)
    xyz = head[:, :3, 3] * 1000
    ants = np.degrees(np.array([f["antennas"] for f in frames], dtype=float))
    body = np.degrees(np.array([f.get("body_yaw", 0.0) for f in frames], dtype=float))
    return t - t[0], np.column_stack([xyz, rpy, ants, body])


def idle(waves: list[Wave], t: np.ndarray) -> np.ndarray:
    out = np.zeros((len(t), len(CHANNELS)))
    for w in waves:
        s = w.amp * np.sin(2 * np.pi * w.hz * t + w.phase)
        if w.channel == "ants":  # both antennas swing outward together
            out[:, IDX["ant_r"]] -= s
            out[:, IDX["ant_l"]] += s
        elif w.channel == "ants_mirror":  # alternate, like flapping
            out[:, IDX["ant_r"]] += s
            out[:, IDX["ant_l"]] += s
        else:
            out[:, IDX[w.channel]] += s
    return out


def mood_track(emotion: Emotion | None, t: np.ndarray, intensity: float = 1.0, idle_scale: float = 1.0) -> np.ndarray:
    """The pose the body settles into for a mood (or breathing neutral)."""
    if emotion is None:
        breath = [Wave(channel="z", amp=1.5, hz=0.25), Wave(channel="ants", amp=3, hz=0.25), Wave(channel="pitch", amp=0.8, hz=0.25, phase=1.0)]
        return NEUTRAL_VEC + idle(breath, t)
    hold = NEUTRAL_VEC + intensity * (_vec(emotion.hold) - NEUTRAL_VEC)
    return hold + idle_scale * min(intensity, 1.0) * idle(emotion.idle, t)


def owns_span(emotion: Emotion, span: float) -> bool:
    """An event (laugh, gasp, sigh) with its own sentence keeps the body until the next tag."""
    return emotion.kind == "state" or span >= EVENT_OWNS_SPAN


class Choreographer:
    def __init__(self) -> None:
        self._variant: dict[str, int] = {}
        self.safety: dict = {}

    def _pick_clip(self, emotion: Emotion, span: float) -> str | None:
        if not emotion.clips:
            return None
        n = self._variant.get(emotion.name, 0)
        self._variant[emotion.name] = n + 1
        # prefer the clip that fits the span best, rotate between equally good ones
        scored = sorted(
            emotion.clips,
            key=lambda c: abs((load_clip(c)[0][-1] - emotion.clip_offset.get(c, 0.0)) - span),
        )
        return scored[n % min(2, len(scored))] if span > 1.2 else scored[0]

    def segment(self, cue: Cue, t: np.ndarray, start: float, end: float, prev_mood: tuple[Emotion | None, float]) -> np.ndarray:
        """Pose track for one cue, defined over the whole timeline t (valid from start on)."""
        emotion = EMOTIONS[cue.emotion]
        k = cue.intensity
        u = t - start
        span = max(end - start, 0.3)

        keeps = owns_span(emotion, span)
        if keeps:
            settle = mood_track(emotion, t, k, idle_scale=1.0 if emotion.kind == "state" else EVENT_IDLE_SCALE)
        else:
            settle = mood_track(prev_mood[0], t, prev_mood[1])

        if emotion.keyframes:
            kt = np.array([kf.t for kf in emotion.keyframes])
            kp = np.array([_vec(kf.pose) for kf in emotion.keyframes])
            gesture = keyframe_track(kt, kp, u)
            gesture = NEUTRAL_VEC + k * (gesture - NEUTRAL_VEC)
            w = _smooth((u - kt[-1]) / CLIP_TAIL_BLEND)[:, None]
            return (1 - w) * gesture + w * settle

        clip = self._pick_clip(emotion, span)
        if clip is None:
            return settle

        ct, cp = load_clip(clip)
        offset = emotion.clip_offset.get(clip, 0.0)
        clip_len = ct[-1] - offset
        rate = float(np.clip(clip_len / span, 1.0, 1.5)) if keeps else 1.0
        play_len = clip_len / rate
        if not keeps:
            # a gesture should cover the non-verbal sound, but not the whole next sentence
            play_len = min(play_len, max(cue.gap_end - start + 0.8, 1.2))

        tau = np.clip(offset + u * rate, 0, ct[-1])
        gesture = np.column_stack([np.interp(tau, ct, cp[:, j]) for j in range(len(CHANNELS))])
        gesture = NEUTRAL_VEC + k * (gesture - NEUTRAL_VEC)

        blend_len = CLIP_TAIL_BLEND if keeps else EVENT_RETURN
        w = _smooth((u - (play_len - blend_len)) / blend_len)[:, None]
        return (1 - w) * gesture + w * settle

    def build(
        self, cues: list[Cue], duration: float, tail: float = 1.8, audio: Path | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        total = duration + tail
        t = np.arange(0.0, total, DT)
        pose = mood_track(None, t)

        mood: tuple[Emotion | None, float] = (None, 1.0)
        cues = sorted(cues, key=lambda c: c.t)
        for i, cue in enumerate(cues):
            end = cues[i + 1].t if i + 1 < len(cues) else duration
            track = self.segment(cue, t, cue.t, end, mood)
            fade = FADE_IN.get(cue.emotion, DEFAULT_FADE)
            w = _smooth((t - cue.t) / fade)[:, None]
            pose = (1 - w) * pose + w * track
            if owns_span(EMOTIONS[cue.emotion], end - cue.t):
                mood = (EMOTIONS[cue.emotion], cue.intensity)

        # settle back to neutral once the audio ends, then a small nod to the viewer
        w = _smooth((t - duration) / 0.6)[:, None]
        pose = (1 - w) * pose + w * mood_track(None, t)
        pose = pose + keyframe_track(END_NOD[0] + duration, END_NOD[1], t) - NEUTRAL_VEC

        if audio is not None:
            active = active_emotions(cues, t)
            mult, tempo = speech_style(active)
            pose = pose + speech.wobble(t, speech.speech_gain(str(audio), len(t)), mult, tempo, CHANNELS)
            at = lambda t0: active[min(int(t0 / DT), len(active) - 1)]  # noqa: E731
            pose = pose + speech.accents(t, speech.onsets(str(audio)), at, IDX, len(CHANNELS))

        pose = np.clip(pose, LO, HI)
        # the daemon refuses head yaw more than 65 deg away from body yaw
        body = pose[:, IDX["body_yaw"]]
        pose[:, IDX["yaw"]] = np.clip(pose[:, IDX["yaw"]], body - 60, body + 60)
        pose, reach = make_reachable(pose, IDX, NEUTRAL_VEC, DT)
        pose, self.safety = make_safe(pose, IDX, NEUTRAL_VEC, DT)
        pose = rate_limit(pose)
        self.safety.update(reach)
        self.safety["final_min_clearance_mm"] = float(real_clearance(pose, IDX).min() * 1000)
        self.safety["final_unreachable_frames"] = int((~reachable(pose, IDX, NEUTRAL_VEC, stretch=1.0)).sum())
        return t, pose


def keyframe_track(kt: np.ndarray, kp: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Ease between keyframe poses (smoothstep per segment); hold the ends."""
    out = np.tile(kp[0], (len(u), 1)).astype(float)
    for (t0, p0), (t1, p1) in zip(zip(kt, kp), zip(kt[1:], kp[1:])):
        w = _smooth((u - t0) / max(t1 - t0, 1e-6))[:, None]
        seg = (u >= t0)[:, None]
        out = np.where(seg, (1 - w) * p0 + w * p1, out)
    return out


def _nod() -> tuple[np.ndarray, np.ndarray]:
    n = NEUTRAL_VEC.copy()
    bow = n.copy()
    bow[IDX["pitch"]] += 12
    bow[IDX["z"]] -= 2
    bow[IDX["ant_r"]] -= 20
    bow[IDX["ant_l"]] += 20
    return np.array([0.35, 0.8, 1.05, 1.6]), np.array([n, bow, bow, n])


def active_emotions(cues: list[Cue], t: np.ndarray) -> list[str | None]:
    """Which emotion owns each frame (held moods, with short events laid over them)."""
    active: list[str | None] = [None] * len(t)
    nxt = [c.t for c in cues[1:]] + [t[-1] + 1]
    holders = [owns_span(EMOTIONS[c.emotion], n - c.t) for c, n in zip(cues, nxt)]
    for i, cue in enumerate(cues):
        if not holders[i]:
            continue
        end = next((c.t for c, h in zip(cues[i + 1 :], holders[i + 1 :]) if h), t[-1] + 1)
        for j in np.flatnonzero((t >= cue.t) & (t < end)):
            active[j] = cue.emotion
    for cue, h in zip(cues, holders):  # short events override the mood while their gesture plays
        if not h:
            for j in np.flatnonzero((t >= cue.t) & (t < cue.gap_end + 0.8)):
                active[j] = cue.emotion
    return active


def speech_style(active: list[str | None]) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame wobble (gain, tempo) multipliers from whichever emotion is active."""
    mult = np.array([speech.STYLE.get(a, speech.STYLE[None])[0] for a in active])
    tempo = np.array([speech.STYLE.get(a, speech.STYLE[None])[1] for a in active])
    sigma = 0.15 / DT
    return gaussian_filter1d(mult, sigma), gaussian_filter1d(tempo, sigma)


def rate_limit(pose: np.ndarray) -> np.ndarray:
    out = pose.copy()
    step = MAX_SPEED * DT
    for i in range(1, len(out)):
        out[i] = out[i - 1] + np.clip(pose[i] - out[i - 1], -step, step)
    return out


def to_move(t: np.ndarray, pose: np.ndarray, description: str = "") -> dict:
    """Pack a pose track as the RecordedMove JSON the daemon plays."""
    rot = R.from_euler("xyz", pose[:, [IDX["roll"], IDX["pitch"], IDX["yaw"]]], degrees=True).as_matrix()
    head = np.zeros((len(t), 4, 4))
    head[:, :3, :3] = rot
    head[:, :3, 3] = pose[:, [IDX["x"], IDX["y"], IDX["z"]]] / 1000
    head[:, 3, 3] = 1.0
    ants = np.radians(pose[:, [IDX["ant_r"], IDX["ant_l"]]])
    body = np.radians(pose[:, IDX["body_yaw"]])
    return {
        "description": description,
        "time": np.round(t, 4).tolist(),
        "set_target_data": [
            {"head": np.round(h, 6).tolist(), "antennas": np.round(a, 5).tolist(), "body_yaw": round(float(b), 5)}
            for h, a, b in zip(head, ants, body)
        ],
    }


END_NOD = _nod()  # a small bow after the last word: pitch down, antennas dip
