import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.regions import router as regions_router
from routes.leads import router as leads_router

app = FastAPI(title="Insure Lead Generation API")

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


@app.get("/health")
def health():
    return {"status": "ok"}
