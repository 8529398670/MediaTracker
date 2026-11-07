"""Outbound fetches never reach a private address: not by name, not through
a DNS answer that mixes one in, not through a redirect, and the poster cache
fetches only what the server itself registered from allowed hosts."""
from __future__ import annotations

import socket
import unittest
import urllib.error
import urllib.request
from unittest import mock

from app.providers import net
from app.reference.images import ImageCache


def answers(*addresses: str):  # type: ignore[no-untyped-def]
    return lambda host, port, **kwargs: [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]


class AddressTest(unittest.TestCase):
    def test_private_and_special_addresses_are_unsafe(self) -> None:
        for address in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fe80::1", "0.0.0.0", "100.64.0.1"):
            self.assertTrue(net.unsafe_ip(address), address)
        self.assertFalse(net.unsafe_ip("93.184.216.34"))

    def test_one_private_answer_among_public_ones_is_refused(self) -> None:
        with mock.patch("socket.getaddrinfo", answers("93.184.216.34", "10.0.0.5")):
            with self.assertRaises(net.UnsafeAddressError):
                net.resolve_public("rebind.example", 443)
        with mock.patch("socket.getaddrinfo", answers("93.184.216.34")):
            self.assertEqual(net.resolve_public("ok.example", 443)[1], "93.184.216.34")

    def test_redirects_may_not_downgrade_or_leave_the_web(self) -> None:
        handler = net._SafeRedirectHandler()
        request = urllib.request.Request("https://a.example/x")
        for target in ("http://a.example/y", "file:///etc/passwd", "gopher://x"):
            with self.assertRaises(urllib.error.HTTPError):
                handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_switched_off_means_no_request(self) -> None:
        net.configure(False, "t", 5)
        try:
            with self.assertRaises(net.NetworkOff):
                net.fetch_json("https://example.com/")
        finally:
            net.configure(True, "t", 5)


class ImageCacheTest(unittest.TestCase):
    def test_only_registered_allowed_urls_are_fetched(self) -> None:
        cache = ImageCache()
        cache.allow_hosts = ("image.tmdb.org", "*.wikimedia.org")
        self.assertTrue(cache.allowed("https://image.tmdb.org/t/p/w342/x.jpg"))
        self.assertTrue(cache.allowed("https://upload.wikimedia.org/a.jpg"))
        self.assertFalse(cache.allowed("http://image.tmdb.org/x.jpg"))
        self.assertFalse(cache.allowed("https://evil.example/x.jpg"))
        self.assertEqual(cache.path_for("https://evil.example/x.jpg"), "")
        fetched = []
        self.assertIsNone(cache.fetch("0" * 32, lambda *args, **kwargs: fetched.append(args)))
        self.assertEqual(fetched, [])


if __name__ == "__main__":
    unittest.main()
