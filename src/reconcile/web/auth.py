"""Cookie-based authentication routes and shared security dependencies."""

from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconcile.auth.config import AUTH_PATH, CSRF_HEADER, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from reconcile.auth.crypto import csrf_token, csrf_valid, new_token, valid_token
from reconcile.auth.runtime import AuthRuntime
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import IssuedSession
from reconcile.persistence.auth_models import TokenPurpose

router = APIRouter(prefix=AUTH_PATH, tags=["Authentication"])
ACKNOWLEDGEMENT = {
    "message": (
        "If this request is eligible, follow the instructions sent to your email. "
        "You can then sign in."
    )
}


def runtime(request: Request) -> AuthRuntime:
    service = getattr(request.app.state, "auth", None)
    if service is None:
        raise AuthError(503, "unavailable", "Authentication is temporarily unavailable.")
    return service


def session_cookie(request: Request, service: AuthRuntime) -> str:
    value = request.cookies.get(service.settings.session_cookie)
    return value if valid_token(value) else ""


def require_csrf(request: Request) -> None:
    service = runtime(request)
    if request.headers.get("origin") not in service.settings.trusted_origins or not csrf_valid(
        service.settings.csrf_secret,
        request.cookies.get(service.settings.csrf_cookie),
        session_cookie(request, service),
        request.headers.get(CSRF_HEADER),
    ):
        raise AuthError(403, "csrf_failed", "Refresh the page and try again.")


def require_analysis(request: Request) -> None:
    service = runtime(request)
    service.sessions.authorize_analysis(session_cookie(request, service))
    require_csrf(request)


def _set_cookie(
    response: Response, service: AuthRuntime, name: str, value: str, max_age: int
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=service.settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )


def _csrf_response(
    request: Request, response: Response, *, rotate: bool, session: str | None = None
) -> dict[str, str]:
    service = runtime(request)
    context = request.cookies.get(service.settings.csrf_cookie)
    if rotate or not valid_token(context):
        context = new_token()
        _set_cookie(
            response,
            service,
            service.settings.csrf_cookie,
            context,
            service.settings.session_absolute_seconds,
        )
    return {
        "csrf_token": csrf_token(
            service.settings.csrf_secret,
            context,
            session_cookie(request, service) if session is None else session,
        )
    }


def _session_response(
    request: Request, response: Response, issued: IssuedSession
) -> dict[str, str]:
    service = runtime(request)
    maximum = max(0, int((issued.absolute_expires_at - service.clock()).total_seconds()))
    _set_cookie(response, service, service.settings.session_cookie, issued.token, maximum)
    return _csrf_response(request, response, rotate=True, session=issued.token)


class AuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("password", check_fields=False)
    @classmethod
    def password_encoding(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Enter valid Unicode characters.") from None
        return value


class EmailInput(AuthInput):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            return validate_email(value, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            raise ValueError("Enter a valid email address.") from None


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, repr=False)


class RegisterInput(EmailInput):
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH, repr=False
    )
    display_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)

    @field_validator("display_name", "organization_name")
    @classmethod
    def names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a name.")
        return value


class TokenInput(AuthInput):
    token: str = Field(min_length=1, max_length=128, repr=False)


class ResetInput(TokenInput):
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH, repr=False
    )


class OrganizationInput(AuthInput):
    organization_id: UUID


@router.get("/csrf")
def bootstrap(request: Request, response: Response) -> dict[str, str]:
    incoming_origin = request.headers.get("origin")
    if incoming_origin and incoming_origin not in runtime(request).settings.trusted_origins:
        raise AuthError(403, "csrf_failed", "Untrusted browser origin.")
    return _csrf_response(request, response, rotate=False)


@router.post("/register", status_code=202, dependencies=[Depends(require_csrf)])
def register(body: RegisterInput, request: Request) -> dict[str, str]:
    runtime(request).accounts.register(
        body.email, body.password, body.display_name, body.organization_name
    )
    return ACKNOWLEDGEMENT


@router.post("/login", dependencies=[Depends(require_csrf)])
def login(body: LoginInput, request: Request, response: Response) -> dict[str, str]:
    service = runtime(request)
    issued = service.accounts.login(body.email, body.password, session_cookie(request, service))
    return _session_response(request, response, issued)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response) -> dict[str, str]:
    service = runtime(request)
    service.sessions.logout(session_cookie(request, service))
    response.delete_cookie(
        service.settings.session_cookie,
        path="/",
        secure=service.settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    return _csrf_response(request, response, rotate=True, session="")


@router.get("/me")
def me(request: Request) -> dict[str, object]:
    service = runtime(request)
    principal = service.sessions.authenticate(session_cookie(request, service))
    return {
        "user": {
            "id": str(principal.user_id),
            "email": principal.email,
            "display_name": principal.display_name,
        },
        "memberships": [
            {
                "organization_id": str(m.organization_id),
                "organization_name": m.organization_name,
                "role": m.role,
            }
            for m in principal.memberships
        ],
        "active_organization_id": str(principal.active_organization_id)
        if principal.active_organization_id
        else None,
    }


@router.post("/select-organization", dependencies=[Depends(require_csrf)])
def select_organization(
    body: OrganizationInput, request: Request, response: Response
) -> dict[str, str]:
    service = runtime(request)
    issued = service.sessions.select_organization(
        session_cookie(request, service), body.organization_id
    )
    return _session_response(request, response, issued)


@router.post("/forgot-password", status_code=202, dependencies=[Depends(require_csrf)])
def forgot_password(body: EmailInput, request: Request) -> dict[str, str]:
    runtime(request).accounts.request_email(body.email, TokenPurpose.RESET)
    return ACKNOWLEDGEMENT


@router.post("/resend-verification", status_code=202, dependencies=[Depends(require_csrf)])
def resend_verification(body: EmailInput, request: Request) -> dict[str, str]:
    runtime(request).accounts.request_email(body.email, TokenPurpose.VERIFICATION)
    return ACKNOWLEDGEMENT


@router.post("/verify-email", dependencies=[Depends(require_csrf)])
def verify_email(body: TokenInput, request: Request) -> dict[str, str]:
    runtime(request).accounts.consume_token(body.token, TokenPurpose.VERIFICATION)
    return {"message": "Email verified. You can now sign in."}


@router.post("/reset-password", dependencies=[Depends(require_csrf)])
def reset_password(body: ResetInput, request: Request, response: Response) -> dict[str, str]:
    service = runtime(request)
    service.accounts.consume_token(body.token, TokenPurpose.RESET, body.password)
    return {"message": "Password changed. Sign in with your new password."}
