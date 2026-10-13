import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.routing import BaseRoute

from src.bootstrap import AUDIT_ACTION, bootstrap
from src.foundation.core.config import settings
from src.foundation.core.database import DbSession, drain_after_commit
from src.foundation.core.error_response import (
    ErrorResponse,
    ValidationDetail,
    ValidationErrorResponse,
)
from src.foundation.core.exceptions import ClientException
from src.foundation.core.limiter import limiter
from src.foundation.core.logging import setup_logging
from src.foundation.core.middlewares import (
    AccessLogMiddleware,
    AuditContextMiddleware,
    ErrorHandlingMiddleware,
    SecurityHeadersMiddleware,
)
from src.foundation.core.realtime import close_broker
from src.foundation.core.routing import API_PREFIX, RouterMount
from src.foundation.core.shutdown import watch_shutdown_signals
from src.foundation.core.telemetry import APP_TELEMETRY, setup_telemetry
from src.foundation.enums import ErrorCode
from src.foundation.routers import (
    api_token,
    audit_log,
    auth,
    events,
    invitation,
    notification,
    organization,
    permission,
    role,
    user,
)
from src.products import MODULES

setup_logging("api")
setup_telemetry("api")

log = logging.getLogger(__name__)

bootstrap()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # So open event streams end and let a reload/deploy proceed.
    watch_shutdown_signals()
    yield
    await drain_after_commit()
    await close_broker()


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    debug=settings.app_debug,
    telemetry=APP_TELEMETRY,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=settings.allow_origins,
            allow_credentials=settings.allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        Middleware(AuditContextMiddleware),
        Middleware(AccessLogMiddleware),
        Middleware(ErrorHandlingMiddleware),
    ],
)

app.state.limiter = limiter


API_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'"
)

# Swagger UI / ReDoc are served from a CDN and bootstrap themselves with an
# inline <script>, so the API policy above would blank the page.
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
    "https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net; "
    "connect-src 'self'; worker-src 'self' blob:"
)

DOCS_PATHS = {
    path
    for path in (app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url)
    if path
}


app.add_middleware(
    SecurityHeadersMiddleware,
    csp=API_CSP,
    docs_csp=DOCS_CSP,
    docs_paths=DOCS_PATHS,
)


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    return _rate_limit_exceeded_handler(request, exc)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    log.info("%s: %s", exc, request.url, exc_info=settings.log_exc_info)

    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            ErrorResponse(
                request,
                error_code=ErrorCode.SERVER_ERROR
                if exc.status_code != status.HTTP_401_UNAUTHORIZED
                else ErrorCode.UNAUTHORIZED,
                msg=exc.detail,
            ),
        ),
        headers=exc.headers,
    )


@app.exception_handler(ClientException)
async def handle_client_exception(
    request: Request,
    exc: ClientException,
) -> JSONResponse:
    log.info("%s: %s", exc, request.url, exc_info=settings.log_exc_info)

    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            ErrorResponse(request, error_code=exc.error_code, msg=exc.detail),
        ),
        headers=exc.headers,
    )


@app.exception_handler(IntegrityError)
async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    log.info("%s: %s", exc, request.url, exc_info=settings.log_exc_info)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=jsonable_encoder(
            ErrorResponse(
                request,
                error_code=ErrorCode.RESOURCE_ALREADY_EXISTS,
                msg=ErrorCode.RESOURCE_ALREADY_EXISTS.description,
            ),
        ),
    )


@app.exception_handler(ValidationError)
async def handle_validation_error(
    request: Request,
    exc: ValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(
            ValidationErrorResponse(
                request,
                error_code=ErrorCode.VALIDATION_ERROR,
                msg=ErrorCode.VALIDATION_ERROR.description,
                errors=exc.errors(),
            ),
        ),
        headers={},
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if any(
        error.get("type", None) == ErrorCode.JSON_INVALID.code for error in exc.errors()
    ):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=jsonable_encoder(
                ErrorResponse(
                    request,
                    error_code=ErrorCode.JSON_INVALID,
                    msg=ErrorCode.JSON_INVALID.description,
                ),
            ),
            headers={},
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(
            ValidationErrorResponse(
                request,
                error_code=ErrorCode.VALIDATION_ERROR,
                msg=ErrorCode.VALIDATION_ERROR.description,
                errors=exc.errors(),
            ),
        ),
        headers={},
    )


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(
            ErrorResponse(request, error_code=ErrorCode.VALIDATION_ERROR, msg=str(exc)),
        ),
        headers={},
    )


