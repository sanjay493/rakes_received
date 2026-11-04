FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    REQUIRE_AUTH=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runs as root because platform volumes mounted at /data are usually root-owned.

# Keep one worker: station/commodity mappings are cached in process memory, so
# extra workers would serve stale values after an edit on the /config page.
CMD exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 120
