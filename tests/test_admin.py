"""Tests for the admin panel."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lb.admin import AdminServer
from lb.node import BatteryNode


class TestAdminServer:
    """Tests for the admin panel server."""

    @pytest.mark.asyncio
    async def test_admin_server_start_stop(self):
        """Test that admin server can start and stop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            server = AdminServer(node)

            await server.start("127.0.0.1", 0)  # Port 0 = random available port
            assert server._server is not None

            await server.stop()

    @pytest.mark.asyncio
    async def test_admin_api_node(self):
        """Test the /api/node endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            server = AdminServer(node)

            status, content_type, body = await server._handle_api_node("GET", {})

            assert status == 200
            assert "application/json" in content_type

            data = json.loads(body.decode())
            assert "node_id" in data
            assert "sign_pub" in data
            assert "enc_pub" in data
            assert "version" in data

    @pytest.mark.asyncio
    async def test_admin_api_groups(self):
        """Test the /api/groups endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            # Create a test group
            gid = node.create_group("test:admin")

            server = AdminServer(node)
            status, content_type, body = await server._handle_api_groups("GET", {})

            assert status == 200
            data = json.loads(body.decode())
            assert "groups" in data
            assert len(data["groups"]) == 1
            assert data["groups"][0]["name"] == "test:admin"

    @pytest.mark.asyncio
    async def test_admin_api_group_detail(self):
        """Test the /api/group endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            gid = node.create_group("test:detail")

            server = AdminServer(node)

            # Test with valid group
            status, content_type, body = await server._handle_api_group_detail("GET", {"id": [gid]})
            assert status == 200
            data = json.loads(body.decode())
            assert data["group_id"] == gid
            assert data["name"] == "test:detail"
            assert "members" in data

            # Test with invalid group
            status, _, body = await server._handle_api_group_detail("GET", {"id": ["invalid"]})
            assert status == 404

    @pytest.mark.asyncio
    async def test_admin_api_claims(self):
        """Test the /api/claims endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            gid = node.create_group("test:claims")
            node.publish_claim(gid, "Test claim content", ["test", "admin"])

            server = AdminServer(node)
            status, content_type, body = await server._handle_api_claims("GET", {"group_id": [gid]})

            assert status == 200
            data = json.loads(body.decode())
            assert "claims" in data
            assert len(data["claims"]) == 1
            assert "Test claim" in data["claims"][0]["text"]

    @pytest.mark.asyncio
    async def test_admin_api_peers(self):
        """Test the /api/peers endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            server = AdminServer(node)
            status, content_type, body = await server._handle_api_peers("GET", {})

            assert status == 200
            data = json.loads(body.decode())
            assert "peers" in data

    @pytest.mark.asyncio
    async def test_admin_api_subscriptions(self):
        """Test the /api/subscriptions endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            server = AdminServer(node)
            status, content_type, body = await server._handle_api_subscriptions("GET", {})

            assert status == 200
            data = json.loads(body.decode())
            assert "subscriptions" in data

    @pytest.mark.asyncio
    async def test_admin_api_offers(self):
        """Test the /api/offers endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            server = AdminServer(node)
            status, content_type, body = await server._handle_api_offers("GET", {})

            assert status == 200
            data = json.loads(body.decode())
            assert "offers" in data

    @pytest.mark.asyncio
    async def test_admin_dashboard_html(self):
        """Test the dashboard HTML is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            server = AdminServer(node)
            status, content_type, body = await server._handle_dashboard("GET", {})

            assert status == 200
            assert "text/html" in content_type

            html = body.decode()
            assert "Learning Battery Market" in html
            assert "Admin Panel" in html
            assert "nav-tab" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
