"""
LBM Coordinator - Distributed Knowledge Sharing for Agents

This module provides the LBM integration layer for agent coordination.
Agents share knowledge through claims, query context before decisions,
and earn tokens for contributing valuable insights.

Architecture:
- Single coordinator node owns the knowledge chain
- Agents are registered as members with unique identities
- Claims are published by the coordinator on behalf of agents
- No fork resolution needed - single source of truth
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from lb.node import BatteryNode
from lb.keys import NodeKeys, gen_node_keys


@dataclass
class AgentIdentity:
    """Represents an agent's identity in the LBM network."""
    name: str
    role: str
    pub_key: str
    balance: int = 0


@dataclass
class KnowledgeClaim:
    """A piece of knowledge shared by an agent."""
    agent_name: str
    claim_type: str  # decision, code, review, insight, question, answer
    content: str
    tags: List[str]
    claim_hash: str
    timestamp: datetime = field(default_factory=datetime.now)


class LBMCoordinator:
    """
    Coordinates knowledge sharing between agents using LBM.

    Uses a single-node architecture for simplicity:
    - One coordinator node manages the knowledge chain
    - Agents are registered as members with their own keys
    - Claims are tagged with agent names for attribution
    - No multi-node sync or fork resolution needed

    Features:
    - Shared knowledge base across all agents
    - Token economy for incentivizing contributions
    - Context retrieval for informed decision making
    - Persistent learning across sessions
    """

    def __init__(
        self,
        data_dir: Path,
        project_name: str = "agentic-playground",
        *,
        faucet_amount: int = 100,
        claim_reward: int = 10,
        transfer_fee_bps: int = 100,  # 1%
    ):
        """
        Initialize the LBM coordinator.

        Args:
            data_dir: Directory for LBM data
            project_name: Name of the project/group
            faucet_amount: Tokens given to new agents
            claim_reward: Tokens earned per knowledge claim
            transfer_fee_bps: Transfer fee in basis points
        """
        self.data_dir = Path(data_dir)
        self.project_name = project_name
        self.faucet_amount = faucet_amount
        self.claim_reward = claim_reward
        self.transfer_fee_bps = transfer_fee_bps

        self._node: Optional[BatteryNode] = None
        self._group_id: Optional[str] = None
        self._agents: Dict[str, AgentIdentity] = {}
        self._agent_keys: Dict[str, NodeKeys] = {}  # For future per-agent signing

    @property
    def node(self) -> BatteryNode:
        """Get the coordinator's node, initializing if needed."""
        if self._node is None:
            self._initialize()
        return self._node

    @property
    def group_id(self) -> str:
        """Get the project group ID."""
        if self._group_id is None:
            self._initialize()
        return self._group_id

    def _initialize(self) -> None:
        """Initialize or load the LBM node and project group."""
        node_dir = self.data_dir / "coordinator"
        node_json = node_dir / "node.json"

        if node_json.exists():
            self._node = BatteryNode.load(node_dir)
            # Find existing group
            for gid, g in self._node.groups.items():
                if g.chain.state.policy.name == self.project_name:
                    self._group_id = gid
                    break
        else:
            self._node = BatteryNode.init(node_dir)

        # Create group if not exists
        if self._group_id is None:
            self._group_id = self._node.create_group(self.project_name)
            # Configure token economy
            self._node.update_group_policy(
                self._group_id,
                faucet_amount=self.faucet_amount,
                claim_reward_amount=self.claim_reward,
                transfer_fee_bps=self.transfer_fee_bps,
            )

    def register_agent(self, name: str, role: str) -> AgentIdentity:
        """
        Register a new agent in the coordination network.

        Args:
            name: Agent's unique name
            role: Agent's role (architect, developer, reviewer, etc.)

        Returns:
            AgentIdentity with the agent's credentials
        """
        if name in self._agents:
            return self._agents[name]

        # Generate a unique key for this agent
        agent_keys = gen_node_keys()
        pub_key = agent_keys.sign_pub_b64
        self._agent_keys[name] = agent_keys

        # Add agent as member (they'll receive faucet tokens)
        try:
            self.node.add_member(self.group_id, pub_key, role="member")
        except Exception:
            pass  # Already a member

        # Get balance from group state
        g = self.node.groups.get(self.group_id)
        balance = g.chain.state.balances.get(pub_key, 0) if g else 0

        identity = AgentIdentity(
            name=name,
            role=role,
            pub_key=pub_key,
            balance=balance,
        )
        self._agents[name] = identity
        return identity

    def share_knowledge(
        self,
        agent_name: str,
        content: str,
        claim_type: str = "insight",
        tags: Optional[List[str]] = None,
    ) -> KnowledgeClaim:
        """
        Share knowledge from an agent to the network.

        Args:
            agent_name: Name of the agent sharing
            content: The knowledge content
            claim_type: Type of claim (decision, code, review, insight, etc.)
            tags: Tags for categorization

        Returns:
            KnowledgeClaim with the claim details
        """
        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent: {agent_name}")

        agent = self._agents[agent_name]

        # Format content with agent metadata
        full_content = f"[{agent_name}:{claim_type}] {content}"
        all_tags = [agent.role, claim_type, f"author:{agent_name}"] + (tags or [])

        # Publish claim from coordinator (single node, no forks)
        claim_hash = self.node.publish_claim(
            self.group_id,
            text=full_content,
            tags=all_tags,
        )

        claim = KnowledgeClaim(
            agent_name=agent_name,
            claim_type=claim_type,
            content=content,
            tags=all_tags,
            claim_hash=claim_hash,
        )

        return claim

    def query_knowledge(
        self,
        agent_name: str,
        query: str,
        top_k: int = 8,
    ) -> Tuple[str, List[str]]:
        """
        Query the knowledge base for relevant context.

        Args:
            agent_name: Name of the querying agent
            query: Search query
            top_k: Number of results

        Returns:
            Tuple of (compiled_context, claim_hashes)
        """
        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent: {agent_name}")

        # Query from coordinator node (single source of truth)
        return self.node.compile_context(self.group_id, query, top_k=top_k)

    def get_agent_balance(self, agent_name: str) -> int:
        """Get an agent's token balance."""
        if agent_name not in self._agents:
            return 0

        pub_key = self._agents[agent_name].pub_key
        g = self.node.groups.get(self.group_id)
        return g.chain.state.balances.get(pub_key, 0) if g else 0

    def transfer_tokens(
        self,
        from_agent: str,
        to_agent: str,
        amount: int,
    ) -> bool:
        """
        Transfer tokens between agents.

        Args:
            from_agent: Sending agent
            to_agent: Receiving agent
            amount: Amount to transfer

        Returns:
            True if successful
        """
        if from_agent not in self._agents:
            raise ValueError(f"Unknown agent: {from_agent}")
        if to_agent not in self._agents:
            raise ValueError(f"Unknown agent: {to_agent}")

        to_pub = self._agents[to_agent].pub_key

        # Note: In this simplified architecture, transfers are done by coordinator
        # A more complete implementation would require agent-signed transactions
        self.node.transfer(self.group_id, to_pub, amount)
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get coordination statistics."""
        g = self.node.groups.get(self.group_id)
        if not g:
            return {}

        state = g.chain.state
        stats = self.node.get_token_stats(self.group_id)

        # Count claims
        claim_count = sum(
            1 for block in g.chain.blocks
            for tx in block.txs
            if tx.get("type") == "claim"
        )

        return {
            "project_name": self.project_name,
            "group_id": self.group_id,
            "chain_height": g.chain.head.height,
            "total_supply": stats["total_supply"],
            "treasury_balance": stats["treasury_balance"],
            "claim_count": claim_count,
            "agent_count": len(self._agents),
            "agents": {
                name: {
                    "role": agent.role,
                    "balance": self.get_agent_balance(name),
                }
                for name, agent in self._agents.items()
            },
            "policy": {
                "faucet_amount": state.policy.faucet_amount,
                "claim_reward": state.policy.claim_reward_amount,
                "transfer_fee_bps": state.policy.transfer_fee_bps,
            },
        }

    def get_all_claims(self) -> List[Dict[str, Any]]:
        """Get all knowledge claims in the network."""
        g = self.node.groups.get(self.group_id)
        if not g:
            return []

        claims = []
        for block in g.chain.blocks:
            for tx in block.txs:
                if tx.get("type") == "claim":
                    try:
                        artifact = self.node.cas.get_json(tx["artifact_hash"])
                        claims.append({
                            "hash": tx["artifact_hash"],
                            "text": artifact.get("text", ""),
                            "tags": artifact.get("tags", []),
                            "block_height": block.height,
                            "author": block.author[:12] + "...",
                            "timestamp_ms": block.ts_ms,
                        })
                    except Exception:
                        pass
        return claims

    def save_state(self) -> None:
        """Persist all state to disk."""
        # State is automatically persisted by LBM nodes
        pass

    def export_learnings(self, output_file: Path) -> None:
        """
        Export all learnings to a JSON file for backup/analysis.

        Args:
            output_file: Path to output JSON file
        """
        data = {
            "exported_at": datetime.now().isoformat(),
            "stats": self.get_stats(),
            "claims": self.get_all_claims(),
        }
        output_file.write_text(json.dumps(data, indent=2, default=str))

    def import_learnings(self, input_file: Path) -> int:
        """
        Import learnings from a backup file.

        Args:
            input_file: Path to JSON file

        Returns:
            Number of claims imported
        """
        data = json.loads(input_file.read_text())
        count = 0
        for claim in data.get("claims", []):
            # Re-publish claims (they'll be deduplicated by hash)
            try:
                self.node.publish_claim(
                    self.group_id,
                    text=claim["text"],
                    tags=claim["tags"],
                )
                count += 1
            except Exception:
                pass
        return count
