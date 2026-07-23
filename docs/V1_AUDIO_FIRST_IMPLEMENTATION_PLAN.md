# Failure Documentary Studio V1 — Audio-First Implementation Plan

## Goal

Build the smallest useful production flow by following the proven VCJ audio-first pattern:

```text
Narration with sparse inline performance tags
    -> Gemini TTS voice generation
    -> Exact timing from generated audio
    -> Shot planning
    -> Image generation
    -> Image + narration + basic sound animatic
    -> Video generation
    -> Final preview
```

This V1 deliberately avoids a large multi-agent Director system, advanced VFX planning, professional multitrack editing, automatic visual QA, and complex dependency graphs.

---

## Core rule

The generated voiceover is the timing authority.

Shots must never be planned from estimated script duration when real narration audio is available. Image timing, animatic timing, video trimming, captions, and final preview duration must follow the generated voiceover.

---

## What we reuse from VCJ

Only the following proven mechanisms are copied into the documentary engine:

1. Stable sequential paragraph IDs.
2. Narration written for the ear rather than as article prose.
3. Sparse inline performance tags inside narration text.
4. Chapter-by-chapter Gemini TTS generation.
5. Audio caching by text, provider, model, voice, and TTS prompt.
6. Regeneration of one changed chapter without regenerating the complete voiceover.
7. Basic audio quality checks before chapter approval.
8. Master voiceover assembly with deterministic chapter gaps.
9. Word timing derived from the generated audio.
10. Shot boundaries selected near word starts, punctuation, and measured pauses.
11. Completed jobs and artifacts preserved so a stopped run can resume.
12. Final video/audio assembly through FFmpeg with stream validation.

---

## V1 production stages

### 1. Narration

The current research and structure stages can remain as input to narration generation, but the visible production workflow begins at Narration.

Narration is generated as strict JSON:

```json
{
  "title": "The Flight That Vanished",
  "target_duration_seconds": 480,
  "spoken_word_count": 1050,
  "paragraphs": [
    {
      "id": "paragraph_01",
      "beat_label": "cold_open",
      "text": "[quietly investigative] At 1:21 in the morning, the aircraft disappeared from civilian radar.",
      "claim_ids": ["CLAIM_001"]
    }
  ],
  "tts_narration": "all tagged paragraph text joined in order"
}
```

#### Performance-tag rules

Use inline square-bracket tags rather than a separate expression object.

Initial controlled tag set:

```text
[quietly investigative]
[curious]
[clear and measured]
[gentle emphasis]
[thinking pause]
[serious]
[with restrained urgency]
[somber]
[reflective]
```

Rules:

- Use tags sparingly.
- Put a tag before the complete sentence it controls.
- Normally use no more than one tag per paragraph.
- Do not tag every paragraph.
- Keep delivery restrained and documentary-like.
- Never use exaggerated trailer, shouting, panic, or sensational tags.
- Keep camera, image, sound, and editing instructions out of spoken narration.

#### Tagged and clean text

The system stores both forms:

```text
Tagged TTS text:
[serious] At 1:21 a.m., the signal vanished.

Clean spoken text:
At 1:21 a.m., the signal vanished.
```

Tagged text is sent to Gemini TTS.

Clean text is derived locally and used for:

- word counting;
- Whisper/native alignment;
- captions;
- shot narration text;
- search and comparison;
- validation that TTS did not add or remove words.

Suggested helper:

```python
TAG_PATTERN = re.compile(r"\[[^\[\]]+\]\s*")


def clean_spoken_text(tagged_text: str) -> str:
    return " ".join(TAG_PATTERN.sub("", tagged_text).split())
```

---

### 2. Voice generation

V1 providers:

- Gemini TTS
- ElevenLabs as an optional alternative
- Manual audio upload as fallback

Gemini is the default.

#### Gemini TTS direction

Use one concise global documentary instruction plus the tagged transcript:

