from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
