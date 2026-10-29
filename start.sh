#!/bin/bash
# Запуск на macOS / Linux: ./start.sh
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
[ -f models/face_recognition_sface_2021dec.onnx ] || python -m app.cli download-models
python run.py
