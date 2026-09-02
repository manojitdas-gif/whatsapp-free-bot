# 100% Free 24/7 Cloud Dockerfile for WhatsApp Automation Engine
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV HEADLESS=true
ENV PORT=8080

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure Chromium browser is ready
RUN python3 -m playwright install chromium

# Copy all application files
COPY . .

# Expose cloud health port
EXPOSE 8080

# Start 24/7 WhatsApp engine
CMD ["python3", "-u", "whatsapp_web_engine.py"]
