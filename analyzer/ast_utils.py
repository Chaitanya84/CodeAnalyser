"""Generic Tree-sitter AST helpers.

Traversal, source locations, text extraction and syntax-error detection.
Nothing here knows about specific C/C++ grammar node semantics; that lives
in grammar_adapter.py.
"""
from __future__ import annotations

from typing import Dict, Iterator, List

# Cap the number of individual error nodes reported per file so diagnostics
# stay readable for badly malformed sources.
MAX_REPORTED_ERRORS = 25


def node_text(node) -> str:
    """Decode the exact source text covered by a node."""
    return node.text.decode("utf-8", errors="replace")


def compact_text(node) -> str:
    """Node text with all whitespace removed (identifiers, qualified names)."""
    return "".join(node_text(node).split())


def normalize_ws(text: str) -> str:
    """Collapse runs of whitespace to single spaces (signatures)."""
    return " ".join(text.split())


def start_line(node) -> int:
    """1-based start line (Tree-sitter points are 0-based rows)."""
    point = node.start_point
    return (point[0] if not hasattr(point, "row") else point.row) + 1


def start_column(node) -> int:
    """0-based start column."""
    point = node.start_point
    return point[1] if not hasattr(point, "column") else point.column


def end_line(node) -> int:
    point = node.end_point
    return (point[0] if not hasattr(point, "row") else point.row) + 1


def end_column(node) -> int:
    point = node.end_point
    return point[1] if not hasattr(point, "column") else point.column


def iter_nodes(root) -> Iterator:
    """Depth-first iteration over every node (named and anonymous)."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        children = node.children
        for i in range(len(children) - 1, -1, -1):
            stack.append(children[i])


def count_nodes(root) -> int:
    return sum(1 for _ in iter_nodes(root))


def collect_syntax_errors(root) -> List[Dict]:
    """Recursively find ERROR and MISSING nodes in the AST.

    A file is cleanly parsed only when both lists are empty. Malformed
    regions are reported with locations but never raise.
    """
    errors: List[Dict] = []
    for node in iter_nodes(root):
        is_error = node.type == "ERROR" or node.is_error
        is_missing = node.is_missing
        if not (is_error or is_missing):
            continue
        if len(errors) >= MAX_REPORTED_ERRORS:
            continue
        errors.append(
            {
                "type": "ERROR" if is_error else "MISSING",
                "node_type": node.type,
                "start_line": start_line(node),
                "start_column": start_column(node),
                "end_line": end_line(node),
                "end_column": end_column(node),
            }
        )
    return errors
