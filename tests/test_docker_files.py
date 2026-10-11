from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_lines(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_dockerfile_starts_gunicorn_with_one_worker():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "gunicorn web.server:app" in text
    assert "--workers 1" in text


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
    ):
        assert entry in lines, f".gitignore is missing {entry}"