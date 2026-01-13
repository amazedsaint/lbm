from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple


def dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def matvec(M: List[List[float]], v: List[float]) -> List[float]:
    return [dot(row, v) for row in M]


def matmul(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    # A (m x n) times B (n x p)
    m, n, p = len(A), len(A[0]), len(B[0])
    out = [[0.0] * p for _ in range(m)]
    for i in range(m):
        for k in range(n):
            aik = A[i][k]
            for j in range(p):
                out[i][j] += aik * B[k][j]
    return out


def transpose(M: List[List[float]]) -> List[List[float]]:
    return [list(col) for col in zip(*M)]


def norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def normalize(v: List[float]) -> List[float]:
    n = norm(v)
    if n == 0:
        return list(v)
    return [x / n for x in v]


def random_orthogonal(d: int, *, seed: int = 0) -> List[List[float]]:
    """Construct a deterministic (seeded) orthogonal-ish matrix using Gram-Schmidt."""
    rng = random.Random(seed)
    cols: List[List[float]] = []
    for j in range(d):
        v = [rng.uniform(-1, 1) for _ in range(d)]
        # subtract projections
        for c in cols:
            proj = dot(v, c)
            v = [vi - proj * ci for vi, ci in zip(v, c)]
        v = normalize(v)
        cols.append(v)
    # return as matrix with cols -> rows
    return transpose(cols)


@dataclass
class Chart:
    name: str
    R: List[List[float]]  # orthogonal transform to local coords

    def to_local(self, v_global: List[float]) -> List[float]:
        return matvec(self.R, v_global)

    def to_global(self, v_local: List[float]) -> List[float]:
        return matvec(transpose(self.R), v_local)


def masked_update(v_local: List[float], *, lr: float, k: int) -> List[float]:
    """Coordinate-dependent update: only first k dims get nudged."""
    out = list(v_local)
    for i in range(min(k, len(out))):
        out[i] += lr
    return out


def holonomy_loop(v0: List[float], *, chart_a: Chart, chart_b: Chart, lr: float = 0.1, k: int = 4) -> Tuple[List[float], float]:
    """Apply an A->B->A loop of masked updates and return (v_final, defect_norm)."""
    # A update
    va = chart_a.to_local(v0)
    va2 = masked_update(va, lr=lr, k=k)
    v1 = chart_a.to_global(va2)

    # B update
    vb = chart_b.to_local(v1)
    vb2 = masked_update(vb, lr=lr, k=k)
    v2 = chart_b.to_global(vb2)

    # Back to A frame without update
    # compare to doing both updates in a single chart (path dependence)
    va_direct = chart_a.to_local(v0)
    va_direct2 = masked_update(masked_update(va_direct, lr=lr, k=k), lr=lr, k=k)
    v_direct = chart_a.to_global(va_direct2)

    defect = [x - y for x, y in zip(v2, v_direct)]
    return v2, norm(defect)
