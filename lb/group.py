from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from .chain import Chain
from .context_graph import ContextGraph
from .fs import ensure_dir, atomic_write_json, read_json

if TYPE_CHECKING:
    from .wal import Transaction


@dataclass
class Group:
    group_id: str
    root: Path
    chain: Chain
    graph: ContextGraph

    @property
    def chain_path(self) -> Path:
        return self.root / "chain.json"

    @property
    def graph_path(self) -> Path:
        return self.root / "graph.json"

    def save(self, wal_tx: Optional["Transaction"] = None) -> None:
        """Save group state (chain + graph).

        Args:
            wal_tx: Optional WAL transaction for atomic multi-file writes.
                   If provided, writes are staged in the transaction.
                   If None, writes are done directly (less durable).
        """
        ensure_dir(self.root)
        if wal_tx is not None:
            wal_tx.write_json(self.chain_path, self.chain.snapshot())
            wal_tx.write_json(self.graph_path, self.graph.snapshot())
        else:
            atomic_write_json(self.chain_path, self.chain.snapshot())
            atomic_write_json(self.graph_path, self.graph.snapshot())

    @staticmethod
    def load(root: Path) -> "Group":
        root = Path(root)
        snap = read_json(root / "chain.json")
        chain = Chain.from_snapshot(snap)
        if (root / "graph.json").exists():
            g = ContextGraph.from_snapshot(read_json(root / "graph.json"))
        else:
            g = ContextGraph()
        return Group(group_id=chain.state.group_id, root=root, chain=chain, graph=g)
