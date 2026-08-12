"""Global symbol index.

Built once after all files are parsed and all entities extracted. The
relationship resolver queries these dictionaries instead of re-walking
ASTs, keeping resolution close to O(relationships) rather than
O(files x entities).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from .models import CodeNode

log = logging.getLogger(__name__)


class SymbolTable:
    """Multi-index store over all extracted entities."""

    def __init__(self) -> None:
        self.nodes: Dict[str, CodeNode] = {}
        self.by_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.by_qualified_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.functions_by_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.functions_by_qualified_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.classes_by_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.classes_by_qualified_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.variables_by_name: Dict[str, List[CodeNode]] = defaultdict(list)
        self.by_file: Dict[str, List[CodeNode]] = defaultdict(list)
        self.duplicate_ids: List[str] = []

    def add(self, node: CodeNode) -> bool:
        """Index one node. Returns False for duplicate ids.

        When a declaration and a definition share an id (declared inside a
        class body and defined out-of-class in the same file), the
        definition replaces the declaration so the index and defines edges
        point at the definition.
        """
        if node.id in self.nodes:
            existing = self.nodes[node.id]
            self.duplicate_ids.append(node.id)
            if existing.is_definition or not node.is_definition:
                log.debug("duplicate symbol id skipped: %s", node.id)
                return False
            # replace declaration with the definition in every index
            for index, key in self._index_entries(existing):
                entries = index.get(key)
                if entries and existing in entries:
                    entries.remove(existing)
            del self.nodes[node.id]
        self._index(node)
        return True

    def _index_entries(self, node: CodeNode):
        entries = [
            (self.by_name, node.name),
            (self.by_qualified_name, node.qualified_name),
            (self.by_file, node.file),
        ]
        if node.type == "function":
            entries.append((self.functions_by_name, node.name))
            entries.append((self.functions_by_qualified_name, node.qualified_name))
        elif node.type == "class":
            entries.append((self.classes_by_name, node.name))
            entries.append((self.classes_by_qualified_name, node.qualified_name))
        elif node.type == "variable":
            entries.append((self.variables_by_name, node.name))
        return entries

    def _index(self, node: CodeNode) -> None:
        self.nodes[node.id] = node
        for index, key in self._index_entries(node):
            index[key].append(node)

    def add_all(self, nodes: List[CodeNode]) -> None:
        for node in nodes:
            self.add(node)

    # ------------------------------------------------------------------
    # lookup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prefer_definition(candidates: List[CodeNode]) -> Optional[CodeNode]:
        """Pick the unique definition among same-named candidates.

        Returns the single definition when exactly one exists; otherwise
        the single candidate; otherwise None (ambiguous).
        """
        definitions = [n for n in candidates if n.is_definition]
        pool = definitions or candidates
        if len(pool) == 1:
            return pool[0]
        return None

    def lookup_function_qname(self, qualified_name: str):
        """Unique function for a qualified name, else None."""
        candidates = self.functions_by_qualified_name.get(qualified_name, [])
        if not candidates:
            return None, False
        picked = self._prefer_definition(candidates)
        return picked, picked is None

    def lookup_class(self, name: str, scope_segments=()):
        """Resolve a (possibly relative) class name to a unique class node.

        Tries longest enclosing-scope prefix first, then the bare qualified
        name, then a unique unqualified match. Returns (node, ambiguous).
        """
        segments = list(scope_segments)
        for i in range(len(segments), -1, -1):
            prefix = "::".join(segments[:i])
            candidate = f"{prefix}::{name}" if prefix else name
            found = self.classes_by_qualified_name.get(candidate)
            if found:
                if len(found) == 1:
                    return found[0], False
                return None, True
        found = self.classes_by_name.get(name, [])
        if len(found) == 1:
            return found[0], False
        if found:
            return None, True
        return None, False

    def variable_type_name(self, name: str, scope_segments=()) -> Optional[str]:
        """Best-effort type name of a variable visible from a scope."""
        candidates = self.variables_by_name.get(name, [])
        typed = [v for v in candidates if v.metadata.get("type_name")]
        if not typed:
            return None
        # Prefer the variable whose scope is the longest prefix of the
        # caller's scope chain (nearest enclosing scope wins).
        caller_scope = "::".join(scope_segments)

        def scope_distance(var: CodeNode) -> int:
            scope = var.scope or ""
            if caller_scope == scope:
                return 0
            if caller_scope.startswith(scope + "::") or not scope:
                return 1
            return 2

        typed.sort(key=lambda v: (scope_distance(v), -len(v.scope or "")))
        return typed[0].metadata["type_name"]
