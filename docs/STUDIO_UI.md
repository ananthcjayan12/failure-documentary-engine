# Failure Investigation Studio

The Studio is the primary operator interface for the Failure Documentary Engine. It keeps project creation, resumable stages, review gates, ChatGPT Image Factory exchange, video imports, narration, timeline assembly, logs, and local configuration in one browser workspace.

## Start

```bash
fde studio
```

Open `http://127.0.0.1:8765`.

To open a known project immediately:

```bash
fde studio --project-id mh370
```

The server binds to `127.0.0.1` by default and is intended to remain local.

## Main workspaces

### Overview

- project totals and review backlog;
- recent productions;
- direct resume into the active project;
- local capability indicators.

### Production

- project brief and completion progress;
- eight numbered pipeline stages;
- stage-specific artifacts;
- recommended next action;
- asynchronous process state and live log;
- manual JSON response bridge;
- Image Factory export and ZIP import;
- contact-sheet preview.

### Assets

- image and video tabs;
- search and filters;
- asset continuity metadata and linked shots;
- prompt drawer;
- approve, reject, or request a targeted change;
- bulk approval for available files;
- direct image/video upload.

### Timeline

- narration upload with optional timestamps;
- timeline entries and source asset mapping;
- preview rendering;
- picture-lock controls.

### Projects

- all local productions;
- persisted status and progress;
- direct resume from any project.

### Settings

- manual, command, or mock agent mode;
- configurable Codex command template;
- project defaults;
- FFmpeg, ffprobe, and Codex readiness.

## Resumability

Every generation or local processing action is launched as a subprocess. The Studio writes:

```text
projects/<project-id>/studio_run.json
projects/<project-id>/studio.log
```

The browser may be closed while the local server remains running. Refreshing or reopening the Studio restores the project state and log. A Studio restart marks an abandoned running process as interrupted instead of silently pretending it completed.

A manual-agent stage writes its prompt and schema into `_requests/`. Paste a strict JSON response into the Studio and choose **Save and resume stage**. Return code `2` is treated as a deliberate waiting state rather than a failed run.

## Paid or subscription boundaries

The Studio does not hide provider boundaries:

- the agent mode is selected in Settings;
- the ChatGPT Image Factory is a file exchange, not browser automation;
- image and video generation occur in the user-selected UI;
- FFmpeg variants, validation, timeline construction, and rendering are local;
- API keys are not returned to the browser.

## Safety

- project IDs are validated by the existing Pydantic contract;
- artifact routes reject traversal outside the selected project;
- subprocess commands are argument arrays;
- only the configured command template is passed through `FDE_LLM_COMMAND`;
- approved artifacts remain versioned and selective invalidation is preserved.

## Native media factory and renderer routes

Version 0.5 makes the Image and Video Factory panels route-aware. When a native provider such as Grok Build CLI is selected, Production shows a direct **Generate pending images/videos** action, generation ledger totals and a manual-packet fallback. When a UI provider is selected, the same panel switches to the export/import handoff.

The AI Orchestrator task editor filters providers by capability. The Providers tab exposes capabilities, health, native adapters and separate Custom CLI templates for structured and media work. The Composition Renderer task selects HyperFrames, FFmpeg or Offline Mock independently from AI generation.
