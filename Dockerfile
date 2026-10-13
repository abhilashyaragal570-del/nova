# Nova web app. Built and run with uvicorn: see the README for the status.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# NOVA_STATE_DIR puts history.json and personality.json in /app/state, so one
# volume can keep both.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NOVA_STATE_DIR=/app/state

WORKDIR /app

# Install dependencies first so rebuilds are fast when only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a normal user. These are the folders Nova writes to, so a volume can
# be mounted on any of them.
RUN useradd --create-home --uid 1000 nova \
    && mkdir -p conversations workflow_data rag_data memory_data workspace logs state \
    && chown -R nova:nova /app
USER nova

EXPOSE 8000

# One worker: a running workflow lives in the server's memory. uvicorn runs a
# single worker unless told otherwise.
# Settings (GEMINI_API_KEY, NOVA_PASSWORD, ...) come from the environment.
CMD ["sh", "-c", "exec uvicorn web.fastapi_app:app --host 0.0.0.0 --port ${PORT:-8000}"]