"""Tests for sync daemon, peer registry, and auto-sync functionality."""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

# Import the modules we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lb.registry import PeerRegistry, Peer, Subscription
from lb.sync_daemon import SyncDaemon
from lb.node import BatteryNode
from lb.p2p import P2PServer
from lb.config import get_config


class TestPeerRegistry:
    """Tests for peer registry."""

    def test_peer_add_and_list(self):
        """Test adding and listing peers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            peer = Peer(
                host="127.0.0.1",
                port=7337,
                node_id="abc123def456",
                sign_pub="test_sign_pub",
                enc_pub="test_enc_pub",
                alias="test-peer",
                last_seen_ms=int(time.time() * 1000),
                last_error=None,
                added_ms=int(time.time() * 1000),
            )
            registry.add_peer(peer)

            peers = registry.list_peers()
            assert len(peers) == 1
            assert peers[0].host == "127.0.0.1"
            assert peers[0].alias == "test-peer"

    def test_peer_persistence(self):
        """Test that peers persist across registry instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Create registry and add peer
            registry1 = PeerRegistry(path)
            peer = Peer(
                host="10.0.0.1",
                port=9000,
                node_id="xyz789",
                sign_pub="sign_pub_xyz",
                enc_pub="enc_pub_xyz",
                alias="persistent-peer",
                last_seen_ms=1000,
                last_error=None,
                added_ms=1000,
            )
            registry1.add_peer(peer)

            # Create new registry instance
            registry2 = PeerRegistry(path)
            peers = registry2.list_peers()
            assert len(peers) == 1
            assert peers[0].node_id == "xyz789"

    def test_peer_remove(self):
        """Test removing a peer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            peer = Peer(
                host="192.168.1.1",
                port=8000,
                node_id="remove_me",
                sign_pub="pub",
                enc_pub="enc",
                alias=None,
                last_seen_ms=1000,
                last_error=None,
                added_ms=1000,
            )
            registry.add_peer(peer)
            assert len(registry.list_peers()) == 1

            result = registry.remove_peer("192.168.1.1:8000")
            assert result is True
            assert len(registry.list_peers()) == 0

    def test_peer_status_update(self):
        """Test updating peer status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            peer = Peer(
                host="127.0.0.1",
                port=7337,
                node_id="status_test",
                sign_pub="pub",
                enc_pub="enc",
                alias=None,
                last_seen_ms=1000,
                last_error=None,
                added_ms=1000,
            )
            registry.add_peer(peer)

            # Update with error
            registry.update_peer_status("127.0.0.1:7337", last_seen_ms=2000, error="connection timeout")
            updated = registry.get_peer("127.0.0.1:7337")
            assert updated.last_seen_ms == 2000
            assert updated.last_error == "connection timeout"


