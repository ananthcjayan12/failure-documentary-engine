# Setup in Five Minutes

1. In ChatGPT on the web, open **Explore GPTs** and choose **Create**.
2. Open the **Configure** view.
3. Name it `Documentary Image Factory` and paste the description from `GPT_CONFIG.json`.
4. Paste all of `GPT_INSTRUCTIONS.md` into Instructions.
5. Upload the six Markdown files from `knowledge/` as Knowledge.
6. Enable **Image Generation** and **Code Interpreter & Data Analysis**.
7. Add the conversation starters from `GPT_CONFIG.json`.
8. Save it as **Only me**.
9. Test with `templates/SMOKE_TEST_PACKET/` before using a full documentary.

For a real project, run:

```bash
fde export-image-factory PROJECT_ID
```

Upload the four packet files listed in its `UPLOAD_README.md`, then paste the command in `RUN_INSTRUCTIONS.md`.
