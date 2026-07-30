"""Endpoints de sesión pública con tokens expirables y revocables."""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from triade.security.public_auth import PublicAuthStore

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def store() -> PublicAuthStore:
    return PublicAuthStore(
        os.getenv("TRIADE_AUTH_DB_PATH", "triade/memory/triade.db"),
        rate_limit_per_minute=int(os.getenv("TRIADE_RATE_LIMIT_PER_MINUTE", "60")),
    )


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, object]:
    try:
        return store().authenticate(payload.username, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/logout")
def logout(request: Request) -> dict[str, object]:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer_required")
    return {"revoked": store().revoke(value[7:], actor="self")}
