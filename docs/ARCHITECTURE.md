# Architecture

```text
Story brief
   │
   ├── Research Agent ──> source_dossier.json + claim_ledger.json
   │
   ├── Structure Agent ──> structure.json ──> HUMAN APPROVAL
   │
   ├── Script Agent ─────> script.json ─────> HUMAN APPROVAL
   │
   ├── Shot Planner ─────> 45–60 shot divisions
   │
   ├── Asset Optimizer ──> <=28 reusable master assets
   │                         │
   │                         ├── image prompts
   │                         ├── contact sheet PNG/PDF/HTML
   │                         └── HUMAN IMAGE REVIEW
   │
   ├── Grok Job Export ──> image-to-video prompts
   │                         │
   │                         └── HUMAN VIDEO REVIEW
   │
   ├── Footage Multiplier ─> crops, slow versions, plates, final frames
   │
   ├── Narration Import ──> audio + optional timestamps
   │
   └── Timeline/Renderer ─> preview.mp4 ─> picture_locked_base.mp4
```

## Persisted contracts

All important boundaries are Pydantic models in `fde/models.py`. The current JSON file in each stage is accompanied by versioned artifacts where the stage is LLM-generated.

## Provider boundary

`fde/agents.py` deliberately separates the pipeline from a specific LLM:

- `ManualAgent`: writes prompt/schema files and waits for JSON.
- `CommandAgent`: runs any command template supplied through `FDE_LLM_COMMAND`.
- `MockAgent`: deterministic offline fixtures.

Image and video generation remain manual watched-folder workflows, making the repository compatible with consumer subscriptions without browser automation or account-cookie handling.

## Dependency invalidation

An image change to `A07` invalidates:

- `asset:A07:image`
- `video_job:A07`
- `variants:A07`
- Timeline entries linked to A07’s shots

It does not invalidate the research, structure, script, shot plan, or unrelated assets.
