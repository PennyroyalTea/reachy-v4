# Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `cannot resolve reachy-mini.local` | mDNS is blocked on this network, or the robot is on another network. Find the robot's IP in the Reachy Mini app or the router, then pass `--robot <ip>`. |
| "No route to host" on macOS, but the router answers | The terminal app has no Local Network permission. Turn it on in System Settings > Privacy & Security > Local Network, then restart the terminal. |
| Both devices are on Wi-Fi but cannot see each other | The network isolates clients, as hotel and conference Wi-Fi often does. Use a phone hotspot for both. |
| `robot daemon is stopped` | Start the robot software from the Reachy Mini app, or restart the robot. |
| The robot does not move, and there are no errors | Another app on the robot has the motors. Stop it in the Reachy Mini app. |
| `ELEVENLABS_API_KEY is not set` | Export the key in the shell that runs the command, or use the ElevenLabs MCP and `perform` instead (see SKILL.md). `demo` needs no key. |
| `text to speech failed (401)` | The key is wrong or lacks text to speech permission. |
| `forced alignment failed` | The key lacks forced alignment permission. Use `--words` with a take saved by `say`, or the whisper extra. |
| An emotion "may feel rushed" | Its tag is less than 2.5 seconds before the next one. Give it a longer sentence, or drop a tag. |
| The first run is slow | It downloads the Pollen library and builds the collision model, about a minute. Later runs are fast. |
| The head still touches the body | Report which emotion and which moment. Run `reachy-v4 check-emotions`. For a custom emotion, move `x` back or `z` up. |
| `local alignment needs faster-whisper` | Run `perform` with the `whisper` extra: `uv run --project engine --extra whisper reachy-v4 perform ...`. |
| An MCP audio link fails to download | The link has expired, after about 2 hours. Poll the run status again for a fresh link, or generate again. |
| `the simulator needs MuJoCo` | Run `sim` with the `sim` extra: `uv run --project engine --extra sim reachy-v4 sim`. |
| The simulator window opens but the tool cannot connect | Wait until `http://127.0.0.1:8000/api/daemon/status` answers, then pass `--robot 127.0.0.1`. Close any other Reachy Mini software on the computer that uses port 8000. |
| No sound from the simulator | The tool plays the voice with `afplay` on macOS, or `ffplay` or `mpg123` on Linux. Install one of them. |
