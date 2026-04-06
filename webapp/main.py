from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import api_router, web_router
from dotenv import load_dotenv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

app = FastAPI(title="FinOps Platform")

app.mount("/static", StaticFiles(directory=str(BASE_DIR /"static")), name="static")

# adding the sub-routers
app.include_router(api_router.router)
app.include_router(web_router.router)