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


# Favicon and PWA assets — must be served from root
_FAVICON_FILES = [
    "favicon.ico", "favicon.svg", "favicon-96x96.png",
    "apple-touch-icon.png", "site.webmanifest",
    "web-app-manifest-192x192.png", "web-app-manifest-512x512.png",
]

@app.get("/{filename}")
def serve_root_file(filename: str):
    if filename in _FAVICON_FILES:
        return FileResponse(STATIC_DIR / filename)
    return FileResponse(STATIC_DIR / "client.html")
