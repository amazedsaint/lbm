"""Tests for chain validation, fork resolution, and transactions.

Tests core chain functionality including:
- Block validation
- Fork resolution logic
- Transaction types (including transfer)
- Block size limits
"""
import time
import pytest

from lb.chain import Chain, Block, ChainError, GroupState, GroupPolicy
from lb.keys import gen_node_keys


def make_chain(creator_keys, name="TestGroup", currency="TEST"):
    """Helper to create a chain with a genesis block."""
    genesis = Chain.make_genesis(
        name,
        group_id=None,
        creator_priv=creator_keys.sign_priv,
        creator_pub_b64=creator_keys.sign_pub_b64,
        currency=currency
    )
    return Chain(genesis)


class TestChainBasics:
    """Basic chain operations tests."""

    @pytest.fixture
    def creator_keys(self):
        """Generate keys for the chain creator."""
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        """Generate keys for a regular member."""
        return gen_node_keys()

    @pytest.fixture
    def chain(self, creator_keys):
        """Create a basic chain with one admin."""
        return make_chain(creator_keys)

    def test_genesis_creates_valid_chain(self, chain, creator_keys):
        """Test that genesis creates a valid chain."""
        assert chain.head.height == 0
        assert chain.state.group_id is not None
        assert creator_keys.sign_pub_b64 in chain.state.admins
        assert creator_keys.sign_pub_b64 in chain.state.members

    def test_append_valid_block(self, chain, creator_keys):
        """Test appending a valid block."""
        initial_height = chain.head.height

        # Create a mint transaction
        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )

        chain.append(block)
        assert chain.head.height == initial_height + 1
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 100

    def test_append_wrong_height_fails(self, chain, creator_keys):
        """Test that blocks with wrong height are rejected."""
        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 2,  # Wrong height
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="wrong height"):
            chain.append(block)

    def test_append_wrong_prev_fails(self, chain, creator_keys):
        """Test that blocks with wrong prev hash are rejected."""
        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            "wrongprevhash",  # Wrong prev
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="wrong prev"):
            chain.append(block)


class TestTransferTransaction:
    """Tests for the transfer transaction type."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def chain_with_balance(self, creator_keys, member_keys):
        """Create a chain with member having some balance."""
        chain = make_chain(creator_keys)

        # Add member
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        # Mint to member
        tx2 = {"type": "mint", "to": member_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx1, tx2]
        )
        chain.append(block)

        return chain, creator_keys, member_keys

    def test_transfer_success(self, chain_with_balance):
        """Test successful token transfer."""
        chain, creator_keys, member_keys = chain_with_balance

        initial_member_bal = chain.state.balances.get(member_keys.sign_pub_b64, 0)
        initial_creator_bal = chain.state.balances.get(creator_keys.sign_pub_b64, 0)

        tx = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 250,
            "ts_ms": int(time.time() * 1000)
        }
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=member_keys.sign_priv,
            author_pub_b64=member_keys.sign_pub_b64,
            txs=[tx]
        )
        chain.append(block)

        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == initial_member_bal - 250
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == initial_creator_bal + 250

    def test_transfer_insufficient_balance_fails(self, chain_with_balance):
        """Test that transfer with insufficient balance fails."""
        chain, creator_keys, member_keys = chain_with_balance

        tx = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 999999,  # More than balance
            "ts_ms": int(time.time() * 1000)
        }
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=member_keys.sign_priv,
            author_pub_b64=member_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="insufficient balance"):
            chain.append(block)

    def test_transfer_to_self_fails(self, chain_with_balance):
        """Test that transfer to self fails."""
        chain, creator_keys, member_keys = chain_with_balance

        tx = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": member_keys.sign_pub_b64,  # Same as from
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=member_keys.sign_priv,
            author_pub_b64=member_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="cannot transfer to self"):
            chain.append(block)

    def test_transfer_others_tokens_fails(self, chain_with_balance):
        """Test that you cannot transfer someone else's tokens."""
        chain, creator_keys, member_keys = chain_with_balance

        # Creator tries to transfer member's tokens
        tx = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,  # Member's address
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,  # Creator signing
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="can only transfer your own tokens"):
            chain.append(block)

    def test_transfer_non_member_fails(self):
        """Test that non-members cannot transfer."""
        creator_keys = gen_node_keys()
        non_member_keys = gen_node_keys()

        chain = make_chain(creator_keys)

        # Non-member tries to transfer (even though they have no tokens)
        tx = {
            "type": "transfer",
            "from": non_member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=non_member_keys.sign_priv,
            author_pub_b64=non_member_keys.sign_pub_b64,
            txs=[tx]
        )

        with pytest.raises(ChainError, match="block author not a member"):
            chain.append(block)


