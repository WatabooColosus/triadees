"""Endpoints de sesión pública con tokens expirables y revocables."""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from triade.security.distributed_auth import DistributedAuthUnavailable
from triade.security.public_auth import PublicAuthStore

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str

class VerifyEmailRequest(BaseModel):
    token: str

class ApiKeyRequest(BaseModel):
    provider: str
    label: str = "default"
    secret: str


def store() -> PublicAuthStore:
    return PublicAuthStore(
        os.getenv("TRIADE_AUTH_DB_PATH", "triade/memory/triade.db"),
        rate_limit_per_minute=int(os.getenv("TRIADE_RATE_LIMIT_PER_MINUTE", "60")),
    )


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, object]:
    try:
        return store().authenticate(payload.username, payload.password)
    except DistributedAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

@router.post("/register")
def register(payload: RegisterRequest) -> dict[str, object]:
    try:
        return store().register_email(payload.email, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest) -> dict[str, object]:
    try:
        return store().verify_email(payload.token)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/api-keys")
def put_api_key(payload: ApiKeyRequest, request: Request) -> dict[str, object]:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer_required")
    try:
        principal = store().authorize(value[7:])
        return store().put_api_key(principal["user_id"], payload.provider, payload.label, payload.secret)
    except (PermissionError, KeyError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/api-keys")
def list_api_keys(request: Request) -> dict[str, object]:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "): raise HTTPException(status_code=401, detail="bearer_required")
    principal = store().authorize(value[7:])
    return {"keys": store().list_api_keys(principal["user_id"])}

@router.get("/audit")
def audit(request: Request) -> dict[str, object]:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "): raise HTTPException(status_code=401, detail="bearer_required")
    principal = store().authorize(value[7:])
    return {"events": store().audit_for_user(principal["user_id"])}


@router.post("/logout")
def logout(request: Request) -> dict[str, object]:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer_required")
    try:
        return {"revoked": store().revoke(value[7:], actor="self")}
    except DistributedAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
