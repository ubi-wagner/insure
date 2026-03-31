import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.regions import router as regions_router
from routes.leads import router as leads_router
from routes.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agents.hunter import run_hunter_loop
    thread = threading.Thread(target=run_hunter_loop, daemon=True)
    thread.start()
    yield


app = FastAPI(title="Insure Lead Generation API", lifespan=lifespan)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(regions_router)
app.include_router(leads_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    return {"status": "ok"}
