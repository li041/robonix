# SPDX-License-Identifier: MulanPSL-2.0
from __future__ import annotations

import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from robonix_api.capability import (
    Service,
    _mcp_loopback_allowed_hosts,
    _provider_bind_host,
)


class ProviderBindHostTest(unittest.TestCase):
    def test_default_and_loopback_values_are_normalized(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_provider_bind_host(), "0.0.0.0")
        self.assertEqual(_provider_bind_host(" 127.0.0.1 "), "127.0.0.1")

    def test_hostname_ipv6_and_empty_values_are_rejected(self) -> None:
        for value in ("", "localhost", "::1", "not-an-address"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _provider_bind_host(value)

    def test_loopback_bind_is_advertised_without_route_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"ROBONIX_PROVIDER_BIND_HOST": "127.0.0.1"},
            clear=True,
        ):
            provider = Service(
                id="test_provider",
                namespace="robonix/service/test",
                pkg_root=Path(directory),
            )
            with mock.patch.object(provider, "resolve_host_ip") as resolve:
                self.assertEqual(provider._advertise_host(), "127.0.0.1")
                resolve.assert_not_called()

    def test_explicit_advertise_host_remains_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "ROBONIX_PROVIDER_BIND_HOST": "127.0.0.1",
                "ROBONIX_ADVERTISE_HOST": "10.20.30.40",
            },
            clear=True,
        ):
            provider = Service(
                id="test_provider",
                namespace="robonix/service/test",
                pkg_root=Path(directory),
            )
            self.assertEqual(provider._advertise_host(), "10.20.30.40")

    def test_loopback_mcp_host_allowlist_covers_dynamic_port(self) -> None:
        self.assertEqual(
            _mcp_loopback_allowed_hosts("127.0.0.1"),
            ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
        )
        self.assertEqual(_mcp_loopback_allowed_hosts("0.0.0.0"), [])

    def test_all_provider_server_paths_use_one_bind_host(self) -> None:
        source = Path(__file__).parents[1] / "robonix_api" / "capability.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('FastMCP(\n            self.id,\n            host=self._bind_host,', text)
        self.assertIn("enable_dns_rebinding_protection=protect_loopback", text)
        self.assertIn("allowed_hosts=_mcp_loopback_allowed_hosts(self._bind_host)", text)
        self.assertIn('host=self._bind_host,\n            port=self._mcp_port', text)

    def test_mcp_server_uses_the_configured_port(self) -> None:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"ROBONIX_MCP_PORT": str(port), "ROBONIX_PROVIDER_BIND_HOST": "127.0.0.1"},
            clear=True,
        ):
            provider = Service(
                id="test_provider",
                namespace="robonix/service/test",
                pkg_root=Path(directory),
            )
            provider._mcp_app = mock.Mock()
            with mock.patch("uvicorn.Server"), mock.patch("threading.Thread"):
                provider._start_mcp_server()
            self.assertEqual(provider._mcp_port, port)


if __name__ == "__main__":
    unittest.main()
