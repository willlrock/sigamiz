FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Права на запуск
RUN chmod +x start.sh

# Запуск
CMD ["./start.sh"]
