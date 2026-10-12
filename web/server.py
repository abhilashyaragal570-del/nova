"""Shared state for Nova's web app, plus the two pages Flask still serves.

Every API route lives in web/fastapi_app.py. This module holds what those
routes share: the conversation store, the tool registry, the approval broker,
the workflow manager, the personality and the document index. It also has a
small Flask app that serves only the chat page (/) and the usage page (/usage).
FastAPI mounts that Flask app at the end, so both pages sit behind the same
password.

Start the web app with:
    uvicorn web.fastapi_app:app --port 8000
"""
import hmac
import json
import os
from pathlib import Path

from flask import Flask, Response, request, send_from_directory

# new_chat, log_turn, MAIN_ID, llm_client and MODEL_NAME are not used in this
# file. web/fastapi_app.py reads them from here at call time, and tests replace
# them here.
from app.chat import new_chat, SYSTEM_PROMPT, fact_store
from app.llm import ask as model
from app.llm import client as llm_client, MODEL as MODEL_NAME
from app.usage_log import log_turn
from memory.conversation_store import MAIN_ID
from memory.store_factory import create_store
from rag.embedder import GeminiEmbedder
from rag.index_factory import create_document_index
from tools.api_request import ApiRequestTool
from tools.calculator import CalculatorTool
from tools.document_search import DocumentSearchTool
from tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from tools.memory_tools import ForgetTool, ListMemoriesTool, RememberTool
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from tools.web_search import WebSearchTool
from web.approvals import ApprovalBroker
from web.workflow_runs import WorkflowManager
from workflows.executor import WorkflowExecutor
from workflows.gemini_planner import make_planner
from workflows.store_factory import create_workflow_store

WEB_DIR = Path(__file__).parent
PROMPT_FILE = Path("personality.json")
store = create_store()

# Only the two pages are Flask now: / and /usage.
app = Flask(__name__)

# Tools that need approval pause until the browser answers Approve or Deny
# (see web/approvals.py). No answer within the timeout counts as a denial.
approvals = ApprovalBroker()
web_registry = ToolRegistry(policy=ToolPolicy(confirm=approvals.confirm))
for _tool in (
    CalculatorTool(),
    WebSearchTool(),
    ListFilesTool(),
    ReadFileTool(),
    WriteFileTool(),
    ApiRequestTool(),
    DocumentSearchTool(),
    # Long-term memory: remember and forget need approval, like write_file.
    RememberTool(fact_store),
    ForgetTool(fact_store),
    ListMemoriesTool(fact_store),
):
    web_registry.register(_tool)

# Workflows share web_registry, so a write step shows the same Approve / Deny card as chat.
WORKFLOW_DEADLINE_SECONDS = 600.0
workflow_manager = WorkflowManager(
    make_planner=lambda write_tools: make_planner(
        web_registry, generate=model, read_only_only=not write_tools, critic=True
    ),
    make_executor=lambda on_event, cancel: WorkflowExecutor(
        web_registry,
        on_event=on_event,
        cancel_event=cancel,
        model=model,
        deadline_seconds=WORKFLOW_DEADLINE_SECONDS,
    ),
    make_store=create_workflow_store,
)

# The document index is created on first use, and the embedder on each
# upload. Tests replace these two functions with fakes.
_document_index = None


def get_document_index():
    global _document_index
    if _document_index is None:
        _document_index = create_document_index()
    return _document_index


def get_embedder():
    return GeminiEmbedder()


@app.before_request
def require_password():
    password = os.environ.get("NOVA_PASSWORD")
    if not password:
        return Response(
            "NOVA_PASSWORD is not set, so the server is refusing all requests.",
            503,
        )
    auth = request.authorization
    if auth and hmac.compare_digest(
        (auth.password or "").encode(), password.encode()
    ):
        return None
    return Response(
        "Password required", 401, {"WWW-Authenticate": 'Basic realm="Nova"'}
    )


def load_prompt():
    try:
        data = json.loads(PROMPT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return SYSTEM_PROMPT
    return data.get("prompt") or SYSTEM_PROMPT


def save_prompt(prompt):
    PROMPT_FILE.write_text(
        json.dumps({"prompt": prompt}, ensure_ascii=False), encoding="utf-8"
    )


current_prompt = load_prompt()


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/usage")
def usage_page():
    return send_from_directory(WEB_DIR, "usage.html")