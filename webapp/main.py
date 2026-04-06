import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from routers import api_router, web_router
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

app = FastAPI(title="FinOps Platform")

# Cross-Origin Resource Sharing (CORS)
# Restrict to origins listed in CORS_ORIGINS (comma-separated), default deny-all
# https://fastapi.tiangolo.com/tutorial/cors/
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_API_KEY = os.getenv("APP_API_KEY", "")

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # API-key auth: all requests must carry X-API-Key matching APP_API_KEY env-var.
    # Whitelist the UI routes, static files and health checks.
    if _API_KEY and _API_KEY != "disabled":
        path = request.url.path
        if not (path.startswith("/api/") or path.startswith("/metrics/")):
             # Allowed UI/Static routes
             return await call_next(request)

        key = request.headers.get("X-API-Key", "")
        if key != _API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)}
    )

app.mount("/static", StaticFiles(directory=str(BASE_DIR /"static")), name="static")

# adding the sub-routers
app.include_router(api_router.router)
app.include_router(web_router.router)