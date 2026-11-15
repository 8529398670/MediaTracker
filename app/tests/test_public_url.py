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

    def test_a_trusted_proxy_range_is_narrow(self) -> None:
        """S13: server.trusted_proxies refuses any range that trusts far more
        than a proxy, not just /0. Each of these trusts every address, or
        every container."""
        for value in (
            "0.0.0.0/0", "::/0", "1.2.3.4/0", "::1/0", "0.0.0.0/1", "128.0.0.0/1", "10.0.0.0/7",
            "2001::/15", "::ffff:0.0.0.0/96", "::ffff:10.0.0.0/100",
        ):
            self.assertFalse(config._narrow_enough_proxy(config._proxy_network(value)), value)
        for value in (
            "127.0.0.1", "::1", "172.17.0.1", "10.0.0.0/8", "173.245.48.0/20", "104.16.0.0/13",
            "2400:cb00::/32", "2001::/16", "::ffff:10.0.0.0/104",
        ):
            self.assertTrue(config._narrow_enough_proxy(config._proxy_network(value)), value)


if __name__ == "__main__":
    unittest.main()
