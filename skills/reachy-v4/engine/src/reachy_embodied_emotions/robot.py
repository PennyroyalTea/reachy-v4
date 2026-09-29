"""Thin async client for the Reachy Mini daemon (REST + /ws/sdk WebSocket).

Plays a motion timeline and its audio as one uploaded move, so the daemon
runs both on its own clock and Wi-Fi jitter never desyncs them.
"""

import asyncio
import base64
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import websockets

CHUNK = 12 * 1024  # the JS SDK slices at 12 KB; the daemon caps chunks at 16 KB


class Robot:
    def __init__(self, host: str, port: int = 8000) -> None:
        self.base = f"http://{host}:{port}"
        self.ws_uri = f"ws://{host}:{port}/ws/sdk"
        self.http = httpx.AsyncClient(base_url=self.base, timeout=10)

    async def status(self) -> dict:
        return (await self.http.get("/api/daemon/status")).json()

    async def set_motor_mode(self, mode: str) -> None:
        (await self.http.post(f"/api/motors/set_mode/{mode}")).raise_for_status()

    async def set_wobbling(self, enabled: bool) -> None:
        path = "enable" if enabled else "disable"
        (await self.http.post(f"/api/media/wobbling/{path}")).raise_for_status()

    async def goto(
        self,
        head: dict | None = None,
        antennas: list[float] | None = None,
        body_yaw: float | None = None,
        duration: float = 1.0,
    ) -> None:
        body = {"duration": duration, "head_pose": head, "antennas": antennas, "body_yaw": body_yaw}
        (await self.http.post("/api/move/goto", json=body)).raise_for_status()

    async def play_timeline(
        self,
        move: dict,
        audio: bytes | None = None,
        audio_format: str = "wav",
        audio_lead_ms: float = 0.0,
        initial_goto_duration: float = 0.3,
        on_event: Callable[[dict], None] | None = None,
        on_state: Callable[[float, dict], None] | None = None,
    ) -> dict:
        """Upload a RecordedMove-shaped dict (+ optional audio) and play it.

        `on_event` sees every daemon event for this move (started, then the end).
        `on_state` gets (monotonic time, msg) for the 50 Hz head_pose / joint_positions stream.
        Returns the daemon's final event (finished / cancelled / error).
        """
        upload_id = str(uuid.uuid4())
        move_json = json.dumps(move, separators=(",", ":"))
        move_chunks = [move_json[i : i + CHUNK] for i in range(0, len(move_json), CHUNK)]
        duration = move["time"][-1] - move["time"][0]

        async with websockets.connect(self.ws_uri, max_size=None) as ws:
            send = lambda cmd: ws.send(json.dumps(cmd))  # noqa: E731
            await send(
                {
                    "type": "upload_move_start",
                    "upload_id": upload_id,
                    "total_chunks": len(move_chunks),
                    "description": move.get("description", ""),
                    "estimated_duration_s": duration,
                }
            )
            for i, chunk in enumerate(move_chunks):
                await send({"type": "upload_move_chunk", "upload_id": upload_id, "chunk_index": i, "chunk": chunk})
            await send({"type": "upload_move_finish", "upload_id": upload_id})

            if audio is not None:
                b64 = base64.b64encode(audio).decode()
                audio_chunks = [b64[i : i + CHUNK] for i in range(0, len(b64), CHUNK)]
                await send(
                    {
                        "type": "upload_audio_start",
                        "upload_id": upload_id,
                        "total_chunks": len(audio_chunks),
                        "encoding": f"{audio_format}-base64",
                    }
                )
                for i, chunk in enumerate(audio_chunks):
                    await send({"type": "upload_audio_chunk", "upload_id": upload_id, "chunk_index": i, "chunk": chunk})
                await send({"type": "upload_audio_finish", "upload_id": upload_id})

            await send(
                {
                    "type": "play_uploaded_move",
                    "upload_id": upload_id,
                    "play_frequency": 100.0,
                    "initial_goto_duration": initial_goto_duration,
                    "audio_lead_ms": audio_lead_ms,
                }
            )

            deadline = asyncio.get_running_loop().time() + duration + initial_goto_duration + 15
            while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if on_state is not None and msg.get("type") in ("head_pose", "joint_positions"):
                    on_state(asyncio.get_running_loop().time(), msg)
                    continue
                if msg.get("type") != "play_uploaded_move" or msg.get("upload_id") != upload_id:
                    continue
                if on_event is not None:
                    on_event(msg)
                if any(k in msg for k in ("finished", "cancelled", "error")):
                    return msg
            return {"error": "timed out waiting for the move to finish"}

    async def stop(self, timeout: float = 3.0) -> dict:
        """Interrupt whatever move is playing (and its audio); the daemon acks with `stopped`."""
        async with websockets.connect(self.ws_uri, max_size=None) as ws:
            await ws.send(json.dumps({"type": "stop_move"}))
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        msg = json.loads(await ws.recv())
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if msg.get("command") == "stop_move":
                        return msg

    async def aclose(self) -> None:
        await self.http.aclose()


def load_audio(path: Path) -> tuple[bytes, str]:
    return path.read_bytes(), path.suffix.lstrip(".")