class TestSubscription:
    """Tests for subscription management."""

    def test_subscription_add_and_list(self):
        """Test adding and listing subscriptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            sub = Subscription(
                group_id="group_abc123",
                peer_host="127.0.0.1",
                peer_port=7337,
                sync_interval_s=300,
                enabled=True,
                last_sync_ms=0,
                last_error=None,
            )
            registry.subscribe(sub)

            subs = registry.list_subscriptions()
            assert len(subs) == 1
            assert subs[0].group_id == "group_abc123"
            assert subs[0].sync_interval_s == 300

    def test_subscription_persistence(self):
        """Test that subscriptions persist across instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # Create and add subscription
            registry1 = PeerRegistry(path)
            sub = Subscription(
                group_id="persistent_group",
                peer_host="10.0.0.1",
                peer_port=9000,
                sync_interval_s=600,
                enabled=True,
                last_sync_ms=5000,
                last_error=None,
            )
            registry1.subscribe(sub)

            # Load in new instance
            registry2 = PeerRegistry(path)
            subs = registry2.list_subscriptions()
            assert len(subs) == 1
            assert subs[0].group_id == "persistent_group"
            assert subs[0].sync_interval_s == 600

    def test_subscription_unsubscribe(self):
        """Test unsubscribing from a group."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            sub = Subscription(
                group_id="to_remove",
                peer_host="127.0.0.1",
                peer_port=7337,
                sync_interval_s=300,
                enabled=True,
                last_sync_ms=0,
                last_error=None,
            )
            registry.subscribe(sub)
            assert len(registry.list_subscriptions()) == 1

            result = registry.unsubscribe("to_remove")
            assert result is True
            assert len(registry.list_subscriptions()) == 0

    def test_subscription_is_due(self):
        """Test checking if subscription is due for sync."""
        sub = Subscription(
            group_id="test",
            peer_host="127.0.0.1",
            peer_port=7337,
            sync_interval_s=60,  # 60 seconds
            enabled=True,
            last_sync_ms=1000,
            last_error=None,
        )

        # Not due yet (at 30 seconds)
        assert not sub.is_due(now_ms=31000)

        # Due (at 61 seconds)
        assert sub.is_due(now_ms=62000)

        # Disabled - never due
        sub.enabled = False
        assert not sub.is_due(now_ms=100000)

    def test_subscription_set_interval(self):
        """Test setting sync interval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            sub = Subscription(
                group_id="interval_test",
                peer_host="127.0.0.1",
                peer_port=7337,
                sync_interval_s=300,
                enabled=True,
                last_sync_ms=0,
                last_error=None,
            )
            registry.subscribe(sub)

            registry.set_sync_interval("interval_test", 600)
            updated = registry.get_subscription("interval_test")
            assert updated.sync_interval_s == 600

    def test_subscription_enable_disable(self):
        """Test enabling/disabling subscription."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            sub = Subscription(
                group_id="enable_test",
                peer_host="127.0.0.1",
                peer_port=7337,
                sync_interval_s=300,
                enabled=True,
                last_sync_ms=0,
                last_error=None,
            )
            registry.subscribe(sub)

            registry.set_enabled("enable_test", False)
            updated = registry.get_subscription("enable_test")
            assert updated.enabled is False


class TestSyncDaemon:
    """Tests for sync daemon."""

    @pytest.mark.asyncio
    async def test_daemon_start_stop(self):
        """Test daemon start and stop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            registry = node.peer_registry

            daemon = SyncDaemon(node, registry)

            # Start
            await daemon.start()
            status = daemon.get_status()
            assert status["running"] is True

            # Stop
            await daemon.stop()
            status = daemon.get_status()
            assert status["running"] is False

    @pytest.mark.asyncio
    async def test_daemon_status(self):
        """Test getting daemon status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))
            registry = node.peer_registry

            # Add a subscription
            sub = Subscription(
                group_id="status_test",
                peer_host="127.0.0.1",
                peer_port=7337,
                sync_interval_s=300,
                enabled=True,
                last_sync_ms=0,
                last_error=None,
            )
            registry.subscribe(sub)

            daemon = SyncDaemon(node, registry)
            status = daemon.get_status()

            assert status["subscriptions_total"] == 1
            assert status["subscriptions_enabled"] == 1


class TestNodeRegistryIntegration:
    """Tests for BatteryNode registry integration."""

    def test_node_peer_registry_property(self):
        """Test that node.peer_registry works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            # Access registry (lazy-loaded)
            registry = node.peer_registry
            assert registry is not None

            # Same instance on second access
            registry2 = node.peer_registry
            assert registry is registry2

    def test_node_subscribe_to_group(self):
        """Test subscribing to a group via node."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = BatteryNode.init(Path(tmpdir))

            sub = node.subscribe_to_group(
                group_id="test_group",
                peer_host="192.168.1.100",
                peer_port=7337,
                sync_interval_s=120,
            )

            assert sub.group_id == "test_group"
            assert sub.peer_host == "192.168.1.100"
            assert sub.sync_interval_s == 120

            # Verify in registry
            loaded = node.peer_registry.get_subscription("test_group")
            assert loaded is not None
            assert loaded.group_id == "test_group"


class TestIntegrationWithP2P:
    """Integration tests with P2P server."""

    @pytest.mark.asyncio
    async def test_group_discovery(self):
        """Test discovering groups from a peer."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            nodeA = BatteryNode.init(Path(d1))
            nodeB = BatteryNode.init(Path(d2))

            # Create a group on node A
            gid = nodeA.create_group("test:discovery")

            # Start server
            srv = P2PServer(nodeA)
            await srv.start("127.0.0.1", 0)
            port = srv._server.sockets[0].getsockname()[1]
            task = asyncio.create_task(srv.serve_forever())

            try:
                # Discover groups from node B
                groups = await nodeB.discover_groups_from_peer("127.0.0.1", port)

                assert len(groups) == 1
                assert groups[0]["group_id"] == gid
                assert groups[0]["name"] == "test:discovery"
                assert groups[0]["is_member"] is False  # nodeB is not a member

            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class TestRegistryStats:
    """Tests for registry statistics."""

    def test_stats(self):
        """Test getting registry stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = PeerRegistry(Path(tmpdir))

            # Add peers
            for i in range(3):
                peer = Peer(
                    host=f"192.168.1.{i}",
                    port=7337,
                    node_id=f"node_{i}",
                    sign_pub=f"pub_{i}",
                    enc_pub=f"enc_{i}",
                    alias=None,
                    last_seen_ms=1000,
                    last_error="error" if i == 0 else None,
                    added_ms=1000,
                )
                registry.add_peer(peer)

            # Add subscriptions
            for i in range(2):
                sub = Subscription(
                    group_id=f"group_{i}",
                    peer_host="127.0.0.1",
                    peer_port=7337,
                    sync_interval_s=300,
                    enabled=(i == 0),  # Only first enabled
                    last_sync_ms=0,
                    last_error="error" if i == 1 else None,
                )
                registry.subscribe(sub)

            stats = registry.stats()
            assert stats["peer_count"] == 3
            assert stats["subscription_count"] == 2
            assert stats["enabled_subscriptions"] == 1
            assert stats["peers_with_errors"] == 1
            assert stats["subs_with_errors"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
