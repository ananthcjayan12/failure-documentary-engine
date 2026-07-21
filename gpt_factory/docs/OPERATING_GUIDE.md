# Operating Guide

## Normal run

1. Export packet locally.
2. Upload the four packet files to a fresh conversation with the private GPT.
3. Send `RUN PRODUCTION PACKET` using the full command supplied in the packet.
4. When generation limits interrupt the run, later send `RESUME FACTORY`.
5. Download the final ZIP if the interface successfully exposes generated images to the file tool.
6. Import locally:

```bash
fde import-image-batch PROJECT_ID returned_images.zip
```

## Reliable fallback

The Custom GPT may be able to generate images but may not always expose them to Code Interpreter for a single ZIP. In that case:

- download completed images from the conversation or Images library,
- keep the asset ID at the beginning of each filename,
- zip the downloaded files locally,
- run the same `import-image-batch` command.

The importer automatically converts landscape images to 1600×900 PNG and maps them by asset ID.
