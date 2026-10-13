from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_lines(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_dockerfile_starts_uvicorn_with_one_process():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uvicorn web.fastapi_app:app" in text
    # A running workflow lives in the server's memory, so there must be only
    # one process. uvicorn runs one unless --workers is given.
    assert "--workers" not in text
    assert "gunicorn" not in text


def test_dockerfile_runs_as_a_normal_user():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER nova" in text


def test_dockerfile_never_copies_the_env_file():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY .env" not in text
    assert "ENV GEMINI_API_KEY" not in text
    assert "ENV NOVA_PASSWORD" not in text


def test_dockerfile_installs_requirements_before_copying_the_code():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert text.index("COPY requirements.txt") < text.index("COPY . .")


def test_dockerfile_sets_up_the_state_folder():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "NOVA_STATE_DIR=/app/state" in text
    # The folder is created before chown, so the normal user owns it and a
    # new named volume copies that ownership.
    mkdir_line = next(line for line in text.splitlines() if "mkdir -p" in line)
    assert " state" in mkdir_line
    assert text.index("mkdir -p") < text.index("chown -R nova:nova /app")


def test_compose_gives_the_state_folder_its_own_volume():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "- nova_state:/app/state" in text
    assert "NOVA_STATE_DIR: /app/state" in text
    assert "\n  nova_state:" in text


def test_dockerignore_keeps_secrets_and_personal_data_out_of_the_image():
    lines = read_lines(".dockerignore")
    for entry in (
        ".env",
        "venv/",
        "history.json",
        "personality.json",
        "conversations/",
        "workspace/",
        "workflow_data/",
        "rag_data/",
        "memory_data/",
        "state/",
        "logs/",
    ):
        assert entry in lines, f".dockerignore is missing {entry}"


def test_gitignore_lists_each_private_path_on_its_own_line():
    lines = read_lines(".gitignore")
    for entry in (
        ".env",
        "venv/",
        "logs/",
        "history.json",
        "personality.json",
        "conversations/",
        "workspace/",
        "workflow_data/",
        "rag_data/",
        "memory_data/",
        "state/",
    ):
        assert entry in lines, f".gitignore is missing {entry}"