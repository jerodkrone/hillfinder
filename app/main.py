import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
import httpx
from app.routers import hills

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ors_api_key = os.getenv("ORS_API_KEY", "")
    async with httpx.AsyncClient(timeout=float(os.getenv("HTTP_CLIENT_TIMEOUT_S", "15"))) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="HillFinder", version="0.1.0", lifespan=lifespan)
app.include_router(hills.router)