```text
You are the narrator of a premium failure-investigation documentary.

Read the transcript exactly as written.

The voice should feel authoritative, intimate, restrained, intelligent and cinematic.
Speak at a measured natural pace, with clear pronunciation of names, numbers and
technical terms. Build suspense through control and silence, never through shouting
or exaggerated trailer-style delivery.

Follow bracketed performance tags such as [curious], [serious],
[quietly investigative], [thinking pause] and [with restrained urgency].
The tags are performance directions. Do not speak them aloud.

Preserve every spoken word. Do not add, remove, paraphrase or explain anything.

TRANSCRIPT:

{tagged_paragraph_text}
```

#### Chapter generation

Generate one audio chapter for each narration paragraph:

```text
04_voice/
├── chapters/
│   ├── paragraph_01/
│   │   ├── tagged_text.txt
│   │   ├── clean_text.txt
│   │   ├── audio.wav
│   │   ├── cache_key.txt
│   │   ├── generation.json
│   │   └── quality.json
│   └── paragraph_02/
├── voiceover_master.wav
├── voiceover.mp3
└── audio_manifest.json
```

#### Cache key

The chapter cache key must include:

- provider;
- model;
- voice;
- global documentary TTS direction;
- tagged paragraph text;
- audio format and sample rate.

Changing one paragraph or its tag should regenerate only that chapter.

#### Audio quality checks

For each generated chapter validate:

- file exists and is non-empty;
- duration is within a reasonable range;
- audio is not silent;
- peak level is not clipped;
- RMS is above the silence threshold;
- output format is valid.

Insert a deterministic small silence during master assembly. Start with a default chapter gap of `0.30` seconds.

The chapter gap is not a replacement for expressive pauses inside sentences. Inline tags and punctuation control delivery; the deterministic gap keeps chapter assembly stable.

---

### 3. Exact audio timing

Timing runs automatically after master voice generation.

Priority:

1. Native provider timing/alignment when available.
2. Otherwise local Whisper word timestamps.

Outputs:

```text
05_timing/
├── audio_timing.json
└── word_timestamps.json
```

Example:

```json
{
  "audio_duration_seconds": 481.24,
  "source": "openai_whisper_word_timestamps",
  "paragraphs": [
    {
      "id": "paragraph_01",
      "start": 0.0,
      "end": 7.42,
      "duration": 7.42
    }
  ],
  "words": [
    {
      "paragraph_id": "paragraph_01",
      "word": "aircraft",
      "start": 2.48,
      "end": 2.91
    }
  ]
}
```

Timing must be linked to the current voiceover hash. If the voiceover changes, old timing is stale and cannot be used for shot planning.

---

### 4. Shot planning

The shot planner runs only after valid voice timing exists.

Inputs:

- approved narration;
- clean narration text;
- paragraph timing;
- word timestamps;
- research/structure context;
- global documentary visual style.

The planner produces exact short shots aligned to real audio.

Recommended starting limits:

```text
Minimum shot: 3 seconds
Target shot: 5–7 seconds
Maximum shot: 10 seconds
```

Boundaries should prefer:

- sentence endings;
- punctuation;
- measured pauses;
- important reveal words;
- a coherent visual idea.

The model proposes the visual treatment, while local deterministic logic snaps boundaries to valid word/pause points.

Shot output:

```json
{
  "shots": [
    {
      "shot_id": "SHOT_001",
      "start": 0.0,
      "end": 5.84,
      "paragraph_ids": ["paragraph_01"],
      "narration_text": "At 1:21 in the morning...",
      "visual_description": "Night aerial reconstruction of a commercial aircraft crossing a dark coastline.",
      "image_prompt": "Cinematic failure-investigation documentary reconstruction...",
      "video_prompt": "The aircraft moves steadily through thin cloud with restrained camera drift...",
      "sound_hint": "subtle distant aircraft engine ambience",
      "transition": "hard_cut"
    }
  ]
}
```

V1 shot planning includes only:

- exact timing;
- narration text;
- visual description;
- image prompt;
- video prompt;
- one simple sound hint;
- transition.

No complex VFX contract is included in V1.

---

### 5. Image generation

Generate one primary image for every approved shot.

Per-shot structure:

```text
07_images/
├── SHOT_001/
│   ├── prompt.txt
│   ├── image.png
│   ├── metadata.json
│   └── thumbnail.jpg
```

Image-job states:

```text
pending -> generating -> downloaded -> review -> approved/rejected
```

Studio controls:

