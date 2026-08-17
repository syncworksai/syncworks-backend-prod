from unittest.mock import patch

from rest_framework.test import APIClient

from platform_growth.services.github_oidc import GitHubOIDCError


RUNTIME_URL = "/api/v1/platform-growth/growth/runtime/run/"


def test_growth_runtime_rejects_unauthenticated_request():
    response = APIClient().post(RUNTIME_URL, {}, format="json")
    assert response.status_code == 403


def test_growth_runtime_rejects_invalid_oidc_token():
    client = APIClient()
    with patch(
        "platform_growth.runtime_views.verify_growth_runtime_token",
        side_effect=GitHubOIDCError("invalid"),
    ):
        response = client.post(
            RUNTIME_URL,
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
    assert response.status_code == 403


def test_growth_runtime_runs_all_background_stages_with_github_oidc():
    client = APIClient()
    with (
        patch(
            "platform_growth.runtime_views.verify_growth_runtime_token",
            return_value={"run_id": "12345", "repository": "syncworksai/syncworks-backend-prod", "ref": "refs/heads/main"},
        ) as verify_oidc,
        patch("platform_growth.runtime_views.run_due_recipes", return_value=[]) as run_recipes,
        patch("platform_growth.runtime_views.prepare_due_scheduled_posts", return_value={"ready": 2, "skipped": 1}) as prepare_posts,
        patch("platform_growth.runtime_views.publish_ready_scheduled_posts", return_value={"published": 2, "failed": 0, "skipped": 0}) as publish_posts,
    ):
        response = client.post(
            RUNTIME_URL,
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer github-oidc-token",
        )

    assert response.status_code == 200
    assert response.data["ok"] is True
    assert response.data["identity"] == "github:12345"
    assert response.data["scheduled_posts"]["ready"] == 2
    assert response.data["publishing"]["published"] == 2
    verify_oidc.assert_called_once_with("github-oidc-token")
    run_recipes.assert_called_once()
    prepare_posts.assert_called_once()
    publish_posts.assert_called_once()


def test_growth_runtime_keeps_shared_secret_manual_fallback():
    client = APIClient()
    with (
        patch.dict("os.environ", {"GROWTH_RUNTIME_SECRET": "runtime-secret"}, clear=False),
        patch("platform_growth.runtime_views.run_due_recipes", return_value=[]),
        patch("platform_growth.runtime_views.prepare_due_scheduled_posts", return_value={"ready": 0, "skipped": 0}),
        patch("platform_growth.runtime_views.publish_ready_scheduled_posts", return_value={"published": 0, "failed": 0, "skipped": 0}),
    ):
        response = client.post(
            RUNTIME_URL,
            {},
            format="json",
            HTTP_X_SYNCWORKS_RUNTIME_SECRET="runtime-secret",
        )
    assert response.status_code == 200
    assert response.data["identity"] == "shared-secret"
