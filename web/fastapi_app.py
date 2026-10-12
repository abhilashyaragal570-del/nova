"""Nova's FastAPI app.

The /chat, /memory, /documents, /system, /conversations, /approvals,
/workflows, /api/usage and /api/agents routes are FastAPI. The only routes
still served by the Flask app in web/server.py are the chat page itself and
the /usage page. Flask is mounted at the end so the FastAPI routes are matched
first, and it keeps doing its own password check for those two pages.

State is shared with Flask by going through the web.server module at call
time: its conversation store, its current personality, its approval broker,
its workflow manager and its tool registry. Tests replace those.

The API docs (/docs, /redoc and /openapi.json) list every FastAPI route and can
try them. They sit behind the same password as everything else.
Run the app with: uvicorn web.fastapi_app:app --port 8000
"""
import hmac
import json
import logging
import os
import queue
import threading
from typing import Annotated, Any

from a2wsgi import WSGIMiddleware
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google.genai import errors
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from agents.definitions import AgentError, get_agent, list_agents
from agents.factory import new_agent_chat
from agents.history import clear_messages, load_messages, save_messages, to_contents
from app.chat import fact_store
from app.tool_loop import run_turn
from app.usage_log import get_log_path, log_turn
from app.usage_report import read_all_entries, summarize
from memory.conversation_store import NEW_TITLE
from rag.embedder import EmbedError
from rag.index import RagIndexError
from rag.ingest import MAX_FILE_BYTES, IngestError, add_upload
from web import server as flask_server
from web.workflow_runs import Busy
from workflows.store import StoreError

logger = logging.getLogger(__name__)

# Room for one file plus the form overhead, the same limit Flask used.
MAX_REQUEST_BYTES = MAX_FILE_BYTES + 100_000

# Builds an agent's chat session. A module variable so tests can replace it
# with a fake that never calls the real API.
chat_factory = new_agent_chat

security = HTTPBasic(auto_error=False)


def require_password(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
) -> None:
    password = os.environ.get("NOVA_PASSWORD")
    if not password:
        raise HTTPException(
            503, "NOVA_PASSWORD is not set, so the server is refusing all requests."
        )
    if credentials and hmac.compare_digest(
        credentials.password.encode(), password.encode()
    ):
        return
    raise HTTPException(
        401, "Password required", headers={"WWW-Authenticate": 'Basic realm="Nova"'}
    )


