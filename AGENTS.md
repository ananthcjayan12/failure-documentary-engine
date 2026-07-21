# Codex Working Rules

## Scope
This repository builds a human-reviewed failure-investigation documentary pipeline.

## Non-negotiable contracts
- Do not merge chapters, shots, and master assets into one concept.
- A project must not exceed `maximum_master_assets` unless an explicit override exists.
- Approved artifacts are immutable; create a new version instead of overwriting.
- Changing an asset invalidates only that asset, its video job, related variants, and linked timeline entries.
- Every narration segment must have shot coverage.
- Every factual narration segment should link to claim IDs when research is enabled.
- Stop at manual review gates; never auto-approve.
- Grok/other image-video services are human-in-the-loop adapters by default.
- Do not use unofficial browser-session scraping.

## Style
- Python 3.10+ with type hints.
- Pydantic models for persisted JSON contracts.
- Small modules and deterministic functions where practical.
- External commands go through `fde.media.run_command`.
- Tests must not require network access, Grok, Codex, or FFmpeg.

## Verification
Run:

```bash
pytest
python -m fde.cli --help
```
