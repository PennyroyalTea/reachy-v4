"""reachy-v4: make Reachy Mini act out Eleven v4 speech.

    reachy-v4 check                          robot, network and API key
    reachy-v4 demo                           the cake scene from the demo video (no API key needed)
    reachy-v4 sim                            a simulated robot in a 3D window, for trying without one
    reachy-v4 emotions                       tags the robot understands
    reachy-v4 say "[curious] Hmm. What's this?"
    reachy-v4 perform --audio take.mp3 --text "[sad] Oh. It's gone."
    reachy-v4 preview gasps
    reachy-v4 check-emotions my_emotions.json

Add --dry-run to plan without moving the robot.
"""

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import numpy as np

from . import tts
from .align import Cue, Word, place_cues
from .choreo import IDX, NEUTRAL_VEC, Choreographer, load_clip, mood_track, owns_span, to_move
from .collision import reachable, real_clearance
from .emotions import EMOTIONS, load_custom
from .perform import Plan, audio_duration, perform
from .robot import Robot
from .tags import parse

DEFAULT_ROBOT = os.environ.get("REACHY_HOST", "reachy-mini.local")
OUT_DIR = Path(os.environ.get("REACHY_V4_OUT", Path.home() / "reachy-v4"))
DEMO = Path(__file__).parent / "demo" / "cake"  # Eleven v4 take (Zibby voice) with its word timings


def say_line(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def resolve(host: str) -> str:
    """mDNS names are slow to resolve on every request; resolve once."""
    try:
        return socket.gethostbyname(host)
    except OSError as e:
        raise SystemExit(f"cannot resolve {host}: {e}. Pass --robot <ip> (find it in the Reachy Mini app or your router).") from e


def build_plan(text: str, audio: Path, words: list[Word]) -> Plan:
    script = parse(text)
    ignored = [t.raw for t in script.tags if t.emotion is None]
    if ignored:
        say_line(f"voice only, no motion for: {', '.join(f'[{r}]' for r in ignored)}")
    duration = audio_duration(audio)
    cues = place_cues(script, words, duration)
    choreo = Choreographer()
    t, pose = choreo.build(cues, duration, audio=audio)
    return Plan(text=text, duration=duration, words=words, cues=cues, safety=choreo.safety, move=to_move(t, pose, text[:200]))


def show_plan(p: Plan) -> None:
    ends = [c.t for c in p.cues[1:]] + [p.duration]
    say_line(f"{p.duration:.1f} s of speech, {len(p.cues)} emotions")
    for c, end in zip(p.cues, ends):
        kind = "held" if owns_span(EMOTIONS[c.emotion], end - c.t) else "quick"
        warn = "  <- under 2.5 s, may feel rushed" if end - c.t < 2.5 else ""
        say_line(f"  {c.t:6.2f}s  {c.emotion:10} {kind:5} [{c.raw}]{warn}")
    s = p.safety
    say_line(
        f"safety: {s.get('unsafe_frames', 0)} frames eased away from the torso, "
        f"{s.get('unreachable_frames', 0)} pulled into reach; closest approach {s.get('final_min_clearance_mm', 0):.1f} mm"
    )


async def play(host: str, p: Plan, audio: Path) -> None:
    robot = Robot(resolve(host))
    try:
        status = await robot.status()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"robot at {host} did not answer on port 8000 ({type(e).__name__}). Run: reachy-v4 check") from e
    if status.get("state") != "running":
        raise SystemExit(f"robot daemon is {status.get('state')}, not running")
    say_line(f"performing on {host} (daemon {status.get('version')})")
    on_event, players = None, []
    if status.get("simulation_enabled") or status.get("mockup_sim_enabled"):
        player = local_player(audio)
        say_line("simulator: playing the audio on this computer" if player else "simulator: no audio player found, motion only")
        if player:
            def on_event(msg: dict) -> None:
                if msg.get("started"):  # sent before the 0.5 s approach to the first pose; the voice leads by 60 ms
                    asyncio.get_running_loop().call_later(0.44, lambda: players.append(subprocess.Popen(player)))
    t0 = time.monotonic()
    result = await perform(robot, p, audio, on_event=on_event)
    await robot.aclose()
    for proc in players:
        if proc.poll() is None and "finished" not in result:
            proc.terminate()
    if "finished" not in result:
        raise SystemExit(f"robot reported: {result}")
    say_line(f"done in {time.monotonic() - t0:.1f} s")


def local_player(audio: Path) -> list[str] | None:
    for cmd in (["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"]):
        if shutil.which(cmd[0]):
            return [*cmd, str(audio)]
    return None


