---
name: reachy-v4
description: Make a Reachy Mini robot act out Eleven v4 speech. Writes emotion audio tags ([curious], [laughs], [sad] and so on) into a script, generates the speech with ElevenLabs Eleven v4 (through the ElevenLabs MCP or an API key), and plays it on the robot with a matching body performance of head, antennas and body, timed to each tag and kept clear of the robot's own body. Also plays a ready-made demo scene with no API key, and runs a 3D simulator for people without a robot. Use when someone wants their Reachy Mini to say something with emotion, to perform an existing Eleven v4 generation, to try the demo, or to add a new emotion. Triggers include "make my robot say", "Reachy Mini", "act it out", "emotional robot", "embodied TTS", "add robot motion to this audio".
---

# Reachy Mini and Eleven v4

An expressive voice deserves an expressive body. This skill turns Eleven v4 audio tags into robot body language, so the same tag drives the voice and the body: `[laughs]` makes Eleven v4 laugh and makes the robot laugh with it.

Everything runs through one command line tool, `reachy-v4`, in the `engine` folder next to this file:

```bash
uv run --project "<this skill's folder>/engine" reachy-v4 <command>
```

In the rest of this file, `reachy-v4` means that full command. Some commands need an extra, which goes before the tool name: `uv run --project "<this skill's folder>/engine" --extra whisper reachy-v4 perform ...`.

## First run: play the demo

Start here when someone is new. The demo is the cake scene from the demo video, with its Eleven v4 audio included, so it needs no ElevenLabs account.

1. Check that `uv` is installed (`uv --version`). If not, point the user to https://docs.astral.sh/uv/.
2. Run `reachy-v4 check`. It finds `reachy-mini.local` by default. Pass `--robot <ip>` if the name does not resolve. The robot and the computer must be on the same network.
3. Run `reachy-v4 demo`. It prints the script and the plan, then performs for about 50 seconds.

The first run downloads the Pollen emotion library (Apache-2.0, from Hugging Face) and builds a collision model. This takes up to a minute. Later runs start in seconds.

If `check` reports "No route to host" on macOS, the terminal app has no Local Network permission. The user must turn it on in System Settings > Privacy & Security > Local Network, then restart the terminal. Do not try to work around this.

### No robot yet

Pollen's MuJoCo simulator shows a Reachy Mini in a 3D window, and the tool treats it like a real robot:

1. Start the simulator in the background: `uv run --project "<this skill's folder>/engine" --extra sim reachy-v4 sim`. The first start installs MuJoCo. Wait until `http://127.0.0.1:8000/api/daemon/status` answers.
2. Run any command with `--robot 127.0.0.1`, for example `reachy-v4 demo --robot 127.0.0.1`. The voice plays on the computer's speakers.
3. Stop the simulator when the user is done.

## Getting the speech

Use the first option that is available.

1. The ElevenLabs MCP server is connected (it has a `creative_generate_speech` tool). No API key is needed:
   1. Call `creative_generate_speech` with the tagged script as `prompt`, `model_id` `eleven_v4`, the voice id (Zibby, `wIzYfKZE8c87XZD7bDLH`, unless the user picked another) and `generations_count` 1.
   2. Poll `creative_get_flow_run_status` until the run completes, then take the audio link from the result (`media[0].url`). Links expire after about 2 hours.
   3. Run `reachy-v4 perform --audio "<link>" --text "<tagged script>"` with the `whisper` extra. It downloads the audio, finds the word timings on the computer and performs. The first run downloads a speech recognition model of about 500 MB.
2. `ELEVENLABS_API_KEY` is set in the environment: run `reachy-v4 say "<tagged script>"`. It generates the speech with word timings and performs it straight away.
3. Neither is available: offer the demo, then help the user connect one. To add the ElevenLabs MCP server to Claude Code, run `claude mcp add --transport http elevenlabs https://api.us.elevenlabs.io/v1/mcp`, then `/mcp` in Claude Code to sign in. An API key comes from the user's ElevenLabs account settings.

Never ask the user to paste an API key into the chat. Ask them to export it in their shell or load it from their password manager.

## Commands

