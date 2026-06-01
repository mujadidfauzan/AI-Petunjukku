from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_internal_api_key(
    x_internal_api_key: Annotated[
        str | None,
        Header(alias="X-Internal-API-Key"),
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.internal_api_key.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL_API_KEY belum dikonfigurasi.",
        )

    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()

    provided = (x_internal_api_key or bearer or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Internal API key tidak valid.",
        )
