# Failure Documentary Studio — Verified Provider and Model Matrix

Last checked against official provider documentation: **2026-07-23**.

The Studio routing page is generated from `fde/orchestrator.py`. Only executable V1 tasks are shown. A provider appears for a task only when its adapter supports the required capability, and the backend rejects unverified provider/model/resolution combinations before a job starts.

## Executable V1 routing tasks

| Stage | Task | Capability |
|---|---|---|
| Story setup | Research dossier | Structured output |
| Story setup | Story structure | Structured output |
| Narration | Narration writer | Structured output |
| Voice | Documentary voice | Audio generation |
| Voice | Word alignment | Alignment |
| Shots | Audio-led visual director | Structured output plus immutable local timing compiler |
| Images | Image generator | Image generation |
| Animatic | Animatic renderer | Local rendering |
| Videos | Video generator | Image-to-video generation |
| Final preview | Final renderer | Local rendering |

The visual director may improve composition, image prompts, video prompts, camera direction, motion, and sound hints. It cannot change the locally compiled shot IDs, word-aligned boundaries, narration membership, total duration, or voiceover hash.

## Structured providers

### Codex CLI

Official model documentation: https://developers.openai.com/api/docs/models

Available route selections:

- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`

The adapter uses the existing authenticated Codex CLI command and writes the final strict JSON message to the stage response file.

Requirement: `codex` on `PATH` and an authenticated ChatGPT/Codex session.

### Claude API

Official model documentation: https://platform.claude.com/docs/en/about-claude/models/overview

Available route selections:

- `claude-fable-5`
- `claude-opus-4-8`
- `claude-sonnet-5`
- `claude-haiku-4-5`

The adapter uses Anthropic structured output and validates the response against the pipeline's Pydantic contract.

Requirement: `ANTHROPIC_API_KEY`.

### Grok Build CLI

Official model documentation: https://docs.x.ai/developers/models

Structured selections:

- `authenticated-default`
- `grok-4.5`
- `grok-4.3`
- `grok-build-0.1`

Requirement: `grok` on `PATH` and `grok login` completed.

### Kimi API

Official documentation: https://platform.kimi.ai/docs/overview

Available route selections:

- `kimi-k3`
- `kimi-k2.7-code`
- `kimi-k2.7-code-highspeed`
- `kimi-k2.6`
- `kimi-k2.5`

The adapter uses Moonshot's OpenAI-compatible chat-completions endpoint with JSON mode. Kimi K3 routes expose the documented `low`, `high`, and `max` reasoning-effort choices.

Requirement: `MOONSHOT_API_KEY`.

### Gemini API

Official model documentation: https://ai.google.dev/gemini-api/docs/models

Structured selections:

- `gemini-3.6-flash`
- `gemini-3.5-flash`
- `gemini-3.5-flash-lite`
- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite`
- `gemini-2.5-pro`
- `gemini-2.5-flash`

The adapter uses the Google Gen AI SDK's JSON response schema and validates the resulting object locally.

Requirement: `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

### Gemini CLI

Official headless-mode documentation: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md

Available route selections:

- `auto`
- `pro`
- `flash`
- `flash-lite`
- `gemini-3.1-pro-preview`
- `gemini-3-flash-preview`
- `gemini-3.1-flash-lite`
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

The native adapter invokes headless mode with `--output-format json`, reads the documented top-level `response` field, extracts the model's strict JSON object, and validates it against the stage contract. It does not incorrectly treat the Gemini CLI envelope itself as the pipeline response.

Requirement: `gemini` on `PATH` and Gemini CLI authentication completed.

## Image providers

### Grok CLI / Imagine

Models:

- `grok-imagine-image-quality`
- `grok-imagine-image`

Selectable resolutions:

- `1K`
- `2K`

Selectable quality presets:

- `standard`
- `quality`

The CLI adapter explicitly requests and records the selected Imagine model, quality, resolution, and aspect ratio. Grok CLI may internally route its built-in Imagine tool, so the saved generation metadata records both the requested settings and the returned file.

### OpenAI GPT Image API

Official documentation: https://developers.openai.com/api/docs/models/gpt-image-2

Models:

- `gpt-image-2`
- `gpt-image-2-2026-04-21`

Native output sizes:

- `auto`
- `1024x1024`
- `1536x1024`
- `1024x1536`

Quality:

- `auto`
- `low`
- `medium`
- `high`

OpenAI exposes exact pixel dimensions rather than generic 1K/2K labels, so the Studio displays the native size choices.

Requirement: `OPENAI_API_KEY`.

### Gemini API images

Models and selectable output sizes:

| Model | Output sizes |
|---|---|
| `gemini-3.1-flash-image` | 512, 1K, 2K, 4K |
| `gemini-3.1-flash-lite-image` | 1K |
| `gemini-3-pro-image` | 1K, 2K, 4K |
| `gemini-2.5-flash-image` | 1K |

The adapter prefers the current Interactions image response contract when the installed Google Gen AI SDK supports it and falls back to the documented GenerateContent image contract for older SDK releases. The router excludes retired image endpoints and validates model-specific size choices before generation.

## Video providers

### Grok CLI / Imagine Video

| Model | Resolutions |
|---|---|
| `grok-imagine-video-1.5` | 480p, 720p, 1080p |
| `grok-imagine-video` | 480p, 720p |

Selectable durations exposed by the Studio: 5, 6, 8, 10, and 12 seconds. The exact documentary shot duration remains controlled by the voice-led edit; provider clips are trimmed or held locally to fit it.

### Gemini API video

| Model | Resolutions | Provider durations |
|---|---|---|
| `gemini-omni-flash-preview` | 720p | 3–10 seconds |
| `veo-3.1-generate-preview` | 720p, 1080p, 4k | 4, 6, or 8 seconds |
| `veo-3.1-fast-generate-preview` | 720p, 1080p, 4k | 4, 6, or 8 seconds |
| `veo-3.1-lite-generate-preview` | 720p, 1080p | 4, 6, or 8 seconds |

The provider API uses lowercase `4k`. Veo 3.1 requests at 1080p or 4k require an eight-second provider generation; the adapter enforces that rule and the documentary engine trims the result to the exact voice-led shot duration. Retired Veo 2 and Veo 3.0 routes are intentionally excluded.

## Audio and alignment

### Google Gemini TTS

Official documentation: https://ai.google.dev/gemini-api/docs/speech-generation

Models:

- `gemini-3.1-flash-tts-preview`
- `gemini-2.5-flash-preview-tts`
- `gemini-2.5-pro-preview-tts`

The Studio exposes the supported documentary voice list and stores the selected model, voice, chapter cache key, quality report, and master-voice SHA.

Requirement: `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

### Local Whisper

Official repository: https://github.com/openai/whisper

Selections:

- `tiny.en`
- `base.en`
- `small.en`
- `medium.en`
- `large-v3`

Word timing is linked to the current master-voice SHA. A changed voiceover makes previous timing invalid.

## Restart and regeneration contract

Every unlocked stage has two controls:

- **Restart from here** — archives the selected stage and every downstream output, resets the state, and waits.
- **Run this step again** — performs the same archive/reset operation and immediately starts that stage using the currently selected route.

No existing production artifact is silently deleted. Previous outputs are moved to:

```text
projects/<project-id>/_history/<timestamp>-<stage-id>/
```

Upstream approved work is preserved. For example, restarting Images keeps the approved narration, voice, exact timing, and shot plan while archiving images, animatic, videos, and final preview.
