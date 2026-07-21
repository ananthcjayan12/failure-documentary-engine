# AI Orchestrator

The AI Orchestrator is the provider-agnostic control plane for Failure Investigation Studio. Every production task declares a capability and may independently select a provider, model, retry policy and compatible fallback.

## Capability map

The 17 routable tasks cover:

- research and fact verification;
- structure, narration and script QA;
- shot planning and asset optimization;
- image prompting, native image generation and image QA;
- animation prompting, native video generation and video QA;
- narration voice/import;
- timeline assembly;
- HyperFrames or FFmpeg rendering;
- final QA.

Capabilities are explicit:

```text
structured · image · video · audio · render
```

The task editor filters its provider list by capability, preventing invalid routes such as assigning a text-only model to image generation.

## Built-in providers

- **Codex CLI** — structured reasoning.
- **Claude Code** — structured reasoning.
- **Gemini CLI** — structured reasoning.
- **Grok Build CLI** — structured reasoning, Imagine images and image-to-video.
- **Custom CLI Adapter** — structured, image, video and audio extension point.
- **ChatGPT UI** — structured/image manual handoff.
- **Grok UI** — structured/image/video manual handoff.
- **Manual Upload** — image/video/audio handoff.
- **HyperFrames** — deterministic browser rendering.
- **FFmpeg** — deterministic fallback rendering.
- **Offline Mock** — complete zero-provider test path.

## Profiles

- **Highest Quality** — specialist reasoning routes, Grok CLI media and HyperFrames.
- **Balanced** — Codex-centered reasoning with Grok CLI media.
- **Grok First** — Grok CLI for every compatible reasoning/media task.
- **Subscription UI** — ChatGPT Images and Grok UI handoffs.
- **Fast** — lighter reasoning and FFmpeg rendering.
- **Offline Test** — deterministic local generation for all stages.

Applying a profile replaces the complete map. Editing one task changes the workspace to **Custom mapping**.

## Fallback execution

Structured tasks use one routed agent rather than a provider-specific pipeline. Primary retries run first; then the fallback adapter runs. A command CLI may therefore fall back to Grok CLI, Mock or a manual bridge, and Grok CLI may fall back to Codex/Claude/Gemini when a compatible command is configured.

Media generation is asset-scoped. A failed asset may fall back to another native provider or produce a `manual_required` record without discarding successful siblings.

## Prompt packs

The active domain pack is injected into real structured prompts. Included packs are Aviation Investigation, Engineering Failure, Cyber Incident, Space Mission Failure and General Investigation.

## Local configuration

```text
projects/.fde-studio.json
projects/.fde-orchestrator.json
```

These files contain routing and command templates, not provider passwords or API keys.

See [`GROK_CLI_HYPERFRAMES.md`](GROK_CLI_HYPERFRAMES.md) for media and rendering details.
