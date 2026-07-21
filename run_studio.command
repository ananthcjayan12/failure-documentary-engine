#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
elif ! .venv/bin/python -c "import fde" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -e .
fi

if command -v npm >/dev/null 2>&1 && [ ! -x node_modules/.bin/hyperframes ]; then
  echo "Installing the pinned HyperFrames runtime…"
  npm install || echo "HyperFrames installation failed; the Studio can still use the FFmpeg fallback."
fi

URL="http://127.0.0.1:8765"
(
  sleep 2
  if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
) >/dev/null 2>&1 &

exec .venv/bin/python -m fde studio --host 127.0.0.1 --port 8765
