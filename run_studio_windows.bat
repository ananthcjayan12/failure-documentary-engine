@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -e .
)
if not exist node_modules\.bin\hyperframes.cmd (
  where npm >nul 2>nul && npm install
)
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m fde studio --host 127.0.0.1 --port 8765
