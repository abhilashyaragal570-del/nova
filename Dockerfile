# Nova web app. Untested until Docker is installed: see the README.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so rebuilds are fast when only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a normal user. These are the folders Nova writes to, so a volume can
# be mounted on any of them.
RUN useradd --create-home --uid 1000 nova \
    && mkdir -p conversations workflow_data rag_data memory_data workspace logs \
    && chown -R nova:nova /app
USER nova

EXPOSE 8000

# One worker: a running workflow lives in the server's memory.
# Settings (GEMINI_API_KEY, NOVA_PASSWORD, ...) come from the environment.
CMD ["sh", "-c", "exec gunicorn web.server:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8000}"]