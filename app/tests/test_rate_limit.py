"""The rate limiter: a page's files never spend the budget, the two budgets are
separate, and no spelling of a path gets around either."""
from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, field

from app.core.middleware import BUDGET_GENERAL, BUDGET_NONE, BUDGET_SIGN_IN, RateLimit, budget_for


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

    def status(self, method: str, path: str) -> int:
        seen: list[int] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b""}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                seen.append(message["status"])

        scope = {"type": "http", "method": method, "path": path, "headers": [], "client": ("10.0.0.1", 1)}
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


if __name__ == "__main__":
    unittest.main()
