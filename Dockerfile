# 24/7 Cloud Webhook Bot for WhatsApp Automation Engine
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV PORT=10000

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Expose cloud port
EXPOSE 10000

# Start Cloud Webhook Engine (FastAPI on Uvicorn)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
