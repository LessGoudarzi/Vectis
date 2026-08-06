from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from config import settings
from routers import layers, trace, admin

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
app.include_router(admin.router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}


# Same as /health, but under /api/v1 — the only prefix the frontend's dev
# proxy (vite.config.ts) and prod reverse proxy (nginx.conf) actually
# forward to the backend, so the frontend's restart-status poll can reach
# it under both.
@app.get("/api/v1/health")
def health_check_v1():
    return {"status": "healthy", "service": settings.APP_NAME}
