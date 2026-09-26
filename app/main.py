import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose.exceptions import JWTError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.middleware import RequestContextMiddleware
from app.db.session import Base, engine
import app.models  # noqa: F401  registers all tables before create_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("dhandas")

app = FastAPI(title=settings.app_name, version="1.0.0")

# Order matters: outermost added last runs first. CORS must wrap everything,
# including error responses, so browsers can read them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
def on_startup() -> None:
    # Dev/first-run convenience. Production deployments should run
    # `alembic upgrade head` instead and can leave this as a no-op safety net.
    Base.metadata.create_all(bind=engine)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Single handler for every domain error (see app/core/exceptions.py) —
    one place maps errors to HTTP status, instead of one handler per type."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(JWTError)
async def jwt_error_handler(request: Request, exc: JWTError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so an unexpected bug returns a clean 500 instead of leaking
    a stack trace to the client; full trace still goes to the logs."""
    request_id = getattr(request.state, "request_id", "-")
    logger.exception("unhandled_exception request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}
