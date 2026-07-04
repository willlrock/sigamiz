#!/bin/bash
# Запуск бота в фоне
python3 bot/main.py &
# Запуск бэкенда (FastAPI) в основном процессе
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
