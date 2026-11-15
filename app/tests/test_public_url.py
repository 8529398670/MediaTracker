"""server.public_url as the .bat scripts print it. Go's twin is
server/config/public_url_test.go."""
from __future__ import annotations

import unittest

from app.core import config


class PublicURLTest(unittest.TestCase):
    def test_public_url_is_a_plain_origin(self) -> None:
        """F11: scripts\\run.bat and login.bat print server.public_url, and cmd
        runs whatever follows a & | < > ^ % or " in it. Only a plain origin passes."""
        for value in (
            "https://a&calc&b", "https://a|b", 'https://a"b', "https://a%b", "https://a^b",
            "https://a b", "https://a<b", "https://a>b", "https://a!b", "https://(a)",
            "ftp://a.example.com", "https://a.example.com/path", "https://a.example.com:port",
        ):
            self.assertFalse(config._valid_public_url(value), value)
        for value in (
            "", "https://app.example.com", "https://app.example.com:8443/", "http://[::1]:8080",
            "http://127.0.0.1:3000", "http://localhost:8080",
        ):
            self.assertTrue(config._valid_public_url(value), value)



if __name__ == "__main__":
    unittest.main()