| Command | What it does |
|---|---|
| `reachy-v4 demo` | Performs the cake scene from the demo video. Needs no API key |
| `reachy-v4 say "<tagged text>"` | Generates Eleven v4 speech with word timings and performs it. Needs `ELEVENLABS_API_KEY` |
| `reachy-v4 perform --audio <file or link> --text "<tagged text>"` | Performs speech the user already has, such as a download from the ElevenLabs app or an MCP result |
| `reachy-v4 preview <emotion> [--intensity 0.6]` | Plays one emotion's gesture without audio |
| `reachy-v4 emotions` | Lists the tags the robot understands |
| `reachy-v4 check-emotions [file.json]` | Checks built-in or custom emotions for collisions and reach |
| `reachy-v4 check` | Checks the robot, the network and the API key |
| `reachy-v4 sim` | Runs a simulated robot in a 3D window. Needs the `sim` extra |

Useful options:
- `--dry-run` plans and prints the timeline without moving the robot. Use it first when you change a script.
- `--robot <host or ip>` picks the robot. The `REACHY_HOST` environment variable sets a default.
- `--voice <voice_id>` picks any ElevenLabs voice for `say`. The default is Zibby, a very expressive character voice.
- `--emotions my_emotions.json` (before the command) loads extra emotions.

`perform` aligns the words with ElevenLabs forced alignment when `ELEVENLABS_API_KEY` is set, and on the computer with the `whisper` extra when it is not.

`say` and `perform` with a link save each take to `~/reachy-v4/`. `say` also saves a `.json` file with the word timings. Replay a take without generating it again: `reachy-v4 perform --audio <take>.mp3 --text @<text file> --words <take>.json`.

## How to write tags the robot can perform

Eleven v4 accepts any tag in square brackets. The robot acts out 10 emotions and their aliases. Run `reachy-v4 emotions` for the full list:

- states, held until the next tag: `[happy]`, `[excited]`, `[sad]`, `[angry]`, `[scared]`, `[curious]`, `[whispers]`
- events, sounds the robot reacts to: `[laughs]`, `[gasps]`, `[sighs]`

Follow these rules when you write or tag a script for the robot:

1. Put a tag where the feeling changes, at the start of a sentence. Do not tag every clause.
2. Give each emotion at least 3 seconds of speech, which is about 8 to 12 words. Tags closer than 2.5 seconds apart play as quick gestures, and the plan output flags them as "may feel rushed".
3. Put an event tag right before the words that react to it: `[gasps] Oh wow. It's a cake.`
4. Use intensity words inside the tag: `[slightly annoyed]` is a milder angry, `[very excited]` is a bigger one.
5. Other tags such as `[pause]`, `[light rain]` or `[French accent]` still shape the voice. The robot keeps its current mood during them.
6. Do not stack 2 emotion tags back to back. Pick the one that matters.
7. Next to each other, use emotions with different energy, such as sad then angry, or whispers then excited. Similar emotions in a row look the same on the robot.

For a longer piece, read `references/writing-scenes.md`. It explains what made the demo scene work and has short scenes to start from.

Example. The user asks: "Make the robot tell me it lost its charger." A good script:

```text
[curious] Hmm. Have you seen my charger? It was right here on the desk a minute ago. [sad] Oh no. I think the vacuum robot took it again. [sighs] It always does this. [angry] Next time I am hiding it somewhere really clever!
```

Then generate and perform it as described in "Getting the speech". Read the printed plan back to the user in one or two lines, for example which emotions played and when.

## Performing on the fly

When the user asks the robot to say something, do not ask them to write the tags. Write the tagged script yourself using the rules above, show it in one line, and perform it. If the plan shows a rushed emotion, merge or drop a tag and run it again.

## Adding a new emotion

Custom emotions live in a JSON file. See `references/custom-emotions.md` for the format, the list of Pollen gesture clips and tuning tips. Always run `reachy-v4 check-emotions <file>` before performing a new emotion. A hold pose needs at least 10 mm of clearance, and 12 mm or more is better. The robot's head gets close to its own body when it looks down, and the check uses the robot's real 3D shapes.

## How it works

`references/how-it-works.md` explains how tags become motion and why the robot never hits itself. Read it only if the user asks or a result looks wrong.

## Troubleshooting

See `references/troubleshooting.md`. The most common problems:
- no network access from the terminal on macOS (above)
- another app running on the robot: stop it in the Reachy Mini app, because only one app can drive the motors
- robot software too old: update it from the Reachy Mini app. This skill is tested on Reachy Mini Wireless with robot software 1.10, and in the simulator with 1.11.
