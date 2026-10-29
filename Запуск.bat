@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv (
  echo Создаю виртуальное окружение...
  python -m venv venv || (echo Установите Python 3.10+ с python.org и отметьте "Add to PATH" & pause & exit /b)
)
call venv\Scripts\activate
echo Устанавливаю зависимости...
pip install -q -r requirements.txt
if not exist models\face_recognition_sface_2021dec.onnx (
  echo Скачиваю нейросети для проверки лица...
  python -m app.cli download-models
)
start "" http://localhost:8000
python run.py
pause
