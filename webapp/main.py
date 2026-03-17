from fastapi import FastAPI
from routers import api_router, web_router
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FinOps Platform")

# adding the sub-routers
app.include_router(api_router.router)
app.include_router(web_router.router)