# FastAPI's own docs pages are switched off because it adds them without the
# password check. They are added back below as normal routes, which do get it.
app = FastAPI(
    title="Nova",
    dependencies=[Depends(require_password)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class FactIn(BaseModel):
    fact: str


class Fact(BaseModel):
    id: str
    text: str
    saved: str | None = None


class Ok(BaseModel):
    ok: bool


class Document(BaseModel):
    source: str
    chunks: int
    model: str | None = None


class Uploaded(BaseModel):
    source: str
    chunks: int


class SystemIn(BaseModel):
    prompt: str


class Prompt(BaseModel):
    prompt: str


class ConversationSummary(BaseModel):
    id: str
    title: str


class ApprovalIn(BaseModel):
    # Any value is accepted on purpose: only the real JSON value true approves.
    approved: Any = None


class WorkflowIn(BaseModel):
    # Any value is accepted on purpose: the route checks the goal itself, and
    # only the real JSON value true turns on tools that change things.
    goal: Any = None
    write_tools: Any = None


class RunId(BaseModel):
    id: str


class AgentInfo(BaseModel):
    name: str
    description: str
    tools: list[str]


class ChatIn(BaseModel):
    # Any value is accepted on purpose: the route checks the message itself.
    message: Any = None


class MainChatIn(BaseModel):
    # Any value is accepted on purpose: the route checks both fields itself.
    message: Any = None
    conversation: Any = None


# Errors keep the {"error": "..."} shape that web/index.html reads.
@app.exception_handler(HTTPException)
async def http_error(request, exc: HTTPException):
    return JSONResponse(
        {"error": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def bad_request(request, exc: RequestValidationError):
    # Flask gave each of these routes its own message for a bad body.
    path = request.url.path
    if path == "/system":
        message = "Empty personality"
    elif path == "/workflows":
        message = "Empty goal"
    elif path.startswith("/approvals") or path.startswith("/workflows/"):
        message = "Invalid request"
    elif path == "/chat" or path.startswith("/api/agents"):
        message = "Empty message"
    else:
        message = "fact must be text"
    return JSONResponse({"error": message}, status_code=400)


# ---------- API docs ----------
# Behind the password like every other route. The browser asks for the login
# once and then sends it with the page's own requests, so "Try it out" works.
# They are left out of the schema, so they don't list themselves.


@app.get("/openapi.json", include_in_schema=False)
def openapi_schema():
    return app.openapi()


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Nova - API docs")


@app.get("/redoc", include_in_schema=False)
def redoc_page():
    return get_redoc_html(openapi_url="/openapi.json", title="Nova - API docs")


# ---------- memory ----------


@app.get("/memory", response_model=list[Fact])
def list_memory():
    return fact_store.list()


@app.post("/memory", response_model=Fact, status_code=201)
def add_memory(body: FactIn):
    try:
        return fact_store.add(body.fact)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(503, "Could not save the fact")


@app.delete("/memory/{fact_id}", response_model=Ok)
def delete_memory(fact_id: str):
    try:
        removed = fact_store.remove(fact_id)
    except OSError:
        raise HTTPException(503, "Could not update memory")
    if not removed:
        raise HTTPException(404, "Not found")
    return {"ok": True}


# ---------- documents ----------
# These call get_document_index() and get_embedder() on web.server, so there is
# still one index, and tests can replace both functions with fakes.


@app.get("/documents", response_model=list[Document])
def list_documents():
    try:
        return flask_server.get_document_index().list_documents()
    except RagIndexError as e:
        raise HTTPException(503, str(e))


async def _read_limited_body(request: Request) -> bytes:
    """Read the request body, refusing it as soon as it passes the limit."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            raise HTTPException(
                413,
                f"That upload is too large (max {MAX_FILE_BYTES // 1000} KB per file)",
            )
    return bytes(body)


def _replay(body: bytes):
    """A receive() that hands the already-read body to a new Request."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _store_upload(filename: str, data: bytes) -> dict:
    # Blocking work (embedding calls Gemini), so it runs in a thread.
    return add_upload(
        filename, data, flask_server.get_document_index(), flask_server.get_embedder()
    )


# The route reads the request itself, so /docs needs this description of the form.
UPLOAD_FORM_DOCS = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            }
        },
    }
}


@app.post(
    "/documents",
    response_model=Uploaded,
    status_code=201,
    openapi_extra=UPLOAD_FORM_DOCS,
)
async def upload_document(request: Request):
    # The password check has already run (it is a dependency of the whole
    # app), and the body is size-limited before anything parses it.
    body = await _read_limited_body(request)
    form = await Request(request.scope, _replay(body)).form()
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(400, "Choose a file to upload")
        filename = upload.filename
        # Read one byte past the limit so a too-big file is noticed, not truncated.
        data = await upload.read(MAX_FILE_BYTES + 1)
    finally:
        await form.close()
    try:
        return await run_in_threadpool(_store_upload, filename, data)
    except IngestError as e:
        raise HTTPException(400, str(e))
    except EmbedError as e:
        raise HTTPException(502, f"Could not read the file for search: {e}")
    except RagIndexError as e:
        raise HTTPException(409, str(e))


@app.delete("/documents/{source}", response_model=Ok)
def remove_document(source: str):
    try:
        removed = flask_server.get_document_index().remove_document(source)
    except RagIndexError as e:
        raise HTTPException(503, str(e))
    if not removed:
        raise HTTPException(404, "Not found")
    return {"ok": True}


# ---------- personality ----------


@app.get("/system", response_model=Prompt)
def get_system():
    return {"prompt": flask_server.current_prompt}


@app.post("/system", response_model=Prompt)
def set_system(body: SystemIn):
    new_prompt = body.prompt.strip()
    if not new_prompt:
        raise HTTPException(400, "Empty personality")
    try:
        # Save first, so a failed save does not leave the live prompt changed.
        flask_server.save_prompt(new_prompt)
    except OSError:
        raise HTTPException(503, "Could not save the personality")
    flask_server.current_prompt = new_prompt
    return {"prompt": new_prompt}


# ---------- conversations ----------


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations():
    return flask_server.store.list_conversations()


@app.post("/conversations", response_model=ConversationSummary)
def create_conversation():
    cid = flask_server.store.create()
    return {"id": cid, "title": NEW_TITLE}


