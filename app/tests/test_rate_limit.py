"""The rate limiter: a page's files never spend the budget, the two budgets are
separate, and no spelling of a path gets around either."""
from __future__ import annotations

import asyncio
import contextlib
import io
import unittest
from dataclasses import dataclass, field

from app.core.middleware import BUDGET_GENERAL, BUDGET_NONE, BUDGET_SIGN_IN, RateLimit, budget_for, rate_key


@dataclass
class Settings:
    rate_limit_max: int = 2
    rate_limit_signin_max: int = 2
    rate_limit_window_seconds: int = 60
    trust_proxy: bool = False
    trusted_proxies: tuple = field(default_factory=tuple)
    proxy_header: str = "X-Forwarded-For"

    def get(self) -> "Settings":
        return self


class Limited:
    """RateLimit in front of an app that always answers 200."""

    def __init__(self, **settings: int) -> None:
        async def app(scope: dict, receive: object, send: object) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        self.limiter = RateLimit(app, Settings(**settings))  # type: ignore[arg-type]

    def status(self, method: str, path: str, client: str = "10.0.0.1", headers: dict[str, str] | None = None) -> int:
        seen: list[int] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b""}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                seen.append(message["status"])

        raw = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
        scope = {"type": "http", "method": method, "path": path, "headers": raw, "client": (client, 1)}
        asyncio.run(self.limiter(scope, receive, send))  # type: ignore[arg-type]
        return seen[0]


class BudgetTest(unittest.TestCase):
    def test_sorting(self) -> None:
        cases = {
            ("GET", "/js/app.js"): BUDGET_NONE,
            ("HEAD", "/css/style.css"): BUDGET_NONE,
            ("GET", "/vendor/bootstrap/bootstrap.min.js"): BUDGET_NONE,
            ("GET", "/"): BUDGET_GENERAL,
            ("GET", "/settings"): BUDGET_GENERAL,
            ("GET", "/api/me"): BUDGET_GENERAL,
            ("GET", "/api/files/abc/chunks/1"): BUDGET_GENERAL,
            ("POST", "/api/files/abc/finish"): BUDGET_GENERAL,
            ("POST", "/api/files/abc/chunks"): BUDGET_GENERAL,
            ("GET", "/api/login/options"): BUDGET_GENERAL,
            ("POST", "/js/app.js"): BUDGET_GENERAL,
            ("GET", "/login/abc.def"): BUDGET_GENERAL,
            ("GET", "/join/abc.def"): BUDGET_GENERAL,
            ("POST", "/api/login"): BUDGET_SIGN_IN,
            ("POST", "/api/login/two-factor"): BUDGET_SIGN_IN,
            ("POST", "/api/login/password"): BUDGET_SIGN_IN,
            ("POST", "/api/join/create"): BUDGET_SIGN_IN,
            ("POST", "/API/Login/"): BUDGET_SIGN_IN,
            ("GET", "/API/owner/logs/days/2026.11"): BUDGET_GENERAL,
            ("GET", "/MCP.json"): BUDGET_GENERAL,
        }
        for (method, path), expected in cases.items():
            with self.subTest(f"{method} {path}"):
                self.assertEqual(budget_for(method, path), expected)


class RateLimitTest(unittest.TestCase):
    def test_static_files_never_spend_the_budget(self) -> None:
        limited = Limited()
        for _ in range(50):
            for path in ("/js/app.js", "/css/style.css", "/vendor/x.min.js"):
                self.assertEqual(limited.status("GET", path), 200)
        self.assertEqual(limited.status("GET", "/api/me"), 200)
        self.assertEqual(limited.status("GET", "/api/me"), 200)
        self.assertEqual(limited.status("GET", "/api/me"), 429)

    def test_the_budgets_are_separate(self) -> None:
        limited = Limited(rate_limit_max=3)
        self.assertEqual(limited.status("POST", "/api/login"), 200)
        self.assertEqual(limited.status("POST", "/api/login"), 200)
        self.assertEqual(limited.status("POST", "/api/login/password"), 429)
        self.assertEqual(limited.status("POST", "/api/join/claim"), 429, "joining shares the sign-in budget")
        self.assertEqual(limited.status("GET", "/api/me"), 200, "sign-in spent the general budget")

    def test_the_page_itself_still_counts(self) -> None:
        limited = Limited(rate_limit_max=1)
        self.assertEqual(limited.status("GET", "/"), 200)
        self.assertEqual(limited.status("GET", "/"), 429)

    def test_ipv6_is_counted_by_its_slash_64(self) -> None:
        """S10: picking a new address inside one /64 does not get a new
        budget. IPv4 is counted as it is."""
        self.assertEqual(rate_key("2001:db8:1:2::1"), rate_key("2001:db8:1:2:ffff::9"))
        self.assertNotEqual(rate_key("2001:db8:1:2::1"), rate_key("2001:db8:1:3::1"))
        self.assertEqual(rate_key("192.0.2.1"), "192.0.2.1")
        self.assertEqual(rate_key("::ffff:192.0.2.1"), "192.0.2.1")
        limited = Limited(rate_limit_signin_max=5)
        with contextlib.redirect_stdout(io.StringIO()):
            refused = sum(limited.status("POST", "/api/login", client=f"2001:db8:1:2::{count:x}") == 429 for count in range(1, 13))
        self.assertEqual(refused, 12 - 5)

    def test_proxy_headers_and_refusals_are_logged(self) -> None:
        """S10: a request through a proxy the server does not trust is warned
        about once per process, and the first 429 a budget gives in a window
        is logged, once."""
        limited = Limited(rate_limit_signin_max=5)
        written = io.StringIO()
        with contextlib.redirect_stdout(written):
            for _ in range(8):
                limited.status("POST", "/api/login", headers={"CF-Connecting-IP": "198.51.100.7"})
        text = written.getvalue()
        self.assertEqual(text.count("CF-Connecting-IP"), 1, text)
        self.assertIn("server.trust_proxy", text)
        self.assertEqual(text.count("budget used up"), 1, text)
        self.assertIn("sign-in budget", text)


if __name__ == "__main__":
    unittest.main()
