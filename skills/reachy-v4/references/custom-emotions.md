# Custom emotions

A custom emotion is one JSON object. Put one or more in a file, as a list, and load it with `--emotions file.json` or the `REACHY_V4_EMOTIONS` environment variable. An emotion with the same `name` as a built-in one replaces it.

`engine/examples/custom_emotions.json` has two working examples, proud and shy.

## Fields

| Field | Meaning |
|---|---|
| `name` | The tag, lowercase, for example `proud` matches `[proud]` |
| `label` | Display name |
| `kind` | `state` (a mood held until the next tag) or `event` (a reaction to a sound such as a laugh) |
| `color` | Hex colour, used by user interfaces only |
| `aliases` | Other tag words that mean the same, for example `["proudly", "triumphant"]`. Longer phrases win, so `quietly curious` beats `quietly`. |
| `clips` | Pollen gesture clips that start the emotion (list below). One is picked per use, to fit the time available. Leave it empty for a pose-only emotion. |
| `keyframes` | Optional. A hand-made onset gesture used instead of clips: a list of `{"t": seconds after the tag, "pose": {...}}`, eased in between. The built-in sigh uses 3: rest, a quick inhale up, then a slow exhale down with the antennas sinking. |
| `clip_offset` | Optional. Seconds to skip at the start of a clip, for example `{"sad2": 3.0}` skips a slow wind-up |
| `hold` | The pose the robot keeps while it speaks in this mood (see below) |
| `idle` | Small repeating motions on top of the hold, so the pose stays alive |

### Hold pose units

- `x`, `y`, `z` in millimetres: x is forward, y is to the robot's left, z is up
- `roll`, `pitch`, `yaw` in degrees: pitch above 0 looks down
- `body_yaw` in degrees: turns the whole body
- `ant_r`, `ant_l` in degrees: neutral is -10 and 10, and the absolute value grows as an antenna droops back. For example, sad uses -130 and 130.

Keep the head within about ±15 mm, ±30° pitch and roll, and ±60° yaw. Keep head yaw within 60° of body yaw. The planner clamps anything outside these ranges.

### Idle waves

Each wave adds `amp * sin(2π · hz · t + phase)` to one channel. The channel is one of the pose fields, or:
- `ants`: both antennas swing outward together
- `ants_mirror`: antennas flap in the same direction

Slow waves (0.2 to 0.5 Hz) read as breathing or thinking. Fast ones (4 to 9 Hz) read as laughing or trembling.

## Tuning tips

- The robot's head gets closest to its body when it looks down or tilts. If `check-emotions` reports low clearance, move `x` back (negative) or raise `z`. That keeps the angles, which carry most of the expression.
- The real head sags a few degrees when pitched down. The check accounts for this, so trust its numbers over what looks fine on paper.
- Preview before you use it in a script: `reachy-v4 --emotions file.json preview proud`.
- Every stressed syllable in the speech also adds a short accent in the emotion's style (jabs for angry, bounces for excited). A custom emotion uses a gentle nod unless it replaces a built-in one.
- Stronger is not always clearer. Distinct emotions come from different directions: up or down, toward or away, still or restless.

## Pollen gesture clips

The clips come from the Pollen Robotics emotion library. The durations run from 2 to 20 seconds, with a median of about 4.6.

amazed1, anxiety1, attentive1, attentive2, boredom1, boredom2, calming1, cheerful1, come1, confused1, contempt1, curious1, dance1, dance2, dance3, disgusted1, displeased1, displeased2, downcast1, dying1, electric1, enthusiastic1, enthusiastic2, exhausted1, fear1, frustrated1, furious1, go_away1, grateful1, helpful1, helpful2, impatient1, impatient2, incomprehensible2, indifferent1, inquiring1, inquiring2, inquiring3, irritated1, irritated2, laughing1, laughing2, lonely1, lost1, loving1, mini-deep-sleep, no1, no_excited1, no_sad1, oops1, oops2, proud1, proud2, proud3, rage1, relief1, relief2, reprimand1, reprimand2, reprimand3, resigned1, sad1, sad2, scared1, serenity1, shy1, sleep1, success1, success2, surprised1, surprised2, thoughtful1, thoughtful2, tired1, toc-toc-toc, uncertain1, uncomfortable1, understanding1, understanding2, waiting, wake-mini-up, welcoming1, welcoming2, yes1, yes_sad1
