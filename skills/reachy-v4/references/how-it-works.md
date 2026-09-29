# How tags become motion

1. Parse. Each `[tag]` maps to one of the robot's emotions through its name, its aliases and intensity words. Tags with no emotion shape the voice only.
2. Time. Word timings come from Eleven v4 with timestamps, from ElevenLabs forced alignment, or from local faster-whisper. A state tag starts with the next spoken word. An event tag starts right after the previous word, where the laugh or gasp is.
3. Choreograph. Each emotion opens with a Pollen gesture clip, then settles into its hold pose with small idle motion. The body starts about 0.1 seconds before the voice, as animators do. An event with its own sentence keeps the body until the next tag. An event followed closely by another tag plays as a quick gesture and hands back to the mood.
4. Speech motion. The head sways gently with the loudness of the voice, and every stressed syllable adds a short accent in the emotion's style: jabs and head shakes when angry, bounces when excited, bobs on each laugh burst, small nods when curious. A calm sway with sharp beats reads as more alive than constant motion.
5. Safety. Every frame goes through 2 checks:
   - reach: the robot's own kinematics check that the head can reach the pose. Unreachable poses would freeze the head, so they are eased toward neutral.
   - clearance: the robot's real 3D shapes check that the head stays at least 10 mm from the body. The check allows for the head sagging under its own weight. Close frames are lifted smoothly, starting before the contact would happen.
6. Finish. After the last word the robot settles and gives a small nod.
7. Play. The motion timeline and the audio are uploaded to the robot together and play on the robot's own clock, so Wi-Fi delays cannot desynchronise them.
