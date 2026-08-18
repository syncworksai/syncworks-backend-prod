from __future__ import annotations

import jwt
from jwt import PyJWKClient

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = "https://token.actions.githubusercontent.com/.well-known/jwks"
AUDIENCE = "syncworks-calendar-runtime"
EXPECTED_REPOSITORY = "syncworksai/syncworks-backend-prod"
EXPECTED_REF = "refs/heads/main"
EXPECTED_WORKFLOW_REF = f"{EXPECTED_REPOSITORY}/.github/workflows/calendar-runtime.yml@{EXPECTED_REF}"
ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}


class CalendarOIDCError(RuntimeError):
    pass


def verify_calendar_runtime_token(token: str) -> dict:
    if not token:
        raise CalendarOIDCError("Missing GitHub OIDC token.")

    try:
        signing_key = PyJWKClient(JWKS_URL, cache_keys=True).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "repository", "ref"]},
        )
    except Exception as exc:
        raise CalendarOIDCError("GitHub OIDC token verification failed.") from exc

    if claims.get("repository") != EXPECTED_REPOSITORY:
        raise CalendarOIDCError("Unexpected GitHub repository.")
    if claims.get("ref") != EXPECTED_REF:
        raise CalendarOIDCError("Calendar runtime may only run from main.")
    if claims.get("workflow_ref") != EXPECTED_WORKFLOW_REF:
        raise CalendarOIDCError("Unexpected GitHub workflow.")
    if claims.get("event_name") not in ALLOWED_EVENTS:
        raise CalendarOIDCError("Unexpected GitHub workflow event.")
    if claims.get("runner_environment") not in (None, "github-hosted"):
        raise CalendarOIDCError("Unexpected runner environment.")
    return claims
