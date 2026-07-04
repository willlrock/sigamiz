#!/bin/bash

# Используем порт 8000 по умолчанию, если переменная $PORT пуста
TARGET_PORT=${PORT:-8000}

echo "Starting bot..."
python3 bot/main.py &

echo "Starting FastAPI on port $TARGET_PORT..."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port $TARGET_PORT
