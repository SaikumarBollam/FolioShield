# FolioShield — Streamlit UI + REST API (single image, two commands).
# Production target: Python 3.12. Terminate TLS at your reverse proxy;
# the built-in servers are not internet-facing on their own.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root runtime user; data/ and logs/ are volumes (see docker-compose).
RUN useradd --create-home --uid 10001 folioshield \
    && mkdir -p /app/data /app/logs \
    && chown -R folioshield:folioshield /app
USER folioshield

EXPOSE 8501 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/', timeout=4)" || exit 1

# Default: the Streamlit UI. Override with `python -m core.api` for the API.
CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.headless", "true", "--server.port", "8501", \
     "--server.address", "0.0.0.0", "--browser.gatherUsageStats", "false"]
