"""Error responses (spec-04 §8).

Every error carries `{code, message, detail, remedy}`. The `remedy` is
user-facing and specific: a LaTeX failure gives the source line, an auth
failure names the backend and the credential it expected, a conflict returns
both versions.

A stack trace tells the user nothing they can act on, and the two auth failures
that matter here — an expired subscription session and a missing API key — look
identical in one.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..kb.write import Conflict, NotFound, StillReferenced, ValidationFailed, WriteError
from ..render.compile import CompileError, TectonicMissing
from ..runtime.base import BackendAuthError, BackendError, ContextExceeded


class RunBusy(WriteError):
    """The run is mid-revision. Distinct from a failure: it resolves by itself,
    so a client should wait and retry rather than report an error."""

    code = "run_busy"


#: Which HTTP status each refusal maps to. 409 for a conflict so the UI can
#: offer a comparison rather than a generic failure.
STATUS = {
    ValidationFailed: 422,
    Conflict: 409,
    RunBusy: 409,
    NotFound: 404,
    StillReferenced: 409,
    WriteError: 400,
    ContextExceeded: 507,
    BackendAuthError: 401,
    TectonicMissing: 503,
    CompileError: 422,
    BackendError: 502,
}


def envelope(code: str, message: str, *, remedy: str = "", detail: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "detail": detail, "remedy": remedy}


def _status_for(exc: Exception) -> int:
    for kind, status in STATUS.items():
        if isinstance(exc, kind):
            return status
    return 500


def install(app) -> None:
    @app.exception_handler(WriteError)
    async def _write_error(_request: Request, exc: WriteError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content=envelope(exc.code, exc.message, remedy=exc.remedy, detail=exc.detail),
        )

    @app.exception_handler(BackendError)
    async def _backend_error(_request: Request, exc: BackendError) -> JSONResponse:
        remedy = ""
        detail = None
        if isinstance(exc, BackendAuthError):
            remedy = f"Expected {exc.credential}."
            detail = {"backend": exc.backend, "credential": exc.credential}
        elif isinstance(exc, ContextExceeded):
            remedy = (
                "Selection reads every fact in one pass by design, so this cannot be "
                "worked around by splitting the corpus. Use a model with a larger window."
            )
            detail = {"needed": exc.needed, "available": exc.available}
        return JSONResponse(
            status_code=_status_for(exc),
            content=envelope(type(exc).__name__, str(exc), remedy=remedy, detail=detail),
        )

    @app.exception_handler(CompileError)
    async def _compile_error(_request: Request, exc: CompileError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content=envelope(
                "latex_compile_failed",
                str(exc),
                remedy="Fix the template or the content at the line shown.",
                detail={"line": exc.line, "source": exc.source_line},
            ),
        )

    @app.exception_handler(TectonicMissing)
    async def _tectonic_missing(_request: Request, exc: TectonicMissing) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=envelope("tectonic_missing", str(exc), remedy="brew install tectonic"),
        )
