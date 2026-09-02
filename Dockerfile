# 100% Free 24/7 Cloud Dockerfile for WhatsApp Automation Engine
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV HEADLESS=true

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser
RUN playwright install chromium

# Copy application files
COPY . .

# Expose health port if required by cloud hosts
EXPOSE 8080

# Run supervisor watchdog 24/7
CMD ["python", "-u", "watchdog.py"]