- preview image;
- play the matching narration section;
- regenerate;
- upload replacement;
- approve;
- reject.

The prompt must include:

- global documentary style;
- shot-specific action and composition;
- relevant continuity details from the current project;
- cinematic 16:9 framing;
- no embedded text or subtitles;
- restrained, technically credible imagery.

---

### 6. Image + narration + basic sound animatic

Before video generation, create a low-cost animatic from approved images.

Inputs:

- approved shot images;
- exact shot timing;
- master voiceover;
- optional basic ambience/SFX selected from each shot's sound hint;
- simple transitions.

Output:

```text
08_animatic/
├── animatic.mp4
├── sound_plan.json
└── render_report.json
```

The animatic may use restrained image motion such as a small push, drift, or crop change. This is a review tool, not the final visual style.

Animatic review should answer:

- Does each visual match the spoken line?
- Are shots too short or too long?
- Are any images repetitive?
- Is the story understandable before video generation?
- Are the simple sound cues helpful or distracting?
- Should a shot remain a still image instead of becoming video?

Video generation remains blocked until the animatic is approved.

---

### 7. Video generation

Only approved shots proceed to video generation.

Use the approved image as the input frame where image-to-video is supported.

Example request:

```json
{
  "shot_id": "SHOT_001",
  "source_image": "07_images/SHOT_001/image.png",
  "duration": 5.84,
  "resolution": "720p",
  "aspect_ratio": "16:9",
  "prompt": "Slow cinematic aerial motion; maintain aircraft geometry and lighting; restrained camera drift."
}
```

Rules:

- Request `720p` explicitly.
- Generated video does not own the edit timing.
- Trim longer results to the approved shot duration.
- Hold the final frame or use the approved image when a result is slightly short.
- Do not alter narration timing to fit generated footage.
- Allow a shot to remain an image when video adds no value.

Per-shot structure:

```text
09_videos/
├── SHOT_001/
│   ├── source.mp4
│   ├── approved.mp4
│   └── metadata.json
```

Job controls:

- generate;
- pause after current job;
- stop;
- resume pending;
- retry failed;
- regenerate;
- upload replacement;
- approve;
- retain image instead of video.

Every completed result must be imported immediately so interruption does not lose completed work.

---

### 8. Final preview

The final preview combines:

- approved video where available;
- approved image fallback for remaining shots;
- master narration;
- the approved simple sound plan;
- transitions.

Output:

```text
10_final_preview/
├── final_preview.mp4
└── render_report.json
```

Starting output target:

```text
1920 x 1080
30 fps
H.264 video
AAC audio
```

Source Grok clips may be 720p and are scaled into the 1080p composition.

The render must validate that the final MP4 contains both video and audio streams.

---

## Simplified Studio navigation

The visible V1 production navigation is limited to:

```text
1. Narration
2. Voice
3. Shots
4. Images
5. Animatic
6. Videos
7. Final Preview
```

Existing Research and Structure pages can remain under Story Setup without adding more production stages.

---

## Project directory layout

```text
projects/<project-id>/
├── 00_input/
├── 01_research/
├── 02_structure/
├── 03_narration/
├── 04_voice/
│   ├── chapters/
│   ├── voiceover_master.wav
│   ├── voiceover.mp3
│   └── audio_manifest.json
├── 05_timing/
├── 06_shots/
├── 07_images/
├── 08_animatic/
├── 09_videos/
├── 10_final_preview/
├── _jobs/
└── project_manifest.json
```

---

## V1 states

```text
PROJECT_CREATED

NARRATION_REVIEW
NARRATION_APPROVED

VOICE_GENERATING
VOICE_REVIEW
VOICE_APPROVED

SHOTS_GENERATING
SHOTS_REVIEW
SHOTS_APPROVED

IMAGES_GENERATING
IMAGES_REVIEW
IMAGES_APPROVED

ANIMATIC_READY
ANIMATIC_APPROVED

VIDEOS_GENERATING
VIDEOS_REVIEW
VIDEOS_APPROVED

FINAL_PREVIEW_READY
```

Research and structure can remain internal prerequisites without expanding this production state list.

---

## Planned code changes

### Models and state

```text
fde/models.py
fde/constants.py
fde/project.py
```

