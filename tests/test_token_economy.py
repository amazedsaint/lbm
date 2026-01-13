"""Tests for token economy features.

Tests the following features:
- Member faucet (auto-mint to new members)
- Claim rewards (earn tokens per claim)
- Transfer fees (percentage fee to treasury)
- Supply caps (max total supply and per-account limits)
- Policy updates (admin-only configuration)
"""
import time
import pytest

from lb.chain import Chain, Block, ChainError, TREASURY, MAX_TOKEN_VALUE
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


def append_block(chain, keys, txs):
    """Helper to append a block with transactions."""
    block = Block.make(
        chain.state.group_id,
        chain.head.height + 1,
        chain.head.block_id,
        author_priv=keys.sign_priv,
        author_pub_b64=keys.sign_pub_b64,
        txs=txs
    )
    chain.append(block)
    return block


class TestPolicyUpdate:
    """Tests for policy_update transaction type."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def chain(self, creator_keys):
        return make_chain(creator_keys)

    def test_admin_can_update_policy(self, chain, creator_keys):
        """Test that admin can update policy fields."""
        tx = {
            "type": "policy_update",
            "updates": {
                "faucet_amount": 100,
                "claim_reward_amount": 10,
                "transfer_fee_bps": 250,
            },
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx])

        assert chain.state.policy.faucet_amount == 100
        assert chain.state.policy.claim_reward_amount == 10
        assert chain.state.policy.transfer_fee_bps == 250

    def test_non_admin_cannot_update_policy(self, chain, creator_keys, member_keys):
        """Test that non-admin cannot update policy."""
        # Add member first
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1])

        # Try to update policy as non-admin
        tx2 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="policy_update requires admin"):
            append_block(chain, member_keys, [tx2])

    def test_invalid_faucet_amount_fails(self, chain, creator_keys):
        """Test that negative faucet amount fails."""
        tx = {
            "type": "policy_update",
            "updates": {"faucet_amount": -10},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="invalid faucet_amount"):
            append_block(chain, creator_keys, [tx])

    def test_invalid_transfer_fee_fails(self, chain, creator_keys):
        """Test that fee > 5000 bps fails."""
        tx = {
            "type": "policy_update",
            "updates": {"transfer_fee_bps": 6000},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="transfer_fee_bps must be 0-5000"):
            append_block(chain, creator_keys, [tx])

    def test_supply_cap_update(self, chain, creator_keys):
        """Test updating supply caps."""
        tx = {
            "type": "policy_update",
            "updates": {
                "max_total_supply": 1000000,
                "max_account_balance": 10000,
            },
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx])

        assert chain.state.policy.max_total_supply == 1000000
        assert chain.state.policy.max_account_balance == 10000

    def test_supply_cap_cannot_be_lowered_below_current(self, chain, creator_keys):
        """Test that supply cap cannot be set below current supply."""
        # Mint some tokens first
        tx1 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 5000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1])

        # Try to set supply cap below current supply
        tx2 = {
            "type": "policy_update",
            "updates": {"max_total_supply": 1000},  # Less than 5000
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="max_total_supply cannot be below current supply"):
            append_block(chain, creator_keys, [tx2])


class TestMemberFaucet:
    """Tests for member faucet (auto-mint to new members)."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    def test_new_member_receives_faucet(self, creator_keys, member_keys):
        """Test that new members receive faucet amount."""
        chain = make_chain(creator_keys)

        # Enable faucet
        tx1 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Add member
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Member should have faucet balance
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 100
        assert chain.state.total_supply == 100

    def test_faucet_zero_means_no_mint(self, creator_keys, member_keys):
        """Test that faucet=0 means no auto-mint."""
        chain = make_chain(creator_keys)

        # Add member without faucet
        tx = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx])

        # Member should have zero balance
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0

    def test_faucet_respects_supply_cap(self, creator_keys, member_keys):
        """Test that faucet respects supply cap."""
        chain = make_chain(creator_keys)

        # Set faucet and low supply cap
        tx1 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100, "max_total_supply": 50},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Add member - faucet should be skipped due to cap
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Member should have zero balance (faucet would exceed cap)
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0


