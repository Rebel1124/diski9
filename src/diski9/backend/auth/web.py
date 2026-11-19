"""Flask integration of authentication and accounts (Phase 6C.2).

Account pages are small server-rendered forms on the Flask server that also
serves the Dash app. Every request resolves the server-side session (if any) into
a :class:`Principal` on ``flask.g``; Dash callbacks, Flask views and services all
authorise against that object. Browser-supplied values never confer identity or
privileges.

Protections: opaque HttpOnly session cookie (``__Host-`` prefix, Secure and
SameSite=Lax in production); session rotation at sign-in, re-authentication and
password changes; CSRF tokens on every form plus an Origin check on every
state-changing request (including Dash callbacks) that carries a session cookie;
safe redirects (relative paths only); generic messages that do not reveal whether
an email address is registered; rate limits; no-store caching and a strict
Content-Security-Policy on account pages.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from flask import Blueprint, Flask, Response, g, redirect, render_template, request
from sqlalchemy import Engine, select

from ..db import db_now, transaction
from ..db.schema import app_sessions
from . import accounts as acct
from . import ratelimit as rl
from .crypto import constant_time_equal, derive, token_hash
from .permissions import (
    GUEST,
    PRIVILEGED,
    AuthorizationError,
    Capability,
    NotAuthenticated,
    Principal,
    RecentAuthenticationRequired,
    authorize,
)
from .provider import (
    AuthError,
    AuthProvider,
    EmailNotConfirmed,
    InvalidLink,
    ProviderUnavailable,
    SupabaseAuthProvider,
)
from .sessions import SessionManager
from .settings import AuthSettings

log = logging.getLogger("diski9.auth")
TEMPLATES = Path(__file__).parent / "templates"
TERMS_DIR = Path(__file__).resolve().parents[4] / "docs" / "legal"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

MESSAGES = {
    "check_email": (
        "info",
        "If that address can be used, we have sent a confirmation link. "
        "Check your inbox (and spam folder).",
    ),
    "recovery_sent": (
        "info",
        "If an account uses that address, we have sent a link to reset the password.",
    ),
    "signed_out": ("ok", "You have signed out. This browser tab's temporary analysis was cleared."),
    "signed_out_all": ("ok", "You have signed out on all devices."),
    "password_changed": ("ok", "Your password was changed. Other devices were signed out."),
    "username_changed": ("ok", "Your username was changed."),
    "privacy_saved": ("ok", "Your privacy setting was saved."),
    "welcome": ("ok", "Your account is ready."),
    "session_ended": ("info", "Your session has ended. Please sign in again."),
    "reauth_needed": ("info", "For your security, please enter your password again."),
    "confirmed": ("ok", "Your email address is confirmed."),
}


@dataclass
class AuthRuntime:
    engine: Engine
    provider: AuthProvider
    settings: AuthSettings
    sessions: SessionManager

    @classmethod
    def create(
        cls,
        engine: Engine,
        settings: AuthSettings | None = None,
        provider: AuthProvider | None = None,
    ) -> AuthRuntime:
        settings = settings or AuthSettings()
        settings.secret()  # fail fast on missing keys
        provider = provider or SupabaseAuthProvider(settings)
        return cls(engine, provider, settings, SessionManager(engine, provider, settings))


# ---------------------------------------------------------------- helpers
def runtime() -> AuthRuntime:
    from flask import current_app

    return current_app.config["DISKI9_AUTH"]


def current_principal() -> Principal:
    """The principal for the current request (guests get :data:`GUEST`). Usable in
    Flask views, Dash callbacks and services called from them."""
    try:
        return g.get("principal", GUEST)
    except RuntimeError:  # outside a request
        return GUEST


def safe_next(value: str | None, default: str = "/") -> str:
    """Only same-site relative paths; anything else becomes ``default`` (prevents
    open redirects such as ``//evil.example`` or ``https://...``)."""
    if not value or len(value) > 512:
        return default
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or any(ord(c) < 32 for c in value):
        return default
    return value


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _render(template: str, title: str, *, status: int = 200, **ctx) -> Response:
    msgs = []
    code = request.args.get("m")
    if code in MESSAGES:
        msgs.append(MESSAGES[code])
    msgs.extend(ctx.pop("messages", []))
    html = render_template(template, title=title, messages=msgs, csrf_token=csrf_token(), **ctx)
    return Response(html, status=status, mimetype="text/html")


def _go(path: str, **params) -> Response:
    return redirect(path + (f"?{urlencode(params)}" if params else ""), code=303)


def csrf_token() -> str:
    rt = runtime()
    if g.get("session_hash"):
        return derive(rt.settings.secret(), "csrf", g.session_hash)
    cookie = request.cookies.get(rt.settings.csrf_cookie_name) or g.get("new_csrf_cookie")
    if not cookie:
        cookie = g.new_csrf_cookie = secrets.token_urlsafe(32)
    return derive(rt.settings.secret(), "csrf-guest", cookie)


def _csrf_valid() -> bool:
    return constant_time_equal(request.form.get("csrf_token"), csrf_token())


def _origin_allowed() -> bool | None:
    """True/False when the request names an origin; None when it names none."""
    rt = runtime()
    origin = request.headers.get("Origin")
    if not origin:
        ref = request.headers.get("Referer")
        if not ref:
            return None
        p = urlsplit(ref)
        origin = f"{p.scheme}://{p.netloc}"
    allowed = {rt.settings.site_origin}
    if rt.settings.app_environment != "production":
        allowed.add(request.host_url.rstrip("/"))
    return origin.rstrip("/") in allowed


def _set_session_cookie(resp: Response, token: str) -> None:
    s = runtime().settings
    resp.set_cookie(
        s.session_cookie_name,
        token,
        max_age=int(s.absolute_lifetime.total_seconds()),
        secure=s.cookie_secure,
        httponly=True,
        samesite="Lax",
        path="/",
    )


def _clear_session_cookie(resp: Response) -> None:
    s = runtime().settings
    resp.delete_cookie(s.session_cookie_name, path="/", secure=s.cookie_secure, samesite="Lax")


def _principal_for(session) -> Principal:
    rt = runtime()
    with rt.engine.connect() as conn:
        view = acct.account(conn, session.user_id)
    return Principal(
        user_id=session.user_id,
        session_hash=session.id,
        roles=view.roles,
        features=view.features,
        onboarded=view.onboarded(rt.settings.app_terms_version),
        username=view.username,
        authenticated_at=session.authenticated_at,
        reauthenticated_at=session.reauthenticated_at,
        now=session.now,
        extra={
            "operator_recency_hours": rt.settings.operator_recency_hours,
            "sensitive_recency_minutes": rt.settings.sensitive_recency_minutes,
            "email": view.email,
        },
    )


def owner_tag() -> str:
    """Opaque per-account marker for the browser (used only to clear one account's
    tab state when another account signs in); never the internal user ID."""
    p = current_principal()
    if not p.is_authenticated:
        return "guest"
    return derive(runtime().settings.secret(), "owner", str(p.user_id))[:24]


# ---------------------------------------------------------------- guards
def require(capability: Capability) -> Callable:
    """Decorator for Flask views. Privileged capabilities also re-check the
    provider session (fail closed) and the recency rules."""

    def wrap(view):
        @wraps(view)
        def inner(*args, **kwargs):
            p = current_principal()
            try:
                authorize(p, capability)
                if capability in PRIVILEGED and not runtime().sessions.verify_with_provider(
                    p.session_hash
                ):
                    raise NotAuthenticated("provider_session_invalid")
            except RecentAuthenticationRequired:
                return _go("/auth/reauthenticate", next=request.full_path, m="reauth_needed")
            except NotAuthenticated:
                return _go("/auth/sign-in", next=request.full_path)
            except AuthorizationError as exc:
                log.info("forbidden: %s", exc.reason)
                return _render(
                    "message.html",
                    "Not available",
                    status=403,
                    body="You do not have access to this page.",
                )
            return view(*args, **kwargs)

        return inner

    return wrap


def require_signed_in(onboarded: bool = True) -> Callable:
    def wrap(view):
        @wraps(view)
        def inner(*args, **kwargs):
            p = current_principal()
            if not p.is_authenticated:
                return _go("/auth/sign-in", next=request.full_path)
            if onboarded and not p.onboarded:
                return _go("/account/welcome")
            return view(*args, **kwargs)

        return inner

    return wrap


def authorize_callback(capability: Capability) -> Principal:
    """For Dash callbacks: the principal if allowed; otherwise the callback is
    stopped (``PreventUpdate``) and nothing is returned to the browser."""
    from dash.exceptions import PreventUpdate

    p = current_principal()
    try:
        authorize(p, capability)
    except AuthorizationError as exc:
        log.info("callback forbidden: %s", exc.reason)
        raise PreventUpdate from None
    return p


# ---------------------------------------------------------------- request hooks
def _before_request():
    rt = runtime()
    g.principal = GUEST
    g.session_hash = None
    token = request.cookies.get(rt.settings.session_cookie_name)
    if token:
        session = rt.sessions.resolve(token)
        if session is None:
            g.clear_session_cookie = True
        else:
            g.session_hash = session.id
            g.principal = _principal_for(session)
    if request.method in UNSAFE_METHODS:
        allowed = _origin_allowed()
        is_account_route = request.path.startswith(("/auth/", "/account"))
        if allowed is False or (allowed is None and (token or is_account_route)):
            log.warning("blocked cross-origin %s %s", request.method, request.path)
            return Response("Forbidden", status=403)
        if is_account_route and not _csrf_valid():
            log.warning("blocked request with invalid CSRF token on %s", request.path)
            return _render(
                "message.html",
                "Please try again",
                status=400,
                body="Your form expired. Please go back, reload the page and try again.",
            )
    return None


def _after_request(resp: Response) -> Response:
    rt = runtime()
    if g.get("set_session_token"):
        _set_session_cookie(resp, g.set_session_token)
    elif g.get("clear_session_cookie"):
        _clear_session_cookie(resp)
    if g.get("new_csrf_cookie"):
        resp.set_cookie(
            rt.settings.csrf_cookie_name,
            g.new_csrf_cookie,
            max_age=7200,
            secure=rt.settings.cookie_secure,
            httponly=True,
            samesite="Strict",
            path="/",
        )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith(("/auth/", "/account", "/legal/")):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
    if g.get("clear_site_data"):
        resp.headers["Clear-Site-Data"] = '"storage"'
    return resp


# ---------------------------------------------------------------- blueprint
bp = Blueprint("diski9_auth", __name__, template_folder=str(TEMPLATES))


def _start_session(identity_session, *, replace: bool = True) -> Response | None:
    """Map the verified identity to a Diski 9 user and start a fresh session."""
    rt = runtime()
    with transaction(rt.engine) as conn:
        uid = acct.ensure_app_user(conn, identity_session.identity)
        status = acct.account(conn, uid).status
        if status != "active":
            return _render(
                "message.html",
                "Account unavailable",
                status=403,
                body="This account is not available. Please contact support.",
            )
        if replace and g.get("session_hash"):  # account switching: end the old session
            rt.sessions._revoke(conn, g.session_hash, "sign_out", db_now(conn))
        token = rt.sessions.start(conn, uid, identity_session)
    g.set_session_token = token
    g.session_hash = token_hash(token)
    return None


@bp.route("/auth/sign-up", methods=["GET", "POST"])
def sign_up():
    title = "Create your account"
    if request.method == "GET":
        return _render("sign_up.html", title)
    rt = runtime()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    if not EMAIL_RE.match(email):
        return _render(
            "sign_up.html",
            title,
            status=400,
            email=email,
            messages=[("error", "Please enter a valid email address.")],
        )
    if len(password) < 10 or len(password) > 72:
        return _render(
            "sign_up.html",
            title,
            status=400,
            email=email,
            messages=[("error", "Please choose a password of 10 to 72 characters.")],
        )
    with transaction(rt.engine) as conn:
        allowed = rl.hit(conn, rt.settings.secret(), rl.SIGN_UP_IP, _client_ip())
    if not allowed:
        return _render(
            "sign_up.html",
            title,
            status=429,
            email=email,
            messages=[("error", "Too many attempts. Please try again later.")],
        )
    try:
        rt.provider.sign_up(email, password)
    except AuthError as exc:
        return _render(
            "sign_up.html", title, status=400, email=email, messages=[("error", exc.public_message)]
        )
    return _go("/auth/check-email", m="check_email")


@bp.route("/auth/check-email")
def check_email():
    return _render(
        "message.html",
        "Check your email",
        body="Follow the link in the email to confirm your address, then finish "
        "setting up your account.",
    )


@bp.route("/auth/sign-in", methods=["GET", "POST"])
def sign_in():
    title = "Sign in"
    next_url = safe_next(request.values.get("next"))
    if request.method == "GET":
        return _render("sign_in.html", title, next_url=next_url)
    rt = runtime()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    generic = [("error", "The email address or password is incorrect.")]
    if not EMAIL_RE.match(email) or not password:
        return _render(
            "sign_in.html", title, status=400, email=email, next_url=next_url, messages=generic
        )
    with transaction(rt.engine) as conn:
        secret = rt.settings.secret()
        ok = rl.hit(conn, secret, rl.SIGN_IN_IP, _client_ip()) and rl.hit(
            conn, secret, rl.SIGN_IN_EMAIL, email
        )
    if not ok:
        return _render(
            "sign_in.html",
            title,
            status=429,
            email=email,
            next_url=next_url,
            messages=[("error", "Too many attempts. Please wait a few minutes.")],
        )
    try:
        ps = rt.provider.sign_in_with_password(email, password)
    except EmailNotConfirmed as exc:
        return _render(
            "sign_in.html",
            title,
            status=400,
            email=email,
            next_url=next_url,
            messages=[("error", exc.public_message)],
        )
    except AuthError as exc:
        status = 503 if isinstance(exc, ProviderUnavailable) else 400
        return _render(
            "sign_in.html",
            title,
            status=status,
            email=email,
            next_url=next_url,
            messages=[("error", exc.public_message)],
        )
    blocked = _start_session(ps)
    if blocked is not None:
        return blocked
    log.info("sign-in")
    return _go("/account/welcome") if not _onboarded_now() else redirect(next_url, code=303)


def _onboarded_now() -> bool:
    rt = runtime()
    with rt.engine.connect() as conn:
        uid = conn.execute(
            select(app_sessions.c.user_id).where(app_sessions.c.id == g.session_hash)
        ).scalar_one()
        return acct.account(conn, uid).onboarded(rt.settings.app_terms_version)


@bp.route("/auth/confirm", methods=["GET", "POST"])
def confirm():
    kind = request.values.get("type")
    token = request.values.get("token_hash") or ""
    if kind not in ("email", "recovery") or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        return _render(
            "message.html",
            "Link not valid",
            status=400,
            body=InvalidLink.public_message,
            primary_href="/auth/sign-in",
            primary_label="Sign in",
        )
    if request.method == "GET":
        body, button = (
            ("Confirm your email address to finish creating your account.", "Confirm email")
            if kind == "email"
            else ("Continue to choose a new password.", "Continue")
        )
        return _render(
            "confirm.html",
            "Confirm" if kind == "email" else "Reset password",
            token_hash=token,
            kind=kind,
            body=body,
            button=button,
        )
    rt = runtime()
    with transaction(rt.engine) as conn:
        allowed = rl.hit(conn, rt.settings.secret(), rl.CONFIRM_IP, _client_ip())
    if not allowed:
        return _render(
            "message.html",
            "Please wait",
            status=429,
            body="Too many attempts. Please try again later.",
        )
    try:
        ps = rt.provider.verify_email_link(token, kind)
    except AuthError as exc:
        return _render(
            "message.html",
            "Link not valid",
            status=400,
            body=exc.public_message,
            primary_href="/auth/forgot" if kind == "recovery" else "/auth/sign-in",
            primary_label="Request a new link" if kind == "recovery" else "Sign in",
        )
    blocked = _start_session(ps)
    if blocked is not None:
        return blocked
    if kind == "recovery":
        return _go("/auth/password")
    return (
        _go("/account/welcome", m="confirmed") if not _onboarded_now() else _go("/", m="confirmed")
    )


@bp.route("/auth/forgot", methods=["GET", "POST"])
def forgot():
    title = "Reset your password"
    if request.method == "GET":
        return _render("forgot.html", title)
    rt = runtime()
    email = (request.form.get("email") or "").strip()
    if EMAIL_RE.match(email):
        with transaction(rt.engine) as conn:
            secret = rt.settings.secret()
            ok = rl.hit(conn, secret, rl.RECOVERY_IP, _client_ip()) and rl.hit(
                conn, secret, rl.RECOVERY_EMAIL, email
            )
        if ok:
            try:
                rt.provider.send_password_recovery(email)
            except ProviderUnavailable as exc:
                return _render(
                    "forgot.html", title, status=503, messages=[("error", exc.public_message)]
                )
    # same response whatever happened: no account enumeration
    return _go("/auth/check-email", m="recovery_sent")


@bp.route("/auth/password", methods=["GET", "POST"])
@require_signed_in(onboarded=False)
def password():
    rt = runtime()
    p = current_principal()
    if not _recent(p):
        return _go("/auth/reauthenticate", next="/auth/password", m="reauth_needed")
    title = "Choose a new password"
    if request.method == "GET":
        return _render("password.html", title)
    new, again = request.form.get("password") or "", request.form.get("confirm") or ""
    if new != again:
        return _render(
            "password.html",
            title,
            status=400,
            messages=[("error", "The two passwords do not match.")],
        )
    if not 10 <= len(new) <= 72:
        return _render(
            "password.html",
            title,
            status=400,
            messages=[("error", "Please choose a password of 10 to 72 characters.")],
        )
    if not rt.sessions.refresh_provider(p.session_hash, strict=True):
        g.clear_session_cookie = True
        return _go("/auth/sign-in", m="session_ended")
    ps = rt.sessions.provider_session(p.session_hash)
    try:
        rt.provider.update_password(ps, new)
        rt.provider.sign_out(ps.access_token, "others")
    except AuthError as exc:
        return _render("password.html", title, status=400, messages=[("error", exc.public_message)])
    with transaction(rt.engine) as conn:
        from sqlalchemy import update

        now = db_now(conn)
        conn.execute(
            update(app_sessions)
            .where(
                app_sessions.c.user_id == p.user_id,
                app_sessions.c.revoked_at.is_(None),
                app_sessions.c.id != p.session_hash,
            )
            .values(
                revoked_at=now,
                revoked_reason="password_changed",
                provider_refresh_token_enc=None,
                provider_access_token_enc=None,
            )
        )
        token = rt.sessions.rotate(conn, p.session_hash)
        from ..repositories.ops import record_audit

        record_audit(
            conn,
            action="account.password_changed",
            target_type="user",
            target_id=str(p.user_id),
            actor=p.user_id,
            actor_role="participant",
        )
    g.set_session_token = token
    return _go("/account" if p.onboarded else "/account/welcome", m="password_changed")


def _recent(p: Principal) -> bool:
    from datetime import timedelta

    s = runtime().settings
    return bool(
        p.reauthenticated_at
        and p.now
        and p.now - p.reauthenticated_at <= timedelta(minutes=s.sensitive_recency_minutes)
    )


@bp.route("/auth/reauthenticate", methods=["GET", "POST"])
@require_signed_in(onboarded=False)
def reauthenticate():
    rt = runtime()
    p = current_principal()
    title = "Confirm it's you"
    next_url = safe_next(request.values.get("next"), "/account")
    email = p.extra.get("email")
    if request.method == "GET":
        return _render("reauth.html", title, next_url=next_url, email=email)
    with transaction(rt.engine) as conn:
        ok = rl.hit(conn, rt.settings.secret(), rl.REAUTH_USER, str(p.user_id))
    if not ok:
        return _render(
            "reauth.html",
            title,
            status=429,
            next_url=next_url,
            email=email,
            messages=[("error", "Too many attempts. Please wait a few minutes.")],
        )
    try:
        ps = rt.provider.sign_in_with_password(email or "", request.form.get("password") or "")
    except AuthError as exc:
        return _render(
            "reauth.html",
            title,
            status=400,
            next_url=next_url,
            email=email,
            messages=[("error", exc.public_message)],
        )
    if ps.identity.subject != _subject_of(p):
        return _render(
            "reauth.html",
            title,
            status=400,
            next_url=next_url,
            email=email,
            messages=[("error", "The email address or password is incorrect.")],
        )
    old = rt.sessions.access_token(p.session_hash)
    with transaction(rt.engine) as conn:
        token = rt.sessions.rotate(conn, p.session_hash, ps, reauthenticated=True)
    if old:
        with contextlib.suppress(AuthError):
            rt.provider.sign_out(old, "local")
    g.set_session_token = token
    return redirect(next_url, code=303)


def _subject_of(p: Principal) -> str | None:
    from ..db.schema import user_identities

    rt = runtime()
    with rt.engine.connect() as conn:
        return conn.execute(
            select(user_identities.c.subject).where(
                user_identities.c.user_id == p.user_id,
                user_identities.c.provider == rt.provider.name,
            )
        ).scalar()


@bp.route("/auth/sign-out", methods=["GET", "POST"])
def sign_out():
    rt = runtime()
    if request.method == "GET":
        if not g.get("session_hash"):
            return _go("/")
        return _render(
            "sign_out.html",
            "Sign out",
            lead="Signing out also clears this browser tab's temporary analysis.",
        )
    h = g.get("session_hash")
    if h:
        if rt.sessions.refresh_provider(h):
            access = rt.sessions.access_token(h)
            if access:
                try:
                    rt.provider.sign_out(access, "local")
                except AuthError:
                    log.warning("provider sign-out failed; app session revoked anyway")
        rt.sessions.revoke(h, "sign_out")
    g.clear_session_cookie = True
    g.clear_site_data = True
    g.session_hash = None
    g.principal = GUEST
    return _render(
        "message.html",
        "Signed out",
        clear_browser_state=True,
        body=MESSAGES["signed_out"][1],
        primary_href="/auth/sign-in",
        primary_label="Sign in again",
    )


@bp.route("/auth/sign-out-everywhere", methods=["POST"])
@require_signed_in(onboarded=False)
def sign_out_everywhere():
    rt = runtime()
    p = current_principal()
    if rt.sessions.refresh_provider(p.session_hash):
        access = rt.sessions.access_token(p.session_hash)
        if access:
            try:
                rt.provider.sign_out(access, "global")
            except AuthError:
                log.warning("provider global sign-out failed")
    with transaction(rt.engine) as conn:
        rt.sessions.revoke_all_for_user(conn, p.user_id, "sign_out_everywhere")
    g.clear_session_cookie = True
    g.clear_site_data = True
    return _render(
        "message.html",
        "Signed out everywhere",
        clear_browser_state=True,
        body=MESSAGES["signed_out_all"][1],
        primary_href="/auth/sign-in",
        primary_label="Sign in again",
    )


@bp.route("/account/welcome", methods=["GET", "POST"])
@require_signed_in(onboarded=False)
def welcome():
    rt = runtime()
    p = current_principal()
    if p.onboarded:
        return _go("/account")
    title = "Finish setting up"
    version = rt.settings.app_terms_version
    if request.method == "GET":
        return _render(
            "welcome.html",
            title,
            terms_version=version,
            lead="Choose a username and confirm the beta terms.",
        )
    username = request.form.get("username") or ""
    try:
        with transaction(rt.engine) as conn:
            if request.form.get("terms_version") != version:
                raise acct.AccountError("The terms were updated. Please review them again.")
            acct.complete_onboarding(
                conn,
                p.user_id,
                username=username,
                terms_version=version,
                accepted_terms=request.form.get("accept_terms") == "yes",
                age_confirmed=request.form.get("age_confirmed") == "yes",
            )
    except acct.AccountError as exc:
        return _render(
            "welcome.html",
            title,
            status=400,
            terms_version=version,
            username=username,
            messages=[("error", str(exc))],
        )
    return _go("/account", m="welcome")


@bp.route("/account")
@require_signed_in()
def account_page():
    rt = runtime()
    p = current_principal()
    with rt.engine.connect() as conn:
        view = acct.account(conn, p.user_id)
        now = db_now(conn)
    next_rename = None
    if view.username_changed_at and now - view.username_changed_at < acct.RENAME_INTERVAL:
        next_rename = (view.username_changed_at + acct.RENAME_INTERVAL).date().isoformat()
    # the first choice at set-up does not count as a change
    with rt.engine.connect() as conn:
        from sqlalchemy import func

        from ..db.schema import username_history

        changes = conn.execute(
            select(func.count())
            .select_from(username_history)
            .where(username_history.c.user_id == p.user_id)
        ).scalar_one()
    if changes <= 1:
        next_rename = None
    roles = ", ".join(sorted(view.roles)) if view.roles else ""
    return _render(
        "account.html",
        "Account settings",
        wide=True,
        acct=view,
        terms_version=rt.settings.app_terms_version,
        next_rename=next_rename,
        roles=roles,
    )


@bp.route("/account/username", methods=["POST"])
@require_signed_in()
def change_username():
    rt = runtime()
    p = current_principal()
    try:
        with transaction(rt.engine) as conn:
            acct.change_username(conn, p.user_id, request.form.get("username") or "")
    except acct.AccountError as exc:
        return _go_account_error(str(exc))
    return _go("/account", m="username_changed")


@bp.route("/account/privacy", methods=["POST"])
@require_signed_in()
def privacy():
    rt = runtime()
    p = current_principal()
    try:
        with transaction(rt.engine) as conn:
            acct.set_privacy(
                conn,
                p.user_id,
                request.form.get("mode") or "",
                retroactive=request.form.get("retroactive") == "yes",
            )
    except acct.AccountError as exc:
        return _go_account_error(str(exc))
    return _go("/account", m="privacy_saved")


def _go_account_error(text: str) -> Response:
    rt = runtime()
    p = current_principal()
    with rt.engine.connect() as conn:
        view = acct.account(conn, p.user_id)
    return _render(
        "account.html",
        "Account settings",
        status=400,
        wide=True,
        acct=view,
        terms_version=rt.settings.app_terms_version,
        next_rename=None,
        roles="",
        messages=[("error", text)],
    )


@bp.route("/legal/terms")
def terms():
    version = runtime().settings.app_terms_version
    path = TERMS_DIR / f"terms-{version}.md"
    text = path.read_text("utf-8") if path.exists() else "The terms are not available."
    return _render("terms.html", "Diski 9 beta terms", wide=True, text=text)


def init_auth(server: Flask, rt: AuthRuntime) -> None:
    """Attach authentication to the Flask server behind Dash."""
    if rt.settings.app_trusted_proxies:
        from werkzeug.middleware.proxy_fix import ProxyFix

        n = rt.settings.app_trusted_proxies
        server.wsgi_app = ProxyFix(server.wsgi_app, x_for=n, x_proto=n, x_host=n)
    server.config["DISKI9_AUTH"] = rt
    server.register_blueprint(bp)
    server.before_request(_before_request)
    server.after_request(_after_request)
