from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .chain import Chain
from .context_graph import ContextGraph
from .fs import ensure_dir, atomic_write_json, read_json


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

    def save(self) -> None:
        ensure_dir(self.root)
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
