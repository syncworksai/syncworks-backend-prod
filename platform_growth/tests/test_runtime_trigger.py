from unittest.mock import patch

from rest_framework.test import APIClient


RUNTIME_URL = "/api/v1/platform-growth/growth/runtime/run/"


def test_growth_runtime_rejects_missing_secret():
    client = APIClient()
    with patch.dict("os.environ", {"GROWTH_RUNTIME_SECRET": "runtime-secret"}, clear=False):
        response = client.post(RUNTIME_URL, {}, format="json")
    assert response.status_code == 403


def test_growth_runtime_is_inactive_when_server_secret_missing():
    client = APIClient()
    with patch.dict("os.environ", {"GROWTH_RUNTIME_SECRET": ""}, clear=False):
        response = client.post(
            RUNTIME_URL,
            {},
            format="json",
            HTTP_X_SYNCWORKS_RUNTIME_SECRET="anything",
        )
    assert response.status_code == 503


def test_growth_runtime_runs_all_background_stages_with_valid_secret():
    client = APIClient()
    with (
        patch.dict("os.environ", {"GROWTH_RUNTIME_SECRET": "runtime-secret"}, clear=False),
        patch("platform_growth.runtime_views.run_due_recipes", return_value=[]) as run_recipes,
        patch("platform_growth.runtime_views.prepare_due_scheduled_posts", return_value={"ready": 2, "skipped": 1}) as prepare_posts,
        patch("platform_growth.runtime_views.publish_ready_scheduled_posts", return_value={"published": 2, "failed": 0, "skipped": 0}) as publish_posts,
    ):
        response = client.post(
            RUNTIME_URL,
            {},
            format="json",
            HTTP_X_SYNCWORKS_RUNTIME_SECRET="runtime-secret",
        )

    assert response.status_code == 200
    assert response.data["ok"] is True
    assert response.data["scheduled_posts"]["ready"] == 2
    assert response.data["publishing"]["published"] == 2
    run_recipes.assert_called_once()
    prepare_posts.assert_called_once()
    publish_posts.assert_called_once()
