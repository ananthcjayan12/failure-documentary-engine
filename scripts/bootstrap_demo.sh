#!/usr/bin/env bash
set -euo pipefail
python -m fde.cli demo mh370-demo
python -m fde.cli status mh370-demo
python -m fde.cli contact-sheet mh370-demo