class TestClaimRewards:
    """Tests for claim rewards (earn tokens per claim)."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    def test_claim_earns_reward(self, creator_keys):
        """Test that publishing a claim earns reward."""
        chain = make_chain(creator_keys)

        # Enable claim rewards
        tx1 = {
            "type": "policy_update",
            "updates": {"claim_reward_amount": 10},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        initial_balance = chain.state.balances.get(creator_keys.sign_pub_b64, 0)

        # Publish claim
        tx2 = {"type": "claim", "artifact_hash": "abc123", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Creator should have earned reward
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == initial_balance + 10
        assert chain.state.total_supply == 10

    def test_claim_reward_zero_means_no_reward(self, creator_keys):
        """Test that claim_reward_amount=0 means no reward."""
        chain = make_chain(creator_keys)

        # Publish claim without rewards enabled
        tx = {"type": "claim", "artifact_hash": "abc123", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx])

        # No balance change
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0

    def test_claim_reward_respects_supply_cap(self, creator_keys):
        """Test that claim rewards respect supply cap."""
        chain = make_chain(creator_keys)

        # Enable rewards with low supply cap
        tx1 = {
            "type": "policy_update",
            "updates": {"claim_reward_amount": 100, "max_total_supply": 50},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Publish claim - reward should be skipped
        tx2 = {"type": "claim", "artifact_hash": "abc123", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # No balance change (reward would exceed cap)
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0


class TestTransferFees:
    """Tests for transfer fees."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    def test_transfer_fee_goes_to_treasury(self, creator_keys, member_keys):
        """Test that transfer fee goes to treasury."""
        chain = make_chain(creator_keys)

        # Add member and give them tokens
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        tx2 = {"type": "mint", "to": member_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1, tx2])

        # Enable 10% transfer fee
        tx3 = {
            "type": "policy_update",
            "updates": {"transfer_fee_bps": 1000},  # 10%
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx3])

        initial_treasury = chain.state.balances.get(TREASURY, 0)

        # Transfer 100 tokens
        tx4 = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, member_keys, [tx4])

        # Member lost 110 (100 + 10 fee)
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 1000 - 110
        # Creator got 100
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 100
        # Treasury got 10
        assert chain.state.balances.get(TREASURY, 0) == initial_treasury + 10

    def test_transfer_zero_fee(self, creator_keys, member_keys):
        """Test transfer with zero fee."""
        chain = make_chain(creator_keys)

        # Add member and give them tokens
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        tx2 = {"type": "mint", "to": member_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1, tx2])

        initial_treasury = chain.state.balances.get(TREASURY, 0)

        # Transfer without fee
        tx3 = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, member_keys, [tx3])

        # Member lost exactly 100
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 900
        # Creator got 100
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 100
        # Treasury unchanged
        assert chain.state.balances.get(TREASURY, 0) == initial_treasury

    def test_transfer_insufficient_balance_with_fee(self, creator_keys, member_keys):
        """Test that sender needs balance for amount + fee."""
        chain = make_chain(creator_keys)

        # Add member and give them exactly 100 tokens
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        tx2 = {"type": "mint", "to": member_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1, tx2])

        # Enable 10% fee
        tx3 = {
            "type": "policy_update",
            "updates": {"transfer_fee_bps": 1000},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx3])

        # Try to transfer 100 (would need 110 with fee)
        tx4 = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="insufficient balance"):
            append_block(chain, member_keys, [tx4])


