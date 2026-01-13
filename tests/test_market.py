import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from lb.node import BatteryNode
from lb.p2p import P2PServer, rpc_call, RPCError


class TestMarketEndToEnd(unittest.TestCase):
    def test_offer_purchase_flow(self):
        async def run():
            with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                nodeA = BatteryNode.init(Path(d1))
                nodeB = BatteryNode.init(Path(d2))

                gid = nodeA.create_group("demo")
                # mint to buyer (B)
                nodeA.mint(gid, nodeB.keys.sign_pub_b64, 1000)

                # create offer on A
                offer_id, package_hash = nodeA.create_offer(
                    gid,
                    title="Test Offer",
                    text="hello world",
                    price=250,
                    tags=["demo"],
                    announce_host="127.0.0.1",
                    announce_port=0,
                )

                srv = P2PServer(nodeA)
                await srv.start("127.0.0.1", 0)
                port = srv._server.sockets[0].getsockname()[1]
                task = asyncio.create_task(srv.serve_forever())

                try:
                    # B pulls offer announcements
                    imported = await nodeB.pull_market_offers_from_peer("127.0.0.1", port)
                    self.assertGreaterEqual(imported, 1)

                    # B purchases
                    ph, pt = await nodeB.purchase_offer_from_peer(host="127.0.0.1", port=port, offer_id=offer_id)
                    self.assertEqual(ph, package_hash)
                    pkg = json.loads(pt.decode("utf-8"))
                    self.assertEqual(pkg.get("text"), "hello world")

                    # check balances updated in A's group
                    buyer_bal = nodeA.balance(gid, nodeB.keys.sign_pub_b64)
                    seller_bal = nodeA.balance(gid, nodeA.keys.sign_pub_b64)
                    self.assertEqual(buyer_bal, 750)
                    self.assertEqual(seller_bal, 250)

                    # grant recorded
                    key = f"{offer_id}:{nodeB.keys.sign_pub_b64}"
                    self.assertIn(key, nodeA.groups[gid].chain.state.grants)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())


class TestAccessControl(unittest.TestCase):
    def test_private_cas_requires_membership(self):
        async def run():
            with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                nodeA = BatteryNode.init(Path(d1))
                nodeC = BatteryNode.init(Path(d2))

                gid = nodeA.create_group("demo")
                claim_hash = nodeA.publish_claim(gid, "secret claim", ["x"])

                srv = P2PServer(nodeA)
                await srv.start("127.0.0.1", 0)
                port = srv._server.sockets[0].getsockname()[1]
                task = asyncio.create_task(srv.serve_forever())
                try:
                    with self.assertRaises(RPCError) as cm:
                        await rpc_call("127.0.0.1", port, nodeC, "cas_get", {"hash": claim_hash})
                    self.assertEqual(cm.exception.code, "forbidden")
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())

    def test_public_package_is_fetchable(self):
        async def run():
            with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                nodeA = BatteryNode.init(Path(d1))
                nodeC = BatteryNode.init(Path(d2))
                gid = nodeA.create_group("demo")
                offer_id, package_hash = nodeA.create_offer(
                    gid,
                    title="PublicPkg",
                    text="ciphertext visible",
                    price=0,
                    tags=["demo"],
                    announce_host="127.0.0.1",
                    announce_port=0,
                )
                srv = P2PServer(nodeA)
                await srv.start("127.0.0.1", 0)
                port = srv._server.sockets[0].getsockname()[1]
                task = asyncio.create_task(srv.serve_forever())
                try:
                    res = await rpc_call("127.0.0.1", port, nodeC, "cas_get", {"hash": package_hash})
                    self.assertEqual(res["hash"], package_hash)
                    self.assertIn("data_b64", res)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())


class TestGroupSync(unittest.TestCase):
    def test_sync_rebuilds_graph(self):
        async def run():
            with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                nodeA = BatteryNode.init(Path(d1))
                nodeB = BatteryNode.init(Path(d2))
                gid = nodeA.create_group("demo")
                # add B as member
                nodeA.add_member(gid, nodeB.keys.sign_pub_b64, role="member")
                # publish claim
                nodeA.publish_claim(gid, "capture compiler invocation", ["build"])

                srv = P2PServer(nodeA)
                await srv.start("127.0.0.1", 0)
                port = srv._server.sockets[0].getsockname()[1]
                task = asyncio.create_task(srv.serve_forever())
                try:
                    replaced = await nodeB.sync_group_from_peer("127.0.0.1", port, gid)
                    self.assertTrue(replaced)
                    ctx, _ = nodeB.compile_context(gid, "how to debug build", top_k=4)
                    self.assertIn("capture compiler invocation", ctx)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
