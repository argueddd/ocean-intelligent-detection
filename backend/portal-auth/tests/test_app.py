import unittest

from app import CAS_NAMESPACE, create_app


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, username: str = "wangqiyue") -> None:
        self.username = username
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append((url, params, timeout))
        xml = (
            f'<cas:serviceResponse xmlns:cas="{CAS_NAMESPACE}">'
            "<cas:authenticationSuccess>"
            f"<cas:user>{self.username}</cas:user>"
            "<cas:attributes>"
            f"<cas:uid>{self.username}</cas:uid>"
            "<cas:displayName>王启跃</cas:displayName>"
            "</cas:attributes>"
            "</cas:authenticationSuccess>"
            "</cas:serviceResponse>"
        )
        return FakeResponse(xml)


class PortalAuthTestCase(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttpClient()
        self.app = create_app(
            {
                "TESTING": True,
                "APP_SECRET_KEY": "test-secret-key",
                "CAS_PUBLIC_URL": "http://cas.example/cas",
                "CAS_INTERNAL_URL": "http://cas-internal/cas",
                "CAS_SERVICE_URL": "http://portal.example/api/auth/callback",
                "PORTAL_PUBLIC_URL": "http://portal.example",
                "SESSION_COOKIE_SECURE": False,
            },
            http_client=self.http,
        )
        self.client = self.app.test_client()

    def test_anonymous_session(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["authenticated"])

    def test_login_callback_creates_portal_session(self):
        login = self.client.get(
            "/api/auth/login", query_string={"return_to": "/?agent=agent-hub"}
        )
        self.assertEqual(login.status_code, 302)
        self.assertTrue(login.location.startswith("http://cas.example/cas/login?"))

        callback = self.client.get(
            "/api/auth/callback", query_string={"ticket": "ST-test-ticket"}
        )
        self.assertEqual(callback.status_code, 302)
        self.assertEqual(callback.location, "/?agent=agent-hub")

        me = self.client.get("/api/auth/me").get_json()
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["user"]["username"], "wangqiyue")
        self.assertEqual(me["user"]["displayName"], "王启跃")
        self.assertNotIn("attributes", me["user"])
        self.assertEqual(
            self.http.requests[0][1]["service"],
            "http://portal.example/api/auth/callback",
        )

    def test_callback_requires_browser_login_flow(self):
        response = self.client.get(
            "/api/auth/callback", query_string={"ticket": "ST-test-ticket"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/?auth_error=invalid_flow")

    def test_external_return_url_is_rejected(self):
        login = self.client.get(
            "/api/auth/login", query_string={"return_to": "https://evil.example"}
        )
        self.assertEqual(login.status_code, 302)
        callback = self.client.get(
            "/api/auth/callback", query_string={"ticket": "ST-test-ticket"}
        )
        self.assertEqual(callback.location, "/")

    def test_logout_clears_local_session(self):
        self.client.get("/api/auth/login")
        self.client.get("/api/auth/callback", query_string={"ticket": "ST-test-ticket"})
        logout = self.client.post(
            "/api/auth/logout", query_string={"return_to": "/?agent=agent-hub"}
        )
        self.assertEqual(logout.status_code, 200)
        self.assertIn("http://cas.example/cas/logout", logout.get_json()["logoutUrl"])
        self.assertIn("agent-hub", logout.get_json()["logoutUrl"])
        self.assertFalse(self.client.get("/api/auth/me").get_json()["authenticated"])

    def test_tampered_session_cookie_is_rejected(self):
        self.client.get("/api/auth/login")
        self.client.get("/api/auth/callback", query_string={"ticket": "ST-test-ticket"})
        cookie = self.client.get_cookie("portal_session")
        self.assertIsNotNone(cookie)
        self.client.set_cookie("portal_session", f"{cookie.value}tampered")

        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["authenticated"])

    def test_health_has_no_external_session_dependency(self):
        response = self.client.get("/api/auth/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
