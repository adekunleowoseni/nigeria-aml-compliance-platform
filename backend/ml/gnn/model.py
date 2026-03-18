from __future__ import annotations

from typing import Any, Tuple

import torch
import torch.nn as nn

try:
    from torch_geometric.nn import MessagePassing, global_mean_pool  # type: ignore
except Exception:  # pragma: no cover
    MessagePassing = object  # type: ignore
    global_mean_pool = None  # type: ignore


class DirectionalMPNN(MessagePassing):  # type: ignore[misc]
    """Minimal placeholder for a directed multigraph message passing layer."""

    def __init__(self, in_channels: int, out_channels: int, edge_dim: int):
        super().__init__(aggr="add")  # type: ignore[arg-type]
        self.lin_node = nn.Linear(in_channels, out_channels)
        self.lin_edge = nn.Linear(edge_dim, out_channels)

    def forward(self, x, edge_index, edge_attr):  # type: ignore[override]
        # If torch_geometric isn't installed, raise a clear error.
        if not hasattr(self, "propagate"):
            raise RuntimeError("torch_geometric is required for GNN components")
        return self.propagate(edge_index=edge_index, x=x, edge_attr=edge_attr)

    def message(self, x_j, edge_attr):  # type: ignore[override]
        return self.lin_node(x_j) + self.lin_edge(edge_attr)


class TemporalGNN(nn.Module):
    """Small GNN scaffold with temporal embedding hooks."""

    def __init__(
        self,
        node_dim: int = 64,
        edge_dim: int = 16,
        hidden_dim: int = 128,
        num_layers: int = 3,
        num_heads: int = 4,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.layers = nn.ModuleList(
            [DirectionalMPNN(node_dim if i == 0 else hidden_dim, hidden_dim, edge_dim) for i in range(num_layers)]
        )
        self.classifier = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.ReLU(), nn.Linear(hidden_dim, 1))

    def forward(self, x, edge_index, edge_attr, edge_time=None, batch=None) -> Tuple[torch.Tensor, Any]:
        h = x
        for layer in self.layers:
            h = layer(h, edge_index, edge_attr)
            h = torch.relu(h)
            h = self.dropout(h)
        if batch is not None and global_mean_pool is not None:
            h = global_mean_pool(h, batch)
        logits = self.classifier(h).squeeze(-1)
        attention_weights = None
        return logits, attention_weights

    def save(self, path: str) -> None:
        torch.save(self.state_dict(), path)

    def load(self, path: str, map_location: str | None = None) -> None:
        state = torch.load(path, map_location=map_location)
        self.load_state_dict(state, strict=True)

