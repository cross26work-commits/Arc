from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import initialize_database
from app.projects.router import router as projects_router
from app.indexer.router import router as indexer_router
from app.analyzer.router import router as analyzer_router
from app.dependencies.router import router as dependencies_router


app = FastAPI(
    title="Arc Core",
    version="0.1.0",
    description="Master Ryuji専用 AI開発長 Arc のローカルCore",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(indexer_router)
app.include_router(analyzer_router)
app.include_router(dependencies_router)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "Arc Core",
        "version": "0.1.0",
        "mode": "local",
        "platform_support": ["macOS", "Windows"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
