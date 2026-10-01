"""Replit OIDC login and server-side session helpers for the Flask API."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import Flask, jsonify, redirect, request, session, url_for

SESSION_COOKIE = "sophia_session"
PKCE_COOKIE = "sophia_pkce_verifier"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
ALLOWLIST_ENV = "SOP_ALLOWED_EMAILS"
ISSUER_URL = os.getenv("ISSUER_URL", "https://replit.com/oidc").rstrip("/")


def _safe_return_to(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _origin() -> str:
    proto = request.headers.get("X-Forwarded-Proto", "https").split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}"


def _pkce_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _is_production() -> bool:
    return os.getenv("NODE_ENV", "").casefold() == "production"


def auth_bypass_enabled() -> bool:
    """Permit local regression runs without weakening the published service."""
    default = "false" if _is_production() else "true"
    return os.getenv("ALLOW_DEV_AUTH_BYPASS", default).casefold() == "true" and not _is_production()


def is_authorized_user(user: Any) -> bool:
    """Require a verified, exact email allowlist match in production."""
    if not isinstance(user, dict):
        return False
    if not _is_production():
        return True

    email = user.get("email")
    verified = user.get("email_verified") is True or (
        isinstance(user.get("email_verified"), str)
        and user["email_verified"].casefold() == "true"
    )
    if not isinstance(email, str) or not email.strip() or not verified:
        return False

    allowed_emails = {
        value.strip().casefold()
        for value in os.getenv(ALLOWLIST_ENV, "").split(",")
        if value.strip()
    }
    return email.strip().casefold() in allowed_emails


def configure_auth(app: Flask) -> OAuth:
    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise RuntimeError("SESSION_SECRET is required for authenticated sessions.")
    if _is_production() and not os.getenv("REPL_ID"):
        raise RuntimeError("REPL_ID is required for Replit OIDC in production.")

    app.secret_key = session_secret
    app.config.update(
        SESSION_COOKIE_NAME=SESSION_COOKIE,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=_is_production(),
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=SESSION_TTL_SECONDS,
    )

    oauth = OAuth(app)
    client_id = os.getenv("REPL_ID", "development")
    oauth.register(
        name="replit",
        server_metadata_url=f"{ISSUER_URL}/.well-known/openid-configuration",
        client_id=client_id,
        client_kwargs={"scope": "openid email profile"},
    )

    @app.get("/api/auth/user")
    def auth_user():
        user = session.get("user")
        return jsonify({"user": user if is_authorized_user(user) else None})

    @app.get("/api/login")
    def login():
        verifier = _pkce_verifier()
        session[PKCE_COOKIE] = verifier
        session["auth_return_to"] = _safe_return_to(request.args.get("returnTo"))
        nonce = secrets.token_urlsafe(32)
        redirect_uri = f"{_origin()}{url_for('auth_callback')}"
        return oauth.replit.authorize_redirect(
            redirect_uri,
            nonce=nonce,
            code_challenge=_pkce_challenge(verifier),
            code_challenge_method="S256",
        )

    @app.get("/api/callback")
    def auth_callback():
        verifier = session.pop(PKCE_COOKIE, None)
        return_to = _safe_return_to(session.pop("auth_return_to", "/"))
        if not verifier:
            return redirect("/api/login")
        try:
            token = oauth.replit.authorize_access_token(code_verifier=verifier)
            userinfo = token.get("userinfo")
            if not isinstance(userinfo, dict) or not userinfo.get("sub"):
                raise RuntimeError("OIDC response did not include a subject.")
            user = {
                "id": str(userinfo["sub"]),
                "email": userinfo.get("email"),
                "email_verified": userinfo.get("email_verified") is True
                or (
                    isinstance(userinfo.get("email_verified"), str)
                    and userinfo["email_verified"].casefold() == "true"
                ),
                "name": userinfo.get("name")
                or " ".join(
                    part
                    for part in (userinfo.get("first_name"), userinfo.get("last_name"))
                    if part
                ),
            }
            if not is_authorized_user(user):
                session.clear()
                return jsonify({"error": "This account is not authorized."}), 403
            session.clear()
            session["user"] = user
            session.permanent = True
            return redirect(return_to)
        except Exception:
            app.logger.exception("OIDC callback failed")
            session.clear()
            return jsonify({"error": "Authentication could not be completed."}), 401

    @app.get("/api/logout")
    def logout():
        session.clear()
        return redirect(_safe_return_to(request.args.get("returnTo")))

    return oauth


def current_user() -> dict[str, Any] | None:
    user = session.get("user")
    return user if isinstance(user, dict) else None


def require_auth(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any):
        if auth_bypass_enabled():
            return handler(*args, **kwargs)
        user = current_user()
        if user is None:
            return jsonify({"error": "Authentication required.", "login_url": "/api/login"}), 401
        if not is_authorized_user(user):
            return jsonify({"error": "This account is not authorized."}), 403
        return handler(*args, **kwargs)

    return wrapped