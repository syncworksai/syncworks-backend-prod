from __future__ import annotations

import jwt
from jwt import PyJWKClient


ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = "https://token.actions.githubusercontent.com/.well-known/jwks"
AUDIENCE = "syncworks-billing-runtime"
EXPECTED_REPOSITORY = "syncworksai/syncworks-backend-prod"
EXPECTED_REF = "refs/heads/main"
EXPECTED_WORKFLOW_REF = f"{EXPECTED_REPOSITORY}/.github/workflows/billing-runtime.yml@{EXPECTED_REF}"
ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}


class GitHubOIDCError(RuntimeError):
    pass


def verify_billing_runtime_token(token: str) -> dict:
    if not token:
        raise GitHubOIDCError("Missing GitHub OIDC token.")

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
        raise GitHubOIDCError("GitHub OIDC token verification failed.") from exc

    if claims.get("repository") != EXPECTED_REPOSITORY:
        raise GitHubOIDCError("Unexpected GitHub repository.")
    if claims.get("ref") != EXPECTED_REF:
        raise GitHubOIDCError("Billing runtime may only run from main.")
    if claims.get("workflow_ref") != EXPECTED_WORKFLOW_REF:
        raise GitHubOIDCError("Unexpected GitHub workflow.")
    if claims.get("event_name") not in ALLOWED_EVENTS:
        raise GitHubOIDCError("Unexpected GitHub workflow event.")
    if claims.get("runner_environment") not in (None, "github-hosted"):
        raise GitHubOIDCError("Unexpected runner environment.")

    return claims
