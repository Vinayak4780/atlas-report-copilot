"""FastAPI entry point: POST /chat, POST /ingest, GET /escalations, GET /health (+ GET /security-events)."""
import asyncio
import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.llm import LLMClient
from app.logging_setup import log_event, setup_logging
from app.models import ChatRequest, ChatResponse, Escalation, HealthResponse, IngestRequest, IngestResponse
from app.rag.embeddings import Embedder
from app.rag.ingest import ingest_directory
from app.rag.vectorstore import VectorStore
from app.repository import Repository
from app.service import ClientNotFound, CopilotService

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("atlas.api")
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.atlas_api_key:
        raise RuntimeError("ATLAS_API_KEY must be set")
    repo = Repository(settings)
    await run_in_threadpool(repo.wait_until_ready)
    embedder = await run_in_threadpool(Embedder, settings.embedding_model, settings.embedding_cache_dir)
    store = VectorStore(settings.qdrant_url, settings.qdrant_collection, embedder)
    for _ in range(30):
        if store.ping():
            break
        await asyncio.sleep(2)
    if store.count() == 0:
        log_event(logger, "auto_ingest_start")
        await run_in_threadpool(ingest_directory, settings.reports_dir, repo, store)
    state.update(repo=repo, store=store, service=CopilotService(settings, repo, store, LLMClient(settings)))
    log_event(logger, "startup_complete", llm_configured=bool(settings.groq_api_key), points=store.count())
    yield
    state.clear()


app = FastAPI(title="Project Atlas - Report Copilot API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.monotonic()
    trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    log_event(logger, "http_request", method=request.method, path=request.url.path, status=response.status_code,
              ms=int((time.monotonic() - t0) * 1000), trace_id=trace_id)
    return response


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logger.exception("unhandled_error")
    return JSONResponse(status_code=500, content={"detail": "Internal error. The request was logged."})


def require_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), settings.atlas_api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


Auth = Depends(require_api_key)


@app.post("/chat", response_model=ChatResponse, dependencies=[Auth])
async def chat(req: ChatRequest) -> ChatResponse:
    service: CopilotService = state["service"]
    try:
        return await asyncio.wait_for(run_in_threadpool(service.chat, req), timeout=settings.request_timeout_s)
    except ClientNotFound:
        raise HTTPException(status_code=404, detail="Unknown client_id")
    except asyncio.TimeoutError:
        log_event(logger, "chat_timeout", logging.WARNING, client_id=req.client_id)
        raise HTTPException(status_code=504, detail="The copilot took too long to answer. Please try again or "
                                                    "ask for an analyst.")


@app.post("/ingest", response_model=IngestResponse, dependencies=[Auth])
async def ingest(req: IngestRequest) -> IngestResponse:
    result = await run_in_threadpool(ingest_directory, settings.reports_dir, state["repo"], state["store"])
    state["service"].cache.clear()
    return IngestResponse(**result)


@app.get("/escalations", response_model=list[Escalation], dependencies=[Auth])
async def escalations(status: Literal["open", "in_progress", "closed"] | None = None,
                      limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
    return await run_in_threadpool(state["repo"].list_escalations, status, limit)


@app.get("/security-events", dependencies=[Auth])
async def security_events(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
    return await run_in_threadpool(state["repo"].list_security_events, limit)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    repo, store, service = state.get("repo"), state.get("store"), state.get("service")
    mysql_ok = bool(repo) and await run_in_threadpool(repo.ping)
    qdrant_ok = bool(store) and await run_in_threadpool(store.ping)
    points = await run_in_threadpool(store.count) if qdrant_ok else 0
    return HealthResponse(status="ok" if mysql_ok and qdrant_ok and points else "degraded", mysql=mysql_ok,
                          qdrant=qdrant_ok, vector_points=points, llm_configured=bool(settings.groq_api_key),
                          cache_entries=len(service.cache) if service else 0)
