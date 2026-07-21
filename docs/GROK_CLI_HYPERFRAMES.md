# Grok CLI media and HyperFrames runtime

Version 0.5 separates the production system into three capability layers:

1. **Structured reasoning** — research, structure, script, shot planning, prompt writing and QA.
2. **Media generation** — still images, image-to-video clips and optional external audio.
3. **Deterministic rendering** — HyperFrames or FFmpeg operating only on approved local artifacts.

This separation allows the same provider to participate in several layers without coupling the pipeline to one vendor.

## Grok Build CLI adapter

The `grok_cli` provider advertises three capabilities:

```text
structured · image · video
```

Authenticate once:

```bash
grok login
fde doctor
```

For structured tasks, the adapter starts a bounded headless turn, supplies the Pydantic JSON Schema, disables unrelated tools, reconstructs streaming text and validates the returned JSON before the pipeline accepts it.

For image and video tasks, the adapter:

- asks Grok to invoke the relevant Imagine tool exactly once;
- passes the approved still as the image-to-video reference;
- records the complete streaming JSON output;
- captures returned local paths or URLs;
- scans the project and Grok directories for newly created files;
- imports the result into the existing asset/version system;
- retries only the failed asset;
- falls back to the configured compatible provider.

Raw output and generation metadata are stored per version:

```text
08_generated_images/generation/A01/v01/
10_generated_videos/generation/A01/v01/
```

The batch-level resumability ledger is:

```text
generation_state.json
generation_report.json
```

Running the same generation action again preserves successful or approved assets and continues with pending exceptions.

## Any-provider task routing

Every task declares one required capability:

```text
structured · image · video · audio · render
```

The route editor only displays providers that support that capability. A route contains the primary provider/model, retry policy, timeout and compatible fallback provider/model.

Included adapters are:

- Codex CLI
- Claude Code
- Gemini CLI
- Grok Build CLI
- Custom CLI
- ChatGPT UI
- Grok UI
- Manual Upload
- HyperFrames
- FFmpeg
- Offline Mock

The **Custom CLI Adapter** makes future providers usable without changing pipeline code. Structured commands support:

```text
{prompt} {output} {model} {reasoning} {temperature} {timeout} {stage}
```

Media commands support:

```text
{prompt} {output} {reference} {model} {duration} {aspect_ratio} {cwd}
```

The routed structured agent can cross provider families during fallback. For example, Claude Code may be primary while Grok CLI or the offline mock is fallback.

## HyperFrames

The repository pins:

```text
hyperframes 0.7.62
gsap 3.13.0
```

Install the runtime:

```bash
npm install
npm run doctor
```

The timeline compiler writes ordinary inspectable HTML. Each timeline item is a deterministic `.clip`; visual state is recomputed from the `hf-seek` event, so browser preview and rendered frames use the same clock.

Before rendering, the system runs the HyperFrames linter. Long documentaries are split at timeline-entry boundaries into resumable chunks. Completed chunks are validated with FFprobe and reused after interruption. FFmpeg concatenates the chunks and attaches the master narration. The final report is written beside the output:

```text
hyperframes-render-report.json
hyperframes-lint.log
hyperframes-concat.log
hyperframes-mux.log
```

If HyperFrames fails and the selected fallback is FFmpeg, the pipeline automatically uses the deterministic FFmpeg renderer instead.

## Useful commands

```bash
# Generate all pending stills with the configured image route
fde generate-media PROJECT image

# Generate selected stills again
fde generate-media PROJECT image --asset-ids A03,A11 --force

# Create animation jobs and generate pending clips
fde video-jobs PROJECT
fde generate-media PROJECT video

# Render using the route selected in AI Orchestrator
fde render-preview PROJECT
fde render-final-base PROJECT
```
