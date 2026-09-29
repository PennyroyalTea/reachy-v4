# Writing a scene the robot can act

A scene is a short tagged script that tells a small story. The best scenes make the voice and the body change together, so each tag should be a moment the audience can see as well as hear.

## What made the demo scene work

1. It tells a story with a turn. A box appears, it holds a cake, the cake is for someone else, something is wrong, then a happy ending. Each emotion has a reason to arrive.
2. Neighbouring emotions differ in energy and direction. Sad, low and slow, is followed by angry, forward and sharp. Whispers, still and turned away, is followed by excited, up and bouncing. The bigger the change, the easier it is to see.
3. Each emotion gets 3 to 5 seconds of speech, about 8 to 15 words. The demo fits 10 emotions into 47 seconds, which is about the limit.
4. Event tags come right before their reaction, and a sentence follows them: `[gasps] Oh wow. It's a cake.` The gasp lands on the body first, then the words carry it.
5. Sentences are short. Questions and exclamations give the voice something to hit, and every stressed syllable adds a small head accent.
6. The robot talks about its own life: its battery, its charger, the vacuum robot. People like a robot that knows it is a robot.
7. It ends on a warm emotion. After the last word the robot settles and gives a small nod.

## The demo scene

```text
[curious] Hmm. There's a box on my desk. It has my name on it, in big letters. What could possibly be inside?
[gasps] Oh wow. It's a cake. A real cake, with candles!
[laughs] Is it really for me? Nobody ever makes me cakes.
[sad] Oh. Wait. The card says it's for someone else. It's for the vacuum robot.
[sighs] Of course it is. It's always the vacuum robot.
[angry] And who drained my battery again? I was at a hundred percent this morning!
[scared] Wait. What was that noise? Something just moved under the desk.
[whispers] Don't move. I think someone is standing right behind the door.
[excited] It's you! You came back! You really came back!
[happy] I'm so glad you're here. I really missed you.
```

Write it as one line when you pass it to `say`. The line breaks here only show the beats.

## Shorter scenes to start from

About 20 seconds each:

```text
[curious] Is that music? I think that's my song. [excited] It is my song! Turn it up, turn it up! [laughs] Look at me, I can't stop dancing. [sighs] Oh no. It's over already. [happy] Play it again?
```

```text
[scared] Wait. Where is my charger? It was right here a minute ago. [angry] Somebody moved it again! [curious] Hmm. What's that under the chair? [gasps] There it is! [happy] Oh, what a relief. Hello, old friend.
```

```text
[whispers] Psst. Can you keep a secret? [excited] I learned a new trick today! Watch this, watch closely. [sad] Oh. It worked much better this morning. [laughs] Okay, that was terrible. [happy] I'll practise, I promise.
```

## Before you perform

- Run the scene with `--dry-run` first. The plan lists each emotion, when it starts, and flags any that may feel rushed.
- Fix a rushed emotion by giving it a longer sentence, or by dropping a tag.
- If two emotions in a row look alike on the robot, swap one for an emotion with the opposite energy.
