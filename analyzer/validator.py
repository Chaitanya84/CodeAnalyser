"""Graph validation.

Verifies structural integrity of nodes and links before serialization:
mandatory node fields, link endpoint existence, allowed relationship
types, and exact-duplicate link removal. Recursive-call self-edges are
explicitly preserved.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from .models import CodeLink, CodeNode

log = logging.getLogger(__name__)

ALLOWED_NODE_TYPES = {"function", "class", "variable"}
ALLOWED_LINK_TYPES = {"calls", "inherits", "defines"}


def validate_graph(
    nodes: List[CodeNode], links: List[CodeLink]
) -> Tuple[List[CodeNode], List[CodeLink], List[str]]:
    issues: List[str] = []

    # ---- nodes ---------------------------------------------------------
    valid_nodes: List[CodeNode] = []
    seen_ids = set()
    for node in nodes:
        if not node.id or not node.name or not node.type or not node.file:
            issues.append(
                f"invalid node (missing mandatory field): "
                f"id={node.id!r} name={node.name!r} type={node.type!r} file={node.file!r}"
            )
            continue
        if node.type not in ALLOWED_NODE_TYPES:
            issues.append(f"node {node.id}: unknown type {node.type!r}")
            continue
        if node.id in seen_ids:
            issues.append(f"duplicate node id removed: {node.id}")
            continue
        seen_ids.add(node.id)
        valid_nodes.append(node)

    # ---- links ---------------------------------------------------------
    valid_links: List[CodeLink] = []
    seen_links = set()
    for link in links:
        if link.type not in ALLOWED_LINK_TYPES:
            issues.append(f"link {link.source} -> {link.target}: invalid type {link.type!r}")
            continue
        if link.source not in seen_ids:
            issues.append(f"link dropped, missing source node: {link.source}")
            continue
        if link.target not in seen_ids:
            issues.append(f"link dropped, missing target node: {link.target}")
            continue
        key = (link.source, link.target, link.type)
        if key in seen_links:
            continue  # exact duplicate; self-edges are NOT filtered out
        seen_links.add(key)
        valid_links.append(link)

    if issues:
        log.warning("graph validation reported %d issue(s)", len(issues))
    log.info(
        "graph validated: %d nodes, %d links", len(valid_nodes), len(valid_links)
    )
    return valid_nodes, valid_links, issues