def save_take(text: str, audio_bytes: bytes, words: list[Word]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / time.strftime("take-%Y%m%d-%H%M%S")
    stem.with_suffix(".mp3").write_bytes(audio_bytes)
    stem.with_suffix(".json").write_text(json.dumps({"text": text, "words": [w.model_dump() for w in words]}, indent=1))
    return stem.with_suffix(".mp3")


def cmd_say(a: argparse.Namespace) -> None:
    say_line(f"generating speech with {a.model} ...")
    speech = tts.synthesize(a.text, voice_id=a.voice, model_id=a.model)
    audio = save_take(a.text, speech.audio, speech.words)
    say_line(f"saved {audio}")
    p = build_plan(a.text, audio, speech.words)
    show_plan(p)
    if not a.dry_run:
        asyncio.run(play(a.robot, p, audio))


def fetch(url: str) -> Path:
    """Download audio from a link, for example a speech result from the ElevenLabs MCP (those links expire)."""
    import httpx

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = httpx.get(url, follow_redirects=True, timeout=60)
    r.raise_for_status()
    ext = ".wav" if "wav" in r.headers.get("content-type", "") else ".mp3"
    path = (OUT_DIR / time.strftime("take-%Y%m%d-%H%M%S")).with_suffix(ext)
    path.write_bytes(r.content)
    say_line(f"saved {path}")
    return path


def cmd_demo(a: argparse.Namespace) -> None:
    take = json.loads(DEMO.with_suffix(".json").read_text())
    say_line(take["text"])
    p = build_plan(take["text"], DEMO.with_suffix(".mp3"), [Word(**w) for w in take["words"]])
    show_plan(p)
    if not a.dry_run:
        asyncio.run(play(a.robot, p, DEMO.with_suffix(".mp3")))


def cmd_sim(a: argparse.Namespace) -> None:
    """Run Pollen's MuJoCo simulator as a local robot: then use --robot localhost in another terminal."""
    try:
        import mujoco  # noqa: F401
    except ImportError:
        raise SystemExit("the simulator needs MuJoCo: run it as 'uv run --extra sim reachy-v4 sim'") from None
    daemon = ["-m", "reachy_mini.daemon.app.main", "--sim", "--no-media", "--fastapi-host", "127.0.0.1"]
    if sys.platform == "darwin":
        # the 3D window needs mjpython on macOS, which looks for libpython inside the virtual environment
        lib = Path(sysconfig.get_config_var("LDLIBRARY") or f"libpython{sys.version_info.major}.{sys.version_info.minor}.dylib")
        link, target = Path(sys.prefix) / "lib" / lib.name, Path(sysconfig.get_config_var("LIBDIR")) / lib.name
        if not link.exists() and target.exists():
            link.symlink_to(target)
        cmd = [str(Path(sys.prefix) / "bin" / "mjpython"), *daemon]
    else:
        cmd = [sys.executable, *daemon]
    say_line("starting the simulated robot; it answers on localhost once the 3D window opens. Ctrl+C stops it.")
    raise SystemExit(subprocess.call(cmd))


def cmd_perform(a: argparse.Namespace) -> None:
    audio = fetch(a.audio) if a.audio.startswith(("http://", "https://")) else Path(a.audio)
    text = Path(a.text[1:]).read_text().strip() if a.text.startswith("@") else a.text
    if a.words:
        words = [Word(**w) for w in json.loads(Path(a.words).read_text())["words"]]
    elif os.environ.get("ELEVENLABS_API_KEY"):
        say_line("aligning the transcript with ElevenLabs forced alignment ...")
        words = tts.force_align(audio.read_bytes(), text)
    else:
        say_line("no ELEVENLABS_API_KEY: aligning locally with faster-whisper ...")
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError:
            raise SystemExit("local alignment needs faster-whisper: run the command with 'uv run --extra whisper ...', "
                             "or set ELEVENLABS_API_KEY to use ElevenLabs forced alignment") from None
        from .align import whisper_words

        words = whisper_words(audio)
    p = build_plan(text, audio, words)
    show_plan(p)
    if not a.dry_run:
        asyncio.run(play(a.robot, p, audio))


def cmd_preview(a: argparse.Namespace) -> None:
    if a.emotion not in EMOTIONS:
        raise SystemExit(f"unknown emotion {a.emotion!r}; see: reachy-v4 emotions")
    event = EMOTIONS[a.emotion].kind == "event"
    cue = Cue(emotion=a.emotion, kind=EMOTIONS[a.emotion].kind, intensity=a.intensity, raw=a.emotion, t=0.3,
              gap_start=0.3, gap_end=1.3 if event else 0.3)
    choreo = Choreographer()
    t, pose = choreo.build([cue], 4.0)
    say_line(f"{a.emotion}: closest approach {choreo.safety['final_min_clearance_mm']:.1f} mm")
    if a.dry_run:
        return

    async def go() -> None:
        robot = Robot(resolve(a.robot))
        await robot.set_motor_mode("enabled")
        await robot.set_wobbling(False)
        await robot.play_timeline(to_move(t, pose, a.emotion), initial_goto_duration=0.5)
        await robot.aclose()

    asyncio.run(go())


def cmd_emotions(a: argparse.Namespace) -> None:
    for e in EMOTIONS.values():
        print(f"[{e.name}]  {e.kind:5}  also: {', '.join(e.aliases[:8])}")
    print("\nIntensity: 'slightly'/'a bit' tone it down, 'very'/'extremely' push it further, for example [slightly annoyed].")
    print("Tags like [pause] or [light rain] shape the voice only; the robot keeps its current mood.")


def cmd_check_emotions(a: argparse.Namespace) -> None:
    """Validate emotions (built-in or from a JSON file) against clips, collisions and reach."""
    names = load_custom(Path(a.file)) if a.file else list(EMOTIONS)
    t = np.arange(0, 4, 0.02)
    ok = True
    for name in names:
        e = EMOTIONS[name]
        problems = []
        for clip in e.clips:
            try:
                load_clip(clip)
            except FileNotFoundError:
                problems.append(f"unknown Pollen clip {clip!r}")
        track = mood_track(e, t)
        clear = real_clearance(track, IDX).min() * 1000
        reach = reachable(track, IDX, NEUTRAL_VEC, stretch=1.0).all()
        if clear < 10:
            problems.append(f"hold pose comes within {clear:.1f} mm of the torso (aim for 12+; move x back or z up)")
        if not reach:
            problems.append("hold pose is outside the head's reach; make it smaller")
        ok &= not problems
        print(f"{'ok ' if not problems else 'FIX'} [{name}] hold clearance {clear:.1f} mm" + "".join(f"\n      - {p}" for p in problems))
    if not ok:
        raise SystemExit(1)


def cmd_check(a: argparse.Namespace) -> None:
    import httpx

    print(f"ELEVENLABS_API_KEY: {'set' if os.environ.get('ELEVENLABS_API_KEY') else 'not set (needed for say; perform can fall back to faster-whisper)'}")
    try:
        ip = socket.gethostbyname(a.robot)
        print(f"robot name {a.robot}: {ip}")
    except OSError:
        print(f"robot name {a.robot}: does not resolve. Is the robot on the same Wi-Fi? Pass --robot <ip>.")
        raise SystemExit(1)
    try:
        s = httpx.get(f"http://{ip}:8000/api/daemon/status", timeout=4).json()
    except httpx.ConnectError as e:
        hint = ""
        if sys.platform == "darwin" and "No route to host" in str(e):
            hint = ("\n  macOS blocks this terminal from the local network. Open System Settings > Privacy & Security > "
                    "Local Network and turn it on for your terminal app, then restart the terminal.")
        print(f"daemon: cannot connect to {ip}:8000 ({e}){hint}")
        raise SystemExit(1)
    print(f"daemon: {s.get('state')}, version {s.get('version')}, wireless {s.get('wireless_version')}, "
          f"motors {s.get('backend_status', {}).get('motor_control_mode')}")
    print("ready" if s.get("state") == "running" else "daemon is not running: start it from the Reachy Mini app")


def main() -> None:
    ap = argparse.ArgumentParser(prog="reachy-v4", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emotions", metavar="JSON", action="append", default=[], help="extra emotions to load (repeatable)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def robot_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--robot", default=DEFAULT_ROBOT, help=f"robot host or IP (default {DEFAULT_ROBOT}, or $REACHY_HOST)")
        p.add_argument("--dry-run", action="store_true", help="plan and print, do not move the robot")

    p = sub.add_parser("say", help="speak tagged text with Eleven v4 and perform it")
    p.add_argument("text")
    p.add_argument("--voice", default=tts.DEFAULT_VOICE_ID, help="ElevenLabs voice id")
    p.add_argument("--model", default=tts.DEFAULT_MODEL, help="eleven_v4 or eleven_v4_turbo")
    robot_opts(p)
    p.set_defaults(fn=cmd_say)

    p = sub.add_parser("demo", help="perform the cake scene from the demo video")
    robot_opts(p)
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("sim", help="run a simulated robot in a 3D window (needs the sim extra)")
    p.set_defaults(fn=cmd_sim)

    p = sub.add_parser("perform", help="perform existing Eleven v4 audio with its tagged transcript")
    p.add_argument("--audio", required=True, help="audio file, or an https link to one")
    p.add_argument("--text", required=True, help="tagged transcript, or @file.txt")
    p.add_argument("--words", help="word timings JSON saved by 'say' (skips alignment)")
    robot_opts(p)
    p.set_defaults(fn=cmd_perform)

    p = sub.add_parser("preview", help="play one emotion's gesture without audio")
    p.add_argument("emotion")
    p.add_argument("--intensity", type=float, default=1.0)
    robot_opts(p)
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("emotions", help="list the tags the robot understands")
    p.set_defaults(fn=cmd_emotions)

    p = sub.add_parser("check-emotions", help="validate built-in or custom emotions")
    p.add_argument("file", nargs="?")
    p.set_defaults(fn=cmd_check_emotions)

    p = sub.add_parser("check", help="check the robot, network and API key")
    p.add_argument("--robot", default=DEFAULT_ROBOT)
    p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    for path in a.emotions or ([os.environ["REACHY_V4_EMOTIONS"]] if os.environ.get("REACHY_V4_EMOTIONS") else []):
        say_line(f"loaded emotions: {', '.join(load_custom(Path(path)))}")
    try:
        a.fn(a)
    except tts.ApiError as e:
        raise SystemExit(str(e)) from e
