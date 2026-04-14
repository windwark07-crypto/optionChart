@echo off
cd /d "%~dp0"

REM 가상환경이 있으면 활성화
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python main.py
