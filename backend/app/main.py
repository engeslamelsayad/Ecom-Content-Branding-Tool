"""FastAPI application: API plus the built dashboard, served as one service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_db
from .routers import auth, runs, tools, workspace
from .security import ensure_seed_owner
from .skill_engine import registry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
)
log = logging.getLogger("ecbt")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await ensure_seed_owner(db)

    skills = registry.available()
    log.info("skills loaded: %s", ", ".join(skills) or "NONE")
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY is unset — generation will fail until it is set.")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json")

app.include_router(auth.router)
# runs first: it registers POST /api/brands/{id}/assets, which workspace's
# generic POST /api/brands/{id}/{resource} would otherwise shadow.
app.include_router(runs.router)
app.include_router(workspace.router)
app.include_router(tools.router)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "skills": registry.available(),
        "anthropic_key": bool(settings.anthropic_api_key),
        "models": {"deep": settings.model_deep, "fast": settings.model_fast},
    }


@app.post("/api/skills/reload")
async def reload_skills():
    """Pick up edited Markdown without a restart (a redeploy does this anyway)."""
    registry.reload()
    return {"ok": True, "skills": registry.available()}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "حصل خطأ غير متوقع في السيرفر"}, status_code=500)


# --- Static dashboard ------------------------------------------------------
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Single-page app: every non-API path resolves to the shell."""
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def no_build():
        return JSONResponse(
            {"detail": "الواجهة لسه مش مبنية. شغّل: cd frontend && npm install && npm run build"},
            status_code=503,
        )
