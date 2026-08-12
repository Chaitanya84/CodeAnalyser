"""Interactive 3D visualization of the code graph.

Loads code_graph.json, builds a NetworkX directed graph, computes a
deterministic 3D force-directed layout, and renders an interactive
dark-themed Plotly HTML page (rotate / zoom / pan / hover / legend
selection).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

import networkx as nx
import plotly.graph_objects as go

log = logging.getLogger(__name__)

LAYOUT_SEED = 42

NODE_COLORS = {
    "function": "#4fc3f7",   # cyan
    "class": "#ffb74d",      # orange
    "variable": "#81c784",   # green
}
NODE_SIZES = {"function": 5, "class": 8, "variable": 4}

EDGE_STYLES = {
    "calls": {"color": "rgba(140, 158, 175, 0.45)", "width": 1.5},
    "inherits": {"color": "rgba(239, 83, 80, 0.85)", "width": 3.0},
    "defines": {"color": "rgba(149, 117, 205, 0.55)", "width": 2.0},
}

BACKGROUND = "#0d1117"


def load_graph(json_path: Path) -> nx.DiGraph:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    graph = nx.DiGraph()
    for node in data.get("nodes", []):
        graph.add_node(node["id"], **node)
    for link in data.get("links", []):
        graph.add_edge(link["source"], link["target"], type=link["type"])
    log.info(
        "visualizer loaded %d nodes and %d edges",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    return graph


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font=dict(size=20, color="#c9d1d9"),
    )
    fig.update_layout(
        paper_bgcolor=BACKGROUND, plot_bgcolor=BACKGROUND,
        title=dict(text="Code Graph", font=dict(color="#c9d1d9")),
    )
    return fig


def _edge_trace(graph: nx.DiGraph, pos: Dict[str, List[float]], edge_type: str) -> go.Scatter3d:
    xs: List = []
    ys: List = []
    zs: List = []
    for source, target, data in graph.edges(data=True):
        if data.get("type") != edge_type:
            continue
        if source not in pos or target not in pos:
            continue
        x0, y0, z0 = pos[source]
        x1, y1, z1 = pos[target]
        xs += [x0, x1, None]
        ys += [y0, y1, None]
        zs += [z0, z1, None]
    style = EDGE_STYLES[edge_type]
    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        name=f"{edge_type} (edges)",
        line=dict(color=style["color"], width=style["width"]),
        hoverinfo="skip",
        legendgroup=edge_type,
    )


def _node_trace(graph: nx.DiGraph, pos: Dict[str, List[float]], node_type: str) -> go.Scatter3d:
    xs, ys, zs, texts, custom = [], [], [], [], []
    for node_id, data in graph.nodes(data=True):
        if data.get("type") != node_type or node_id not in pos:
            continue
        x, y, z = pos[node_id]
        xs.append(x)
        ys.append(y)
        zs.append(z)
        kind = data.get("kind") or node_type
        texts.append(
            f"<b>{data.get('qualified_name', data.get('name', node_id))}</b>"
            f"<br>Type: {node_type} ({kind})"
            f"<br>File: {data.get('file', '?')}"
            f"<br>Line: {data.get('line', '?')}"
        )
        custom.append(node_id)
    label = {"function": "functions", "class": "classes", "variable": "variables"}.get(
        node_type, node_type + "s"
    )
    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="markers",
        name=label,
        marker=dict(
            size=NODE_SIZES.get(node_type, 5),
            color=NODE_COLORS.get(node_type, "#ffffff"),
            opacity=0.9,
            line=dict(width=0.5, color="#0d1117"),
        ),
        text=texts,
        hoverinfo="text",
        customdata=custom,
        legendgroup=node_type,
    )


def build_figure(graph: nx.DiGraph) -> go.Figure:
    if graph.number_of_nodes() == 0:
        return _empty_figure("No graph entities were found in the analyzed source tree.")

    # nx.spring_layout requires scipy (sparse eigen-solver for initial
    # placement); scipy is declared in requirements.txt.
    pos = nx.spring_layout(graph, dim=3, seed=LAYOUT_SEED)

    traces: List[go.Scatter3d] = []
    for edge_type in ("calls", "inherits", "defines"):
        traces.append(_edge_trace(graph, pos, edge_type))
    for node_type in ("function", "class", "variable"):
        traces.append(_node_trace(graph, pos, node_type))

    axis = dict(
        showbackground=False, showticklabels=False, showgrid=False,
        zeroline=False, title="", showspikes=False,
    )
    layout = go.Layout(
        title=dict(
            text=(
                f"Code Graph — {graph.number_of_nodes()} nodes, "
                f"{graph.number_of_edges()} edges"
            ),
            font=dict(color="#c9d1d9", size=18),
        ),
        paper_bgcolor=BACKGROUND,
        plot_bgcolor=BACKGROUND,
        scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, bgcolor=BACKGROUND),
        legend=dict(
            font=dict(color="#c9d1d9"),
            bgcolor="rgba(22, 27, 34, 0.8)",
            bordercolor="#30363d",
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        hoverlabel=dict(bgcolor="#161b22", font=dict(color="#c9d1d9")),
    )
    return go.Figure(data=traces, layout=layout)


def render(json_path: Path, html_path: Path) -> None:
    graph = load_graph(json_path)
    figure = build_figure(graph)
    html_path = Path(html_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(html_path), include_plotlyjs=True)
    log.info("wrote %s", html_path)
