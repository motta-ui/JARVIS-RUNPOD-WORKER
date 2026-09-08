import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, CORS_ORIGINS, OUTPUTS_DIR, ASSETS_DIR, LORAS_DIR
from .database import init_db
from .engines.registry import persist_engine_snapshot
from .routers import health, projects, assets, gallery, jobs, engines, models, loras, settings, presets, workflows, cloud

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("jarvis")

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocorreu um erro interno no JARVIS. Consulta os logs do backend para detalhes."},
    )


@app.on_event("startup")
def on_startup():
    logger.info("A iniciar %s v%s...", APP_NAME, APP_VERSION)
    init_db()
    try:
        persist_engine_snapshot()
    except Exception:
        logger.exception("Falha ao gravar snapshot inicial dos engines (não crítico).")
    logger.info("Base de dados pronta. Engines registados.")


app.include_router(health.router)
app.include_router(projects.router)
app.include_router(assets.router)
app.include_router(gallery.router)
app.include_router(jobs.router)
app.include_router(engines.router)
app.include_router(models.router)
app.include_router(loras.router)
app.include_router(settings.router)
app.include_router(presets.router)
app.include_router(workflows.router)
app.include_router(cloud.router)

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/static-assets", StaticFiles(directory=str(ASSETS_DIR)), name="static-assets")
app.mount("/static-loras", StaticFiles(directory=str(LORAS_DIR)), name="static-loras")
