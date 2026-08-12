"""Relationship resolution pass.

Runs strictly AFTER the global symbol index exists. Resolves pending call
sites, inheritance specifiers and containment (defines) relationships into
graph links, classifying each outcome as resolved / ambiguous / unresolved.

Policy: prefer a correct omission over an incorrect edge. Ambiguous and
unresolved relationships are recorded in diagnostics, never guessed.
Self-edges (recursive calls) are valid and preserved.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .models import CodeLink, CodeNode, PendingCall, PendingInheritance
from .symbol_table import SymbolTable

log = logging.getLogger(__name__)

# Keep diagnostic lists bounded for very large codebases.
MAX_DIAGNOSTIC_ENTRIES = 500


class RelationshipResolver:
    def __init__(self, symbols: SymbolTable) -> None:
        self.symbols = symbols
        self.links: List[CodeLink] = []
        self.resolved_calls = 0
        self.resolved_inheritance = 0
        self.resolved_defines = 0
        self.unresolved_calls: List[dict] = []
        self.ambiguous_calls: List[dict] = []
        self.unresolved_inheritance: List[dict] = []
        self.ambiguous_defines: List[dict] = []

    # ------------------------------------------------------------------
    # orchestration
    # ------------------------------------------------------------------

    def resolve_all(
        self,
        pending_calls: List[PendingCall],
        pending_inheritance: List[PendingInheritance],
    ) -> List[CodeLink]:
        self._resolve_defines()
        self._resolve_inheritance(pending_inheritance)
        self._resolve_calls(pending_calls)
        log.info(
            "resolution: %d calls, %d inherits, %d defines resolved "
            "(%d unresolved calls, %d ambiguous calls)",
            self.resolved_calls,
            self.resolved_inheritance,
            self.resolved_defines,
            len(self.unresolved_calls),
            len(self.ambiguous_calls),
        )
        return self.links

    # ------------------------------------------------------------------
    # defines (containment): class -> members
    # ------------------------------------------------------------------

    def _resolve_defines(self) -> None:
        """Link every entity whose scope is a known class to that class."""
        for node in list(self.symbols.nodes.values()):
            if not node.scope:
                continue
            classes = self.symbols.classes_by_qualified_name.get(node.scope, [])
            if len(classes) == 1:
                self._add_link(classes[0].id, node.id, "defines")
                self.resolved_defines += 1
            elif len(classes) > 1:
                self._record(
                    self.ambiguous_defines,
                    {
                        "member": node.id,
                        "scope": node.scope,
                        "candidates": sorted(c.id for c in classes),
                        "file": node.file,
                        "line": node.line,
                    },
                )

    # ------------------------------------------------------------------
    # inheritance
    # ------------------------------------------------------------------

    def _resolve_inheritance(self, pending: List[PendingInheritance]) -> None:
        for record in pending:
            base = record.base_raw.strip(":")  # tolerate leading '::'
            if not base:
                continue
            derived_segments = tuple(record.derived_qualified_name.split("::")[:-1])
            target, ambiguous = self.symbols.lookup_class(base, derived_segments)
            if target is not None:
                self._add_link(record.derived_id, target.id, "inherits")
                self.resolved_inheritance += 1
            elif ambiguous:
                self._record(
                    self.unresolved_inheritance,
                    {
                        "derived": record.derived_qualified_name,
                        "base": record.base_raw,
                        "reason": "ambiguous",
                        "file": record.file,
                        "line": record.line,
                    },
                )
            else:
                self._record(
                    self.unresolved_inheritance,
                    {
                        "derived": record.derived_qualified_name,
                        "base": record.base_raw,
                        "reason": "base class not found",
                        "file": record.file,
                        "line": record.line,
                    },
                )

    # ------------------------------------------------------------------
    # calls
    # ------------------------------------------------------------------

    def _resolve_calls(self, pending: List[PendingCall]) -> None:
        for call in pending:
            target, status = self._resolve_call(call)
            if target is not None:
                self._add_link(call.caller_id, target.id, "calls")
                self.resolved_calls += 1
            elif status == "ambiguous":
                self._record(self.ambiguous_calls, self._call_diagnostic(call, status))
            else:
                self._record(self.unresolved_calls, self._call_diagnostic(call, status))

    def _resolve_call(self, call: PendingCall) -> Tuple[Optional[CodeNode], str]:
        if call.kind == "member":
            return self._resolve_member_call(call)
        if call.kind == "qualified":
            return self._resolve_qualified_call(call)
        if call.kind == "direct":
            return self._resolve_direct_call(call)
        return None, "unresolvable callee expression"

    # -- direct (unqualified) calls ------------------------------------

    def _resolve_direct_call(self, call: PendingCall) -> Tuple[Optional[CodeNode], str]:
        """Resolution order: caller scope chain -> global -> unique by name."""
        segments = list(call.scope_segments)
        for i in range(len(segments), -1, -1):
            prefix = "::".join(segments[:i])
            candidate = f"{prefix}::{call.name}" if prefix else call.name
            found = self.symbols.functions_by_qualified_name.get(candidate)
            if found:
                picked = self.symbols._prefer_definition(found)
                return (picked, "resolved") if picked else (None, "ambiguous")
        found = self.symbols.functions_by_name.get(call.name, [])
        picked = self.symbols._prefer_definition(found) if found else None
        if picked is not None:
            return picked, "resolved"
        if found:
            return None, "ambiguous"
        return None, "no matching function"

    # -- qualified calls -------------------------------------------------

    def _resolve_qualified_call(self, call: PendingCall) -> Tuple[Optional[CodeNode], str]:
        raw = (call.raw or "").strip(":")
        if not raw:
            return None, "no matching function"
        segments = list(call.scope_segments)
        # try enclosing-namespace prefixes, longest first
        for i in range(len(segments), -1, -1):
            prefix = "::".join(segments[:i])
            candidate = f"{prefix}::{raw}" if prefix else raw
            found = self.symbols.functions_by_qualified_name.get(candidate)
            if found:
                picked = self.symbols._prefer_definition(found)
                return (picked, "resolved") if picked else (None, "ambiguous")
        # suffix fallback: a function whose qualified name ends with raw
        matches = [
            node
            for node in self.symbols.functions_by_name.get(call.name, [])
            if node.qualified_name == raw or node.qualified_name.endswith("::" + raw)
        ]
        picked = self.symbols._prefer_definition(matches) if matches else None
        if picked is not None:
            return picked, "resolved"
        if matches:
            return None, "ambiguous"
        return None, "no matching function"

    # -- member calls ----------------------------------------------------

    def _resolve_member_call(self, call: PendingCall) -> Tuple[Optional[CodeNode], str]:
        if call.object_is_this:
            if not call.class_scope:
                return None, "'this' outside method context"
            target, ambiguous = self.symbols.lookup_function_qname(
                f"{call.class_scope}::{call.name}"
            )
            if target is not None:
                return target, "resolved"
            if ambiguous:
                return None, "ambiguous"
            return None, f"method not found on {call.class_scope}"

        type_name: Optional[str] = None
        if call.object_name:
            type_name = call.local_types.get(call.object_name)
            if type_name is None:
                type_name = self.symbols.variable_type_name(
                    call.object_name, call.scope_segments
                )
        if not type_name:
            return None, "receiver type unknown"

        class_node, ambiguous = self.symbols.lookup_class(type_name, call.scope_segments)
        if class_node is None:
            return None, "ambiguous receiver type" if ambiguous else "receiver type unknown"

        target, fn_ambiguous = self.symbols.lookup_function_qname(
            f"{class_node.qualified_name}::{call.name}"
        )
        if target is not None:
            return target, "resolved"
        if fn_ambiguous:
            return None, "ambiguous"
        return None, f"method not found on {class_node.qualified_name}"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _add_link(self, source: str, target: str, link_type: str) -> None:
        self.links.append(CodeLink(source=source, target=target, type=link_type))

    @staticmethod
    def _record(bucket: List[dict], entry: dict) -> None:
        if len(bucket) < MAX_DIAGNOSTIC_ENTRIES:
            bucket.append(entry)

    @staticmethod
    def _call_diagnostic(call: PendingCall, status: str) -> dict:
        return {
            "caller": call.caller_qualified_name,
            "callee": call.raw or call.name,
            "kind": call.kind,
            "status": status,
            "file": call.file,
            "line": call.line,
        }