@app.get("/health", tags=["Health"], include_in_schema=False)
async def health_check(session: DbSession) -> Response:
    try:
        await session.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok"})
    except Exception:
        log.exception("Health check: database unreachable")
        return JSONResponse(
            {"status": "error", "detail": "database unavailable"},
            status_code=503,
        )


# Mount order is route-matching and schema order. `public` routers are in the
# published OpenAPI schema for API-token consumers; the rest serve the
# dashboard and auth flows.
ROUTERS: list[RouterMount] = [
    RouterMount(router=auth.router, tags=["Authentication"]),
    RouterMount(router=auth.internal_router, tags=["Authentication"], public=False),
    *(*module.routers for module in MODULES),
    RouterMount(router=api_token.router, tags=["API Tokens"], public=False),
    RouterMount(router=organization.router, tags=["Organizations"], public=False),
    RouterMount(router=user.router, tags=["Users"], public=False),
    RouterMount(router=invitation.router, tags=["Invitations"], public=False),
    RouterMount(router=role.router, tags=["Roles"], public=False),
    RouterMount(router=permission.router, tags=["Permissions"], public=False),
    RouterMount(
        router=audit_log.build_router(AUDIT_ACTION),
        tags=["Audit Log"],
        public=False,
    ),
    RouterMount(router=notification.router, tags=["Notifications"], public=False),
    RouterMount(router=events.router, tags=["Events"], public=False),
]

for mount in ROUTERS:
    app.include_router(
        mount.router,
        tags=list(mount.tags),
        prefix=API_PREFIX,
        include_in_schema=mount.public,
    )


def _build_openapi(routes: list[BaseRoute]) -> dict[str, Any]:
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=routes,
    )

    openapi_schema["components"]["schemas"]["ErrorResponse"] = (
        ErrorResponse.model_json_schema()
    )

    openapi_schema["components"]["schemas"]["ValidationDetail"] = (
        ValidationDetail.model_json_schema()
    )

    openapi_schema["components"]["schemas"]["ValidationErrorResponse"] = (
        ValidationErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
    )

    for path_item in openapi_schema["paths"].values():
        for method, operation in path_item.items():
            if "responses" not in operation:
                operation["responses"] = {}

            if "400" not in operation["responses"]:
                operation["responses"]["400"] = {
                    "description": "Bad Request",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        },
                    },
                }

            if (
                method.lower() in ["get", "put", "delete"]
                and "404" not in operation["responses"]
            ):
                operation["responses"]["404"] = {
                    "description": "Not Found",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        },
                    },
                }

            if "422" in operation["responses"]:
                operation["responses"]["422"] = {
                    "description": "Validation Error",
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ValidationErrorResponse",
                            },
                        },
                    },
                }

    return openapi_schema


def custom_openapi() -> dict[str, Any]:
    if not app.openapi_schema:
        app.openapi_schema = _build_openapi(app.routes)
    return app.openapi_schema


def internal_openapi() -> dict[str, Any]:
    """Schema of every API route, including those hidden from the public one.

    Not served - `generate_openapi.py` writes it for the frontend, whose API
    types are generated from it. Mounts `ROUTERS` on a throwaway app with
    every route visible, so it can never list a different set of routes.
    """
    internal = FastAPI()
    for mount in ROUTERS:
        internal.include_router(mount.router, tags=list(mount.tags), prefix=API_PREFIX)
    return _build_openapi(internal.routes)


app.openapi = custom_openapi  # ty: ignore[invalid-assignment]
