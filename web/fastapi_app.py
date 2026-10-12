"""Nova's FastAPI app.

The three /memory routes are FastAPI. Every other route is still the Flask app
in web/server.py, mounted at the end so the FastAPI routes are matched first.
Flask keeps doing its own password check for the routes it serves.

FastAPI also builds a /docs page that lists the FastAPI routes and can try them.
Run it with: uvicorn web.fastapi_app:app --port 8001
"""
import hmac
import os
from typing import Annotated

from a2wsgi import WSGIMiddleware
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.chat import fact_store
from web.server import app as flask_app

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


app = FastAPI(title="Nova", dependencies=[Depends(require_password)])


class FactIn(BaseModel):
    fact: str


class Fact(BaseModel):
    id: str
    text: str
    saved: str | None = None


class Ok(BaseModel):
    ok: bool


# Errors keep the {"error": "..."} shape that web/index.html reads.
@app.exception_handler(HTTPException)
async def http_error(request, exc: HTTPException):
    return JSONResponse(
        {"error": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def bad_request(request, exc: RequestValidationError):
    # Only /memory has a request body in FastAPI so far. Flask answered a
    # missing or non-text fact with this same message and a 400.
    return JSONResponse({"error": "fact must be text"}, status_code=400)


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


# Must stay last: a mount at "/" matches every path that no route above took.
app.mount("/", WSGIMiddleware(flask_app))