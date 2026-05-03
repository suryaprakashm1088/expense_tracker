FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better layer caching — only reinstalls if requirements change)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create persistent data directory for SQLite
RUN mkdir -p /data

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chown -R appuser:appuser /data

USER appuser

# Expose the gunicorn port
EXPOSE 5001

# Docker health check — hits the /health route every 30 seconds
HEALTHCHECK --interval=30s \
            --timeout=10s \
            --start-period=40s \
            --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1

# Start with gunicorn (production WSGI server — never use flask dev server in prod)
# NOTE: workers=1 is intentional.
# Prometheus counters live in process memory. With >1 workers, each process
# accumulates its own counts and /metrics only returns the scraping worker's
# values — so Grafana sees a fraction of real events (or 0).
# 1 worker + 4 threads gives full concurrency for I/O-bound Flask routes
# while keeping all counters in a single shared process.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "app:app"]
