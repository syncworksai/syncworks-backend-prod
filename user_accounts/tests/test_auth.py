from rest_framework.test import APITestCase


class TestAuth(APITestCase):
    def test_register_and_login(self):
        r = self.client.post(
            "/api/v1/auth/register/",
            {"email": "t1@test.com", "username": "t1@test.com", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertIn("token", r.data)

        r2 = self.client.post(
            "/api/v1/auth/login/",
            {"identifier": "t1@test.com", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertIn("token", r2.data)
