"""Supabase Auth wrapper — sign up, sign in, sign out, profile, avatar upload.

Auth and per-user data (profile, avatar) always go through a fresh anon-key
client with the user's session attached, so RLS (auth.uid() = user_id)
resolves correctly — never the service-role client for these operations.

Streamlit reruns the whole script on every interaction, so no Python object
survives between reruns except st.session_state — the access/refresh tokens
are stashed there and re-attached to a fresh client on every call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from supabase import Client, create_client

from src.config import SUPABASE_ANON_KEY, SUPABASE_URL

AVATAR_BUCKET = "avatars"


@dataclass
class AuthSession:
    user_id:       str
    email:         str
    access_token:  str
    refresh_token: str


@dataclass
class AuthResult:
    ok:      bool
    session: AuthSession | None = None
    error:   str | None = None


def _fresh_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def _authed_client(access_token: str, refresh_token: str) -> Client:
    """Anon-key client with the user's session attached, so auth.uid()
    resolves for RLS-protected reads/writes (profile, avatar storage)."""
    client = _fresh_client()
    client.auth.set_session(access_token, refresh_token)
    return client


def sign_up(email: str, password: str) -> AuthResult:
    try:
        resp = _fresh_client().auth.sign_up({"email": email, "password": password})
        if resp.user is None or resp.session is None:
            # "Confirm email" is enabled on the Supabase project — no active
            # session until the user clicks the confirmation link.
            return AuthResult(ok=False, error="confirm_email")
        session = AuthSession(
            user_id=resp.user.id,
            email=resp.user.email or email,
            access_token=resp.session.access_token,
            refresh_token=resp.session.refresh_token,
        )
        return AuthResult(ok=True, session=session)
    except Exception as exc:
        return AuthResult(ok=False, error=str(exc))


def sign_in(email: str, password: str) -> AuthResult:
    try:
        resp = _fresh_client().auth.sign_in_with_password({"email": email, "password": password})
        if resp.user is None or resp.session is None:
            return AuthResult(ok=False, error="invalid_credentials")
        session = AuthSession(
            user_id=resp.user.id,
            email=resp.user.email or email,
            access_token=resp.session.access_token,
            refresh_token=resp.session.refresh_token,
        )
        return AuthResult(ok=True, session=session)
    except Exception as exc:
        return AuthResult(ok=False, error=str(exc))


def sign_out(access_token: str, refresh_token: str) -> None:
    try:
        _authed_client(access_token, refresh_token).auth.sign_out()
    except Exception:
        pass  # a failed remote sign-out shouldn't block clearing local state


def get_profile(access_token: str, refresh_token: str, user_id: str) -> dict[str, Any] | None:
    try:
        client = _authed_client(access_token, refresh_token)
        resp = client.table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
        return resp.data[0] if resp.data else None
    except Exception:
        return None


def default_avatar_url(user_id: str) -> str:
    """Deterministic placeholder avatar (DiceBear — public, free, no API key)
    assigned at registration so every user has something to look at before
    they optionally upload their own. Seeded by user_id, so it's stable for
    that user but looks different across users."""
    return f"https://api.dicebear.com/9.x/bottts-neutral/png?seed={user_id}"


def create_profile(access_token: str, refresh_token: str, user_id: str, is_adult: bool) -> bool:
    try:
        client = _authed_client(access_token, refresh_token)
        client.table("user_profiles").insert({
            "user_id":    user_id,
            "is_adult":   is_adult,
            "avatar_url": default_avatar_url(user_id),
        }).execute()
        return True
    except Exception:
        return False


def get_query_history(
    access_token: str,
    refresh_token: str,
    user_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return this user's past queries, most recent first.

    Relies on the ql_own_read RLS policy (auth.uid() = user_id) — a logged-in
    user can only ever see their own rows, never another user's.
    """
    try:
        client = _authed_client(access_token, refresh_token)
        resp = (
            client.table("query_logs")
            .select("id, created_at, user_query, final_answer, locale, status")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


def upload_avatar(
    access_token: str,
    refresh_token: str,
    user_id: str,
    file_bytes: bytes,
    filename: str,
) -> str | None:
    """Upload to '<user_id>/<filename>' in the avatars bucket, update the
    profile's avatar_url, and return the new public URL (None on failure)."""
    try:
        client = _authed_client(access_token, refresh_token)
        path = f"{user_id}/{filename}"
        client.storage.from_(AVATAR_BUCKET).upload(
            path, file_bytes, file_options={"upsert": "true"}
        )
        public_url = client.storage.from_(AVATAR_BUCKET).get_public_url(path)
        client.table("user_profiles").update({"avatar_url": public_url}).eq("user_id", user_id).execute()
        return public_url
    except Exception:
        return None
