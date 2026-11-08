"""What a browser, and a script, get when a request fails."""
from __future__ import annotations

from typing import Any

from starlette.routing import Route
from starlette.testclient import TestClient

from app.tests.route_support import RoutesTestCase

BROWSER = "text/html,application/xhtml+xml,*/*;q=0.8"


class ErrorPageCase(RoutesTestCase):
    def fetch(self, path: str, accept: str = "", client: Any = None) -> Any:
        return (client or self.client).get(path, headers={"accept": accept} if accept else {})


class NotFoundTests(ErrorPageCase):
    def test_a_browser_gets_the_page(self) -> None:
        for path in ["/settings", "/nope.css", "/a/b/"]:
            response = self.fetch(path, BROWSER)
            self.assertEqual(response.status_code, 404, path)
            self.assertTrue(response.headers["content-type"].startswith("text/html"), path)
            self.assertIn("Page not found", response.text, path)
            self.assertEqual(response.headers["cache-control"], "no-store", path)
            self.assertIn("content-security-policy", response.headers, path)

    def test_a_script_keeps_the_plain_answer(self) -> None:
        for accept in ["*/*", "text/css"]:
            response = self.fetch("/nope.css", accept)
            self.assertEqual((response.status_code, response.text), (404, "Not found"), accept)

    def test_the_api_stays_json_even_for_a_browser(self) -> None:
        response = self.fetch("/api/nope", BROWSER)
        self.assertEqual((response.status_code, response.json()), (404, {"error": "not found"}))

    def test_the_app_pages_still_serve(self) -> None:
        paths = ["/", "/login/some-credential", "/index.html"]
        paths.append("/join/some-credential")
        for path in paths:
            response = self.fetch(path, BROWSER)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('id="users-table"', response.text, path)

    def test_favicon_and_robots_exist(self) -> None:
        self.assertEqual(self.fetch("/favicon.ico").status_code, 200)
        robots = self.fetch("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Disallow: /", robots.text)


class CrashTests(ErrorPageCase):
    def setUp(self) -> None:
        super().setUp()

        async def boom(request: Any) -> Any:
            raise RuntimeError("the disk is on fire")

        self.app.router.routes.insert(0, Route("/boom", boom))

    def test_a_browser_sees_a_reference_and_no_detail(self) -> None:
        response = self.fetch("/boom", BROWSER)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Reference: " + response.headers["x-request-id"], response.text)
        self.assertNotIn("fire", response.text)

    def test_a_script_keeps_json(self) -> None:
        response = self.fetch("/boom", "application/json")
        self.assertEqual(response.json()["request_id"], response.headers["x-request-id"])

    def test_a_crash_keeps_the_security_headers(self) -> None:
        for accept in [BROWSER, "application/json"]:
            headers = self.fetch("/boom", accept).headers
            self.assertEqual(headers["x-frame-options"], "DENY", accept)
            self.assertIn("content-security-policy", headers, accept)
            self.assertEqual(headers["x-robots-tag"], "noindex, nofollow", accept)


class RateLimitedTests(ErrorPageCase):
    def test_a_browser_gets_the_page_and_the_api_keeps_json(self) -> None:
        self.set_config(rate_limit_max=1)
        client = TestClient(self.app, raise_server_exceptions=False)
        self.fetch("/", BROWSER, client)
        page = self.fetch("/", BROWSER, client)
        self.assertEqual(page.status_code, 429)
        self.assertIn("Too many requests", page.text)
        self.assertIn("retry-after", page.headers)
        api = self.fetch("/api/me", BROWSER, client)
        self.assertEqual((api.status_code, api.json()), (429, {"error": "too many requests"}))


class HeaderTests(ErrorPageCase):
    def test_every_answer_says_noindex(self) -> None:
        for path in ["/", "/nope", "/api/health", "/robots.txt"]:
            self.assertEqual(self.fetch(path).headers["x-robots-tag"], "noindex, nofollow", path)