class TestSupplyCaps:
    """Tests for supply caps."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    def test_mint_blocked_at_supply_cap(self, creator_keys):
        """Test that minting is blocked when at supply cap."""
        chain = make_chain(creator_keys)

        # Set supply cap
        tx1 = {
            "type": "policy_update",
            "updates": {"max_total_supply": 500},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Mint up to cap
        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 500, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Try to mint more
        tx3 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1, "ts_ms": int(time.time() * 1000)}
        with pytest.raises(ChainError, match="max_total_supply"):
            append_block(chain, creator_keys, [tx3])

    def test_account_balance_cap(self, creator_keys):
        """Test that minting respects account balance cap."""
        chain = make_chain(creator_keys)

        # Set account cap
        tx1 = {
            "type": "policy_update",
            "updates": {"max_account_balance": 100},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Mint up to account cap
        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Try to mint more to same account
        tx3 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1, "ts_ms": int(time.time() * 1000)}
        with pytest.raises(ChainError, match="max_account_balance"):
            append_block(chain, creator_keys, [tx3])

    def test_transfer_respects_recipient_account_cap(self, creator_keys, member_keys):
        """Test that transfers respect recipient account cap."""
        chain = make_chain(creator_keys)

        # Add member
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        # Give creator tokens
        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        # Set account cap
        tx3 = {
            "type": "policy_update",
            "updates": {"max_account_balance": 50},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1, tx2, tx3])

        # Try to transfer more than recipient can hold
        tx4 = {
            "type": "transfer",
            "from": creator_keys.sign_pub_b64,
            "to": member_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="max_account_balance"):
            append_block(chain, creator_keys, [tx4])

    def test_supply_tracking(self, creator_keys):
        """Test that total_supply is correctly tracked."""
        chain = make_chain(creator_keys)

        assert chain.state.total_supply == 0

        # Mint 100
        tx1 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 100, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1])
        assert chain.state.total_supply == 100

        # Mint 200 more
        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 200, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])
        assert chain.state.total_supply == 300


class TestSnapshotRestoreWithTokenEconomy:
    """Test that snapshots preserve token economy state."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    def test_snapshot_preserves_policy(self, creator_keys):
        """Test that snapshot preserves policy fields."""
        chain = make_chain(creator_keys)

        # Set policy
        tx1 = {
            "type": "policy_update",
            "updates": {
                "faucet_amount": 50,
                "claim_reward_amount": 5,
                "transfer_fee_bps": 100,
                "max_total_supply": 1000000,
                "max_account_balance": 10000,
            },
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Mint some tokens
        tx2 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 500, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Snapshot and restore
        snapshot = chain.snapshot()
        restored = Chain.from_snapshot(snapshot)

        # Check policy preserved
        assert restored.state.policy.faucet_amount == 50
        assert restored.state.policy.claim_reward_amount == 5
        assert restored.state.policy.transfer_fee_bps == 100
        assert restored.state.policy.max_total_supply == 1000000
        assert restored.state.policy.max_account_balance == 10000

        # Check total_supply preserved
        assert restored.state.total_supply == 500


class TestSecurityBounds:
    """Test security bounds and overflow protection."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    def test_mint_amount_bound(self, creator_keys):
        """Test that mint amount is bounded."""
        chain = make_chain(creator_keys)

        tx = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": MAX_TOKEN_VALUE + 1, "ts_ms": int(time.time() * 1000)}
        with pytest.raises(ChainError, match="too large"):
            append_block(chain, creator_keys, [tx])

    def test_faucet_amount_bound(self, creator_keys):
        """Test that faucet amount is bounded."""
        chain = make_chain(creator_keys)

        tx = {
            "type": "policy_update",
            "updates": {"faucet_amount": MAX_TOKEN_VALUE + 1},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="too large"):
            append_block(chain, creator_keys, [tx])

    def test_transfer_amount_bound(self, creator_keys):
        """Test that transfer amount is bounded."""
        chain = make_chain(creator_keys)

        # Give creator a lot of tokens
        tx1 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": MAX_TOKEN_VALUE, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1])

        member_keys = gen_node_keys()
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Try to transfer more than MAX_TOKEN_VALUE
        tx3 = {
            "type": "transfer",
            "from": creator_keys.sign_pub_b64,
            "to": member_keys.sign_pub_b64,
            "amount": MAX_TOKEN_VALUE + 1,
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="too large"):
            append_block(chain, creator_keys, [tx3])


class TestEdgeCases:
    """Edge case tests for token economy."""

    @pytest.fixture
    def creator_keys(self):
        return gen_node_keys()

    @pytest.fixture
    def member_keys(self):
        return gen_node_keys()

    def test_duplicate_add_no_faucet(self, creator_keys, member_keys):
        """Test that adding an already-existing member does not give faucet again."""
        chain = make_chain(creator_keys)

        # Enable faucet
        tx1 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Add member - gets faucet
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 100
        assert chain.state.total_supply == 100

        # Add same member again (duplicate) - should NOT get faucet again
        tx3 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx3])
        # Balance unchanged (no double faucet)
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 100
        assert chain.state.total_supply == 100

    def test_readd_removed_member_gets_faucet(self, creator_keys, member_keys):
        """Test that re-adding a removed member gives them faucet again (welcome back)."""
        chain = make_chain(creator_keys)

        # Enable faucet
        tx1 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Add member - gets faucet
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 100
        assert chain.state.total_supply == 100

        # Remove member
        tx3 = {"type": "member_remove", "pub": member_keys.sign_pub_b64, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx3])

        # Re-add member - SHOULD get faucet again (returning member welcome bonus)
        tx4 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx4])
        # Member gets faucet again
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 200
        assert chain.state.total_supply == 200

    def test_multiple_claims_multiple_rewards(self, creator_keys):
        """Test that multiple claims in one block each get rewards."""
        chain = make_chain(creator_keys)

        # Enable claim rewards
        tx1 = {
            "type": "policy_update",
            "updates": {"claim_reward_amount": 10},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Submit multiple claims in one block
        tx2 = {"type": "claim", "artifact_hash": "claim1", "ts_ms": int(time.time() * 1000)}
        tx3 = {"type": "claim", "artifact_hash": "claim2", "ts_ms": int(time.time() * 1000)}
        tx4 = {"type": "claim", "artifact_hash": "claim3", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2, tx3, tx4])

        # Should get 3 * 10 = 30 tokens
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 30
        assert chain.state.total_supply == 30

    def test_empty_policy_update_fails(self, creator_keys):
        """Test that empty policy_update fails."""
        chain = make_chain(creator_keys)

        tx = {
            "type": "policy_update",
            "updates": {},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="no updates"):
            append_block(chain, creator_keys, [tx])

    def test_policy_update_unknown_key_fails(self, creator_keys):
        """Test that policy_update with unknown key fails."""
        chain = make_chain(creator_keys)

        tx = {
            "type": "policy_update",
            "updates": {"unknown_field": 123},
            "ts_ms": int(time.time() * 1000)
        }
        with pytest.raises(ChainError, match="unknown keys"):
            append_block(chain, creator_keys, [tx])

    def test_claim_reward_respects_account_cap(self, creator_keys):
        """Test that claim rewards respect account cap."""
        chain = make_chain(creator_keys)

        # Enable rewards and set account cap
        tx1 = {
            "type": "policy_update",
            "updates": {"claim_reward_amount": 100, "max_account_balance": 50},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Publish claim - reward would exceed account cap
        tx2 = {"type": "claim", "artifact_hash": "abc123", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # No balance change (reward would exceed cap)
        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0

    def test_faucet_respects_account_cap(self, creator_keys, member_keys):
        """Test that faucet respects account cap."""
        chain = make_chain(creator_keys)

        # Set faucet and account cap where faucet > cap
        tx1 = {
            "type": "policy_update",
            "updates": {"faucet_amount": 100, "max_account_balance": 50},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])

        # Add member - faucet should be skipped due to account cap
        tx2 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx2])

        # Member should have zero balance (faucet would exceed account cap)
        assert chain.state.balances.get(member_keys.sign_pub_b64, 0) == 0
        assert chain.state.total_supply == 0

    def test_transfer_to_treasury_allowed(self, creator_keys):
        """Test that transfer to treasury is allowed."""
        chain = make_chain(creator_keys)

        # Give creator some tokens
        tx1 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1])

        initial_treasury = chain.state.balances.get(TREASURY, 0)

        # Transfer to treasury
        tx2 = {
            "type": "transfer",
            "from": creator_keys.sign_pub_b64,
            "to": TREASURY,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx2])

        assert chain.state.balances.get(creator_keys.sign_pub_b64, 0) == 900
        assert chain.state.balances.get(TREASURY, 0) == initial_treasury + 100

    def test_fee_calculation_rounding(self, creator_keys, member_keys):
        """Test fee calculation with various amounts and fee rates."""
        chain = make_chain(creator_keys)

        # Add member and give tokens
        tx1 = {"type": "member_add", "pub": member_keys.sign_pub_b64, "role": "member", "ts_ms": int(time.time() * 1000)}
        tx2 = {"type": "mint", "to": member_keys.sign_pub_b64, "amount": 1000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx1, tx2])

        # Set 1% fee (100 bps)
        tx3 = {
            "type": "policy_update",
            "updates": {"transfer_fee_bps": 100},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx3])

        initial_treasury = chain.state.balances.get(TREASURY, 0)

        # Transfer 99 - fee should be 0 (99 * 100 / 10000 = 0.99 -> 0)
        tx4 = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 99,
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, member_keys, [tx4])

        # Fee is 0 due to integer division
        assert chain.state.balances.get(TREASURY, 0) == initial_treasury

        # Transfer 100 - fee should be 1 (100 * 100 / 10000 = 1)
        tx5 = {
            "type": "transfer",
            "from": member_keys.sign_pub_b64,
            "to": creator_keys.sign_pub_b64,
            "amount": 100,
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, member_keys, [tx5])

        assert chain.state.balances.get(TREASURY, 0) == initial_treasury + 1

    def test_supply_cap_can_be_removed(self, creator_keys):
        """Test that supply cap can be set to None (removed)."""
        chain = make_chain(creator_keys)

        # Set supply cap
        tx1 = {
            "type": "policy_update",
            "updates": {"max_total_supply": 1000},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx1])
        assert chain.state.policy.max_total_supply == 1000

        # Remove supply cap
        tx2 = {
            "type": "policy_update",
            "updates": {"max_total_supply": None},
            "ts_ms": int(time.time() * 1000)
        }
        append_block(chain, creator_keys, [tx2])
        assert chain.state.policy.max_total_supply is None

        # Now can mint unlimited
        tx3 = {"type": "mint", "to": creator_keys.sign_pub_b64, "amount": 1000000, "ts_ms": int(time.time() * 1000)}
        append_block(chain, creator_keys, [tx3])
        assert chain.state.total_supply == 1000000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
