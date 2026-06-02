from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .database import create_db
from .routers import admin, client, public

app = FastAPI(title="Telex", docs_url=None, redoc_url=None)

# Trust X-Forwarded-For from nginx (localhost only)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["127.0.0.1", "::1"])

app.include_router(client.router)
app.include_router(admin.router)
app.include_router(public.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def on_startup():
    create_db()


@app.get("/")
def serve_admin():
    return FileResponse(STATIC_DIR / "index.html")


# Catch-all: /{identifier} → per-client send page
# Must be last so it doesn't shadow /api/*, /static/*, /
@app.get("/{identifier}")
def serve_client_page(identifier: str):
    return FileResponse(STATIC_DIR / "client.html")