class TestBlockSizeValidation:
    """Tests for block size limits."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def chain(self, creator_keys):
        return make_chain(creator_keys)

    def test_block_with_many_txs_fails(self, chain, creator_keys):
        """Test that blocks with too many transactions are rejected."""
        # Create more transactions than allowed (default is 100)
        txs = [
            {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1, "ts_ms": int(time.time() * 1000)}
            for _ in range(150)  # More than default max of 100
        ]

        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=txs
        )

        with pytest.raises(ChainError, match="too many transactions"):
            chain.append(block)


class TestForkResolution:
    """Tests for fork resolution logic (snapshot/restore)."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    def test_snapshot_and_restore(self, creator_keys):
        """Test chain snapshot and restoration."""
        chain = make_chain(creator_keys)

        # Add some transactions
        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 500, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )
        chain.append(block)

        # Snapshot
        snapshot = chain.snapshot()

        # Restore
        restored = Chain.from_snapshot(snapshot)

        assert restored.head.height == chain.head.height
        assert restored.head.block_id == chain.head.block_id
        assert restored.state.balances == chain.state.balances
        assert restored.state.group_id == chain.state.group_id


class TestMemberManagement:
    """Tests for member add/remove transactions."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def chain(self, creator_keys):
        return make_chain(creator_keys)

    def test_add_member(self, chain, creator_keys, member_keys):
        """Test adding a new member."""
        tx = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )
        chain.append(block)

        assert member_keys.sign_pub_b64 in chain.state.members
        assert member_keys.sign_pub_b64 not in chain.state.admins

    def test_add_admin(self, chain, creator_keys, member_keys):
        """Test adding a new admin."""
        tx = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "admin", "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx]
        )
        chain.append(block)

        assert member_keys.sign_pub_b64 in chain.state.members
        assert member_keys.sign_pub_b64 in chain.state.admins

    def test_non_admin_cannot_add_member(self, chain, creator_keys, member_keys):
        """Test that non-admins cannot add members."""
        # First add member (non-admin)
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        block1 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx1]
        )
        chain.append(block1)

        # Try to add another member as non-admin
        another_keys = gen_node_keys()
        tx2 = {"type": "member_add", "pub": another_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        block2 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=member_keys.sign_priv,  # Member trying to add
            author_pub_b64=member_keys.sign_pub_b64,
            txs=[tx2]
        )

        with pytest.raises(ChainError, match="member_add requires admin"):
            chain.append(block2)

    def test_remove_member(self, chain, creator_keys, member_keys):
        """Test removing a member."""
        # Add member first
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        block1 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx1]
        )
        chain.append(block1)
        assert member_keys.sign_pub_b64 in chain.state.members

        # Remove member
        tx2 = {"type": "member_remove", "pub": member_keys.sign_pub_b64, "ts_ms": int(time.time() * 1000)}
        block2 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx2]
        )
        chain.append(block2)
        assert member_keys.sign_pub_b64 not in chain.state.members


class TestTimestampValidation:
    """Tests for timestamp validation."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def chain(self, creator_keys):
        return make_chain(creator_keys)

    def test_block_timestamp_in_future_fails(self, chain, creator_keys):
        """Test that blocks with timestamps too far in the future are rejected."""
        future_ts = int(time.time() * 1000) + (10 * 60 * 1000)  # 10 minutes in future

        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx],
            ts_ms=future_ts
        )

        with pytest.raises(ChainError, match="timestamp too far in future"):
            chain.append(block)

    def test_block_timestamp_before_prev_fails(self, chain, creator_keys):
        """Test that blocks with timestamps before previous block are rejected."""
        # Add first block
        tx1 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block1 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx1]
        )
        chain.append(block1)

        # Try to add block with earlier timestamp
        past_ts = chain.head.ts_ms - 1000  # 1 second before previous

        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        block2 = Block.make(
            chain.state.group_id,
            chain.head.height + 1,
            chain.head.block_id,
            author_priv=creator_keys.sign_priv,
            author_pub_b64=creator_keys.sign_pub_b64,
            txs=[tx2],
            ts_ms=past_ts
        )

        with pytest.raises(ChainError, match="timestamp must not be before"):
            chain.append(block2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