- Replace the current visuals-first ordering with the V1 audio-first states.
- Add narration paragraph, timing, shot, animatic, and video-job models.
- Keep model schemas small and versioned.

### Narration and voice

```text
fde/narration.py
fde/providers/gemini_tts.py
fde/providers/elevenlabs_tts.py
fde/providers/manual_audio.py
```

- Add tagged-to-clean text handling.
- Add the documentary narration prompt.
- Add Gemini TTS chapter generation.
- Add chapter caching and audio QC.
- Add master voiceover assembly.

### Timing

```text
fde/timing.py
```

- Reuse provider alignment when available.
- Fall back to Whisper word timestamps.
- Link timing files to the current voiceover hash.

### Shot planning

```text
fde/director.py or fde/shots.py
```

- Consume actual audio timing.
- Generate visual descriptions and image/video prompts.
- Snap proposed boundaries to valid word/pause points.

### Images, animatic, and video jobs

```text
fde/providers/media_factory.py
fde/studio/jobs.py
fde/render.py
fde/timeline.py
```

- Keep image and video jobs resumable.
- Add image-first animatic rendering.
- Add explicit 720p video requests.
- Allow image fallback per shot.
- Assemble the final preview with voice and approved basic sound.

### Studio UI

```text
fde/studio/service.py
fde/studio/server.py
fde/studio/static/index.html
fde/studio/static/app.js
fde/studio/static/styles.css
```

- Present only the seven V1 stages.
- Add per-chapter voice playback/regeneration.
- Add shot timing and prompt review.
- Add image approval.
- Add animatic approval gate.
- Add video queue controls and final preview playback.

---

## Implementation sequence

### Milestone 1 — Narration and real voice

- documentary narration prompt with sparse inline tags;
- tagged/clean text support;
- Gemini TTS chapter generation;
- cache and quality checks;
- master voiceover assembly;
- voice review UI.

### Milestone 2 — Timing and shots

- provider/Whisper alignment;
- real paragraph and word timing;
- audio-first shot planning;
- shot review/edit UI.

### Milestone 3 — Images and animatic

- image generation queue;
- per-shot approval;
- simple sound-hint resolver;
- image + narration + basic sound animatic;
- animatic approval gate.

### Milestone 4 — Videos and final preview

- image-to-video queue;
- explicit 720p requests;
- pause/stop/resume;
- image fallback;
- final 1080p preview assembly and validation.

---

## Not included in V1

- Separate Narrative, Visual, Sound, and Continuity Director agents.
- Advanced VFX planning.
- Motion Canvas scene coding.
- Professional multitrack editor.
- Music generation.
- Automated multimodal visual QA.
- Complex continuity contracts.
- Full caption authoring UI.
- Large artifact dependency graph.
- Multiple rendering backends beyond the existing practical fallback path.

---

## Acceptance criteria

V1 is complete only when all of the following are true:

1. Narration is generated with sparse square-bracket performance tags.
2. Clean spoken text is derived locally without tags.
3. Gemini TTS generates real chapter audio.
4. One paragraph can be regenerated without regenerating every chapter.
5. Silent, empty, invalid, or clipped chapters are rejected.
6. A complete master voiceover can be played in Studio.
7. Word timings are produced from the generated audio.
8. Timing is invalidated when the voiceover changes.
9. Shot planning is blocked until valid voice timing exists.
10. Every shot has exact start and end times based on real audio.
11. Every shot can generate, review, replace, and approve an image.
12. The Studio can render an image + narration + basic sound animatic.
13. Video generation is blocked until animatic approval.
14. Video requests explicitly use 720p and 16:9.
15. Completed video jobs survive stop/resume and are imported immediately.
16. A shot may retain its approved image instead of using generated video.
17. Final preview combines approved videos, image fallbacks, narration, and basic sound.
18. Final preview is rendered at 1920x1080 and contains valid audio and video streams.
19. The branch contains normal source files only; no bootstrap archives or extraction workflow are introduced.

---

## Final V1 principle

Write expressive narration with sparse inline performance tags, generate and approve the real voice, divide that audio into exact shots, approve the image animatic, and only then generate the video clips needed for the final preview.