@app.get("/conversations/{cid}")
def get_conversation(cid: str):
    conv = flask_server.store.load(cid)
    if conv is None:
        raise HTTPException(404, "Not found")
    return conv


@app.delete("/conversations/{cid}", response_model=Ok)
def delete_conversation(cid: str):
    if not flask_server.store.delete(cid):
        raise HTTPException(404, "Not found")
    return {"ok": True}


# ---------- chat ----------
# The reply is streamed. run_turn blocks, so it runs in a worker thread and
# hands text over a queue. The conversation is saved when the stream ends,
# including when the browser stops reading it (the Stop button).


@app.post("/chat", response_class=PlainTextResponse)
def chat(body: MainChatIn | None = None):
    message = body.message if body is not None else None
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(400, "Empty message")
    user_input = message.strip()

    store = flask_server.store
    main_id = flask_server.MAIN_ID
    cid = (body.conversation if body is not None else None) or main_id
    conv = store.load(cid) if isinstance(cid, str) else None
    if conv is None:
        raise HTTPException(404, "Conversation not found")

    messages = conv["messages"]
    title = conv["title"]
    if cid != main_id and title == NEW_TITLE:
        title = user_input[:40]
    registry = flask_server.web_registry
    chat_session = flask_server.new_chat(messages, flask_server.current_prompt)

    def generate():
        chunks = queue.Queue()
        outcome = {}

        def worker():
            try:
                outcome["result"] = run_turn(
                    chat_session, user_input, registry, on_text=chunks.put
                )
                flask_server.log_turn(outcome["result"], source="web")
            except errors.APIError as e:
                outcome["error"] = e
            finally:
                chunks.put(None)

        threading.Thread(target=worker, daemon=True).start()

        reply = ""
        try:
            while True:
                text = chunks.get()
                if text is None:
                    break
                reply += text
                yield text
            error = outcome.get("error")
            if error is not None:
                yield (
                    f"\n[Nova couldn't reply: error {error.code}. "
                    "Try again in a moment.]"
                )
                return
        finally:
            if reply:
                messages.append({"role": "user", "text": user_input})
                messages.append({"role": "model", "text": reply})
                store.save(cid, title, messages)

        result = outcome.get("result")
        if result is None:
            return
        if not reply:
            print(
                "EMPTY REPLY: tool_calls =",
                result.tool_calls,
                "hit_round_limit =",
                result.hit_round_limit,
                flush=True,
            )
        if result.total_tokens:
            info = {
                "prompt": result.prompt_tokens,
                "reply": result.reply_tokens,
                "total": result.total_tokens,
            }
            yield "\x00" + json.dumps(info)

    return StreamingResponse(generate(), media_type="text/plain")


# ---------- tool approvals ----------


@app.get("/approvals", response_model=list[dict[str, Any]])
def list_approvals():
    return flask_server.approvals.list_pending()


@app.post("/approvals/{approval_id}", response_model=Ok)
def answer_approval(approval_id: str, body: ApprovalIn | None = None):
    approved = body is not None and body.approved is True
    if not flask_server.approvals.resolve(approval_id, approved):
        raise HTTPException(404, "Unknown or already answered")
    return {"ok": True}


# ---------- workflows ----------
# These use flask_server.workflow_manager, so there is still one manager and
# only one workflow can plan or run at a time.


@app.post("/workflows", response_model=RunId, status_code=202)
def start_workflow(body: WorkflowIn | None = None):
    goal = body.goal if body is not None else None
    if not isinstance(goal, str) or not goal.strip():
        raise HTTPException(400, "Empty goal")
    write_tools = body.write_tools is True
    try:
        run_id = flask_server.workflow_manager.start(goal, write_tools)
    except Busy as e:
        raise HTTPException(409, str(e))
    return {"id": run_id}


@app.get("/workflows", response_model=list[dict[str, Any]])
def list_workflows():
    try:
        return flask_server.workflow_manager.list_saved()
    except StoreError as e:
        raise HTTPException(503, str(e))


@app.get("/workflows/current", response_model=dict[str, Any])
def current_workflow():
    return flask_server.workflow_manager.snapshot() or {"state": "idle"}


@app.post("/workflows/{run_id}/approve", response_model=Ok)
def answer_workflow_plan(run_id: str, body: ApprovalIn | None = None):
    approved = body is not None and body.approved is True
    if not flask_server.workflow_manager.approve(run_id, approved):
        raise HTTPException(404, "No plan is waiting under that id")
    return {"ok": True}


