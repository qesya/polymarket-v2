FROM python:3.11-slim

# Security: run as non-root
RUN groupadd -r trader && useradd -r -g trader trader

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /app/data/models /app/logs && chown -R trader:trader /app

USER trader

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/metrics || exit 1

# Default: run the full system
CMD ["python", "main.py"]
