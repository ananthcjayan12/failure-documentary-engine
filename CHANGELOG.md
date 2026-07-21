# Changelog

## 0.5.0

- Added native Grok Build CLI support for structured reasoning, image generation and image-to-video generation.
- Added streaming-JSON recovery, media path/URL discovery and preserved raw Grok output.
- Added asset-scoped media generation ledgers, retries, fallbacks and interruption-safe resumability.
- Expanded the AI Orchestrator from 13 to 17 capability-routed tasks.
- Added explicit `structured`, `image`, `video`, `audio` and `render` capabilities.
- Added capability-filtered provider selection and compatibility validation.
- Added the Grok First and Subscription UI profiles.
- Added a Custom CLI Adapter with separate structured and media command templates.
- Added a provider-agnostic routed structured agent supporting cross-adapter fallback.
- Added HyperFrames 0.7.62 and GSAP 3.13.0 as the deterministic browser-render runtime.
- Added `hf-seek` timeline compositions, linting, resumable entry-aligned render chunks, FFprobe validation, FFmpeg concatenation and narration muxing.
- Added automatic FFmpeg renderer fallback.
- Rebuilt the Production and Provider UI for native media generation and provider capabilities.
- Added automated tests for capability routing, cross-provider fallback, media resumability and HyperFrames contracts.

## 0.4.0

- Added the AI Orchestrator main workspace.
- Added 13 persisted task-to-model routes.
- Added routing profiles, editable prompt packs and provider health checks.
- Added reasoning, temperature, timeout, retry and fallback controls.
- Integrated selected routes into background jobs.