@app.post("/workflows/{run_id}/cancel", response_model=Ok)
def cancel_workflow(run_id: str):
    if not flask_server.workflow_manager.cancel(run_id):
        raise HTTPException(404, "Nothing to cancel under that id")
    return {"ok": True}


@app.post("/workflows/{workflow_id}/resume", response_model=RunId, status_code=202)
def resume_workflow_route(workflow_id: str):
    try:
        run_id = flask_server.workflow_manager.resume(workflow_id)
    except Busy as e:
        raise HTTPException(409, str(e))
    except StoreError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": run_id}


# ---------- usage report ----------
# Only the JSON route moves. The /usage page just serves usage.html, so Flask
# keeps doing that through the mount.


@app.get("/api/usage", response_model=dict[str, Any])
def api_usage():
    entries, skipped = read_all_entries(get_log_path())
    summary = summarize(entries)
    summary["skipped"] = skipped
    return summary


# ---------- specialized agents ----------
# Each agent gets a restricted copy of flask_server.web_registry, so a tool that
# needs approval still shows the same Approve / Deny card as chat.


def _find_agent(name: str):
    try:
        return get_agent(name)
    except AgentError:
        return None


@app.get("/api/agents", response_model=list[AgentInfo])
def api_list_agents():
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "tools": sorted(spec.tools),
        }
        for spec in list_agents()
    ]


@app.get("/api/agents/{name}/history", response_model=dict[str, Any])
def api_agent_history(name: str):
    spec = _find_agent(name)
    if spec is None:
        raise HTTPException(404, "Unknown agent")
    return {
        "agent": spec.name,
        "messages": load_messages(flask_server.store, spec),
    }


@app.delete("/api/agents/{name}/history", response_model=Ok)
def api_agent_clear(name: str):
    spec = _find_agent(name)
    if spec is None:
        raise HTTPException(404, "Unknown agent")
    clear_messages(flask_server.store, spec)
    return {"ok": True}


@app.post("/api/agents/{name}/chat", response_class=PlainTextResponse)
def api_agent_chat(name: str, body: ChatIn | None = None):
    spec = _find_agent(name)
    if spec is None:
        raise HTTPException(404, "Unknown agent")
    user_input = body.message if body is not None else None
    if not isinstance(user_input, str) or not user_input.strip():
        raise HTTPException(400, "Empty message")
    user_input = user_input.strip()

    store = flask_server.store
    messages = load_messages(store, spec)
    try:
        chat_session, registry = chat_factory(
            flask_server.llm_client,
            flask_server.MODEL_NAME,
            spec,
            flask_server.web_registry,
            to_contents(messages),
        )
    except AgentError as e:
        raise HTTPException(500, str(e))

    def generate():
        # run_turn blocks, so it runs in a thread and hands text over a queue.
        chunks = queue.Queue()
        outcome = {}

        def worker():
            try:
                outcome["result"] = run_turn(
                    chat_session, user_input, registry, on_text=chunks.put
                )
                log_turn(outcome["result"], source=f"web-agent:{spec.name}")
            except errors.APIError as e:
                outcome["error"] = e
            finally:
                chunks.put(None)

        threading.Thread(target=worker, daemon=True).start()

        reply = ""
        try:
            while True:
                text = chunks.get()
                if text is None:
                    break
                reply += text
                yield text
            error = outcome.get("error")
            if error is not None:
                yield (
                    f"\n[{spec.name} couldn't reply: error {error.code}. "
                    "Try again in a moment.]"
                )
                return
        finally:
            if reply:
                messages.append({"role": "user", "text": user_input})
                messages.append({"role": "model", "text": reply})
                try:
                    save_messages(store, spec, messages)
                except Exception:
                    logger.exception("Could not save the %s conversation", spec.name)

        result = outcome.get("result")
        if result is not None and result.total_tokens:
            info = {
                "prompt": result.prompt_tokens,
                "reply": result.reply_tokens,
                "total": result.total_tokens,
            }
            yield "\x00" + json.dumps(info)

    return StreamingResponse(generate(), media_type="text/plain")


# Must stay last: a mount at "/" matches every path that no route above took.
app.mount("/", WSGIMiddleware(flask_server.app))