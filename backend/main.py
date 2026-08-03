from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from config import settings
from routers import layers, trace

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url="/openapi.json" if settings.DEBUG else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Layer payloads are repetitive JSON (thousands of features with the same
# property keys) — compresses ~10x, well worth the CPU on responses this size.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(layers.router)
app.include_router(trace.router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}
