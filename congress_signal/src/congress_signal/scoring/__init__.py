"""Scoring layers fed into the asymmetric filter.

Each layer takes raw `Trade` / `Actor` objects (plus prices when needed) and
emits one of the typed score objects defined in `..schema`.
"""

from .actor import score_actors
from .cluster import find_clusters
from .residual import compute_residuals
from .signal import score_trades

__all__ = [
    "score_actors",
    "score_trades",
    "find_clusters",
    "compute_residuals",
]
