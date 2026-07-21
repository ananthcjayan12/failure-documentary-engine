# Documentary Image Factory — Ready-to-Install Custom GPT Package

This folder contains everything needed to create the private Custom GPT.

## Fastest setup

1. Open ChatGPT on the web → Explore GPTs → Create.
2. In Configure, use the name and description in `GPT_CONFIG.json`.
3. Paste `GPT_INSTRUCTIONS.md` into Instructions.
4. Upload all six files from `knowledge/`.
5. Enable Image Generation and Code Interpreter & Data Analysis.
6. Add the four conversation starters from `GPT_CONFIG.json`.
7. Save as **Only me**.
8. Upload the four files in `templates/SMOKE_TEST_PACKET/` and send its run instruction.

The optional `BUILDER_PROMPT.txt` can be pasted into the conversational GPT Builder, but the Configure method is more deterministic.

## Connect it to the local engine

```bash
fde export-image-factory PROJECT_ID
```

Upload the generated packet to the GPT. After downloading or locally zipping the output images:

```bash
fde import-image-batch PROJECT_ID /path/to/returned_images.zip
```
