"""Speech-driven head motion, computed offline from the audio file.

Follows the SDK's head wobbler (reachy_mini motion/speech_tapper.py): loudness
in 20 ms frames drives a gain that scales a set of slow sines. Doing it here
instead of in the daemon means the collision check sees the exact final
trajectory, and each emotion can speak with its own body (big bouncy speech
when excited, barely moving when sad or whispering).
"""

import numpy as np
import soundfile as sf

FRAME = 0.02
# channel: (amplitude in mm or deg, frequency Hz)
SINES = {  # channel: (amplitude in mm or deg, frequency Hz, phase)
    "pitch": (4.5, 2.2, 0.0),
    "yaw": (7.5, 0.6, 1.3),
    "roll": (2.25, 1.3, 2.1),
    "x": (4.5, 0.35, 0.7),
    "y": (3.75, 0.45, 3.4),
    "z": (2.25, 0.25, 5.0),
}
SCALE = 1.5

# per-emotion wobble: (gain multiplier, tempo multiplier)
STYLE = {  # the sway is kept calm so the syllable accents read as beats against it
    None: (0.8, 1.0),
    "happy": (0.9, 1.1),
    "excited": (1.2, 1.35),
    "laughs": (0.8, 1.4),
    "sad": (0.45, 0.7),
    "sighs": (0.5, 0.7),
    "angry": (0.7, 1.3),
    "gasps": (0.9, 1.1),
    "scared": (0.5, 1.5),
    "curious": (0.6, 0.9),
    "whispers": (0.3, 0.8),
}


def _smooth(x: np.ndarray, attack: float, release: float) -> np.ndarray:
    a_up, a_down = 1 - np.exp(-FRAME / attack), 1 - np.exp(-FRAME / release)
    out = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += (a_up if v > acc else a_down) * (v - acc)
        out[i] = acc
    return out


def speech_gain(audio_path: str, n_frames: int) -> np.ndarray:
    """0..1 speaking gain per 20 ms frame, zero-padded to n_frames."""
    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    hop = int(sr * FRAME)
    n = min(n_frames, len(mono) // hop)
    frames = mono[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)

    # voice activity with hysteresis: on above -35 dB, off below -45 dB
    active = np.zeros(n, dtype=bool)
    on = False
    for i, v in enumerate(db):
        on = v > -35 if not on else v > -45
        active[i] = on
    gate = _smooth(active.astype(float), attack=0.04, release=0.25)

    level = np.clip((db + 46) / (46 - 18), 0, 1) ** 0.9
    gain = _smooth(level, attack=0.05, release=0.25) * gate
    out = np.zeros(n_frames)
    out[:n] = gain
    return out


def wobble(t: np.ndarray, gain: np.ndarray, mult: np.ndarray, tempo: np.ndarray, channels: list[str]) -> np.ndarray:
    """Offsets [n, len(channels)]; mult/tempo are per-frame emotion style factors."""
    phase_t = np.cumsum(tempo) * FRAME  # tempo changes bend time instead of jumping phase
    out = np.zeros((len(t), len(channels)))
    for ch, (amp, hz, phase) in SINES.items():
        out[:, channels.index(ch)] = SCALE * amp * gain * mult * np.sin(2 * np.pi * hz * phase_t + phase)
    return out


# Accents: a short pulse on each stressed syllable, shaped by the emotion of the moment,
# so the body hits the beats of the voice instead of only swaying with its loudness.
# channel -> amplitude (mm or deg); a leading "~" flips the sign on every other accent (shakes, twitches).
# "ants" moves both antennas outward together.
ACCENTS: dict[str | None, dict[str, float]] = {
    None: {"pitch": 3.5},
    "happy": {"z": 5.0, "~roll": 5.0, "ants": 10.0},
    "excited": {"z": 8.0, "pitch": -5.0, "ants": 20.0, "~roll": 5.0, "~body_yaw": 6.0},
    "laughs": {"pitch": -11.0, "z": 5.0, "~ants": 22.0, "~roll": 6.0},
    "sad": {"pitch": 3.0},
    "sighs": {"pitch": 2.0},
    "angry": {"~yaw": 11.0, "pitch": 5.0, "~ants": 12.0},
    "gasps": {"pitch": -4.0, "z": 3.0},
    "scared": {"x": -5.0, "~ants": 12.0, "~yaw": 5.0},
    "curious": {"pitch": 4.5, "~roll": 3.5},
    "whispers": {"pitch": 2.0},
}
ACCENT_RISE = 0.08  # seconds from onset to the peak of each pulse
ONSET_HOP = 0.01


def onsets(audio_path: str, min_gap: float = 0.18, floor: float = 0.3) -> list[tuple[float, float]]:
    """(time, strength 0..1) for syllable onsets strong enough to carry an accent."""
    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    hop = int(sr * ONSET_HOP)
    n = len(mono) // hop
    frames = mono[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames**2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    energy = np.log(rms + 1e-4)
    flux = np.maximum(np.diff(energy, prepend=energy[0]), 0.0)
    flux = np.convolve(flux, np.ones(3) / 3, mode="same")
    peak = (flux > np.roll(flux, 1)) & (flux >= np.roll(flux, -1)) & (db > -38)
    idx = np.flatnonzero(peak)
    if not len(idx):
        return []
    scale = np.percentile(flux[idx], 95) or 1.0
    strength = np.clip(flux[idx] / scale, 0, 1)
    keep: list[int] = []
    for i in idx[np.argsort(-strength)]:  # strongest first, then enforce spacing
        if flux[i] / scale >= floor and all(abs(i - j) * ONSET_HOP >= min_gap for j in keep):
            keep.append(i)
    return [(i * ONSET_HOP, float(min(flux[i] / scale, 1.0))) for i in sorted(keep)]


def accents(t: np.ndarray, hits: list[tuple[float, float]], emotion_at, idx: dict[str, int], n_channels: int) -> np.ndarray:
    """Offsets [n, channels]: one alpha-shaped pulse per onset, styled by emotion_at(time)."""
    out = np.zeros((len(t), n_channels))
    for k, (t0, strength) in enumerate(hits):
        style = ACCENTS.get(emotion_at(t0), ACCENTS[None])
        u = t - t0
        live = (u >= 0) & (u < 1.0)
        pulse = np.zeros(len(t))
        pulse[live] = (u[live] / ACCENT_RISE) * np.exp(1 - u[live] / ACCENT_RISE)
        for ch, amp in style.items():
            sign = (-1) ** k if ch.startswith("~") else 1
            name = ch.lstrip("~")
            a = sign * amp * strength * pulse
            if name == "ants":
                out[:, idx["ant_r"]] -= a
                out[:, idx["ant_l"]] += a
            else:
                out[:, idx[name]] += a
    return out
