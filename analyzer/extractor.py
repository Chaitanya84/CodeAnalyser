"""AST entity extraction with scope/context tracking.

Walks each parsed AST once, maintaining an explicit scope stack
(file -> namespaces -> classes). Produces:

- entity nodes (functions, methods, classes, structs, global/member vars)
- pending call sites and pending inheritance records, resolved later
  against the global symbol index (never during extraction).

No regex is used anywhere: every decision is driven by Tree-sitter node
types and named fields via the grammar adapter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from . import grammar_adapter as ga
from .ast_utils import compact_text, node_text, start_column, start_line
from .models import CodeNode, PendingCall, PendingInheritance
from .parser import ParsedFile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Scope:
    """Immutable scope context threaded through the AST walk."""

    file: str
    segments: Tuple[str, ...] = ()       # namespace/class name segments, in order
    class_ids: Tuple[str, ...] = ()      # ids of enclosing classes (if any)

    @property
    def qualified(self) -> str:
        return "::".join(self.segments)

    def child(self, name: str, class_id: Optional[str] = None) -> "_Scope":
        return _Scope(
            file=self.file,
            segments=self.segments + (name,),
            class_ids=self.class_ids + ((class_id,) if class_id else ()),
        )


class EntityExtractor:
    """Single-pass AST walker collecting entities and pending relationships."""

    def __init__(self) -> None:
        self.nodes: List[CodeNode] = []
        self.pending_calls: List[PendingCall] = []
        self.pending_inheritance: List[PendingInheritance] = []

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------

    def extract_file(self, parsed: ParsedFile) -> None:
        if not parsed.parsed_ok:
            return
        self._walk(parsed.tree.root_node, _Scope(file=parsed.relative_path))

    # ------------------------------------------------------------------
    # generic dispatch
    # ------------------------------------------------------------------

    def _walk(self, node, scope: _Scope) -> None:
        node_type = node.type
        if node_type == "namespace_definition":
            self._process_namespace(node, scope)
        elif node_type in ga.CLASS_SPECIFIER_TYPES:
            if ga.is_class_definition(node):
                self._process_class(node, scope)
            # forward declarations are intentionally not indexed as nodes
        elif ga.is_function_definition(node):
            self._process_function(node, scope)
        elif ga.is_variable_declaration(node):
            self._process_declaration(node, scope)
        else:
            # template_declaration, linkage_specification ("extern \"C\""),
            # using-declarations, preproc regions, ... : recurse so wrapped
            # entities are still found. Function bodies are never reached
            # here because function_definition is handled above and does
            # not recurse (locals are not graph nodes).
            for child in node.named_children:
                self._walk(child, scope)

    # ------------------------------------------------------------------
    # namespaces
    # ------------------------------------------------------------------

    def _process_namespace(self, node, scope: _Scope) -> None:
        segments = ga.namespace_segments(node.child_by_field_name("name"))
        child_scope = scope
        for segment in segments:
            child_scope = child_scope.child(segment)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.named_children:
                self._walk(child, child_scope)
        else:
            for child in node.named_children:
                self._walk(child, child_scope)

    # ------------------------------------------------------------------
    # classes / structs
    # ------------------------------------------------------------------

    def _process_class(self, node, scope: _Scope) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = compact_text(name_node)
        else:
            name = f"<anonymous_{start_line(node)}>"
        kind = ga.class_kind(node)
        qualified = f"{scope.qualified}::{name}" if scope.qualified else name
        class_id = f"{scope.file}::{qualified}"

        self.nodes.append(
            CodeNode(
                id=class_id,
                name=name,
                qualified_name=qualified,
                type="class",
                kind=kind,
                scope=scope.qualified or None,
                file=scope.file,
                line=start_line(node),
                column=start_column(node),
                is_definition=True,
                metadata={"kind": kind},
            )
        )

        # inheritance (resolved later against the symbol index)
        for base in ga.get_base_type_names(node):
            self.pending_inheritance.append(
                PendingInheritance(
                    derived_id=class_id,
                    derived_qualified_name=qualified,
                    base_raw=base,
                    file=scope.file,
                    line=start_line(node),
                    scope_segments=scope.segments,
                )
            )

        body = node.child_by_field_name("body")
        if body is not None:
            child_scope = scope.child(name, class_id=class_id)
            for child in body.named_children:
                if child.type == "access_specifier":
                    continue  # "public:" / "private:" labels carry no entity
                self._walk(child, child_scope)

    # ------------------------------------------------------------------
    # functions / methods
    # ------------------------------------------------------------------

    def _make_function_node(
        self, fn_declarator, scope: _Scope, is_definition: bool
    ) -> Optional[CodeNode]:
        qtext = ga.declarator_qualified_text(fn_declarator)
        if not qtext:
            return None
        absolute = qtext.startswith("::")
        qtext = qtext.strip(":")
        segments = [s for s in qtext.split("::") if s]
        if not segments:
            return None
        name = segments[-1]
        qualifier = segments[:-1]
        if absolute:
            full = segments
        else:
            full = list(scope.segments) + qualifier + [name]
        qualified = "::".join(full)
        scope_qname = "::".join(full[:-1]) or None

        params = ga.parameters_text(fn_declarator)
        signature = f"{name}{params}"
        node_id = f"{scope.file}::{qualified}::{params}"

        is_method = bool(qualifier) or bool(scope.class_ids)
        kind = "method" if is_method else "function"
        class_hint = qualifier[-1] if qualifier else (
            scope.segments[-1] if scope.class_ids else None
        )
        if name.startswith("~"):
            kind = "destructor"
        elif class_hint and name == class_hint:
            kind = "constructor"

        return CodeNode(
            id=node_id,
            name=name,
            qualified_name=qualified,
            type="function",
            kind=kind,
            scope=scope_qname,
            signature=signature,
            file=scope.file,
            line=start_line(fn_declarator),
            column=start_column(fn_declarator),
            is_definition=is_definition,
            metadata={
                "parameters": params,
                "is_method": is_method,
                "class_qualifier": qualifier[-1] if qualifier else None,
            },
        )

    def _process_function(self, node, scope: _Scope) -> None:
        fn_declarator = ga.get_function_declarator(node)
        if fn_declarator is None:
            log.debug("unusable function declarator in %s line %d",
                      scope.file, start_line(node))
            return
        fn_node = self._make_function_node(fn_declarator, scope, is_definition=True)
        if fn_node is None:
            return
        self.nodes.append(fn_node)

        body = ga.get_function_body(node)
        if body is not None:
            local_types = self._parameter_types(fn_declarator)
            self._collect_calls(body, fn_node, local_types)
        # Deliberately no recursion into the body: local variables are not
        # graph nodes and nested entity definitions inside functions are
        # out of scope for the primary graph.

    # ------------------------------------------------------------------
    # declarations: variables, fields, function declarations
    # ------------------------------------------------------------------

    def _process_declaration(self, node, scope: _Scope) -> None:
        type_node = node.child_by_field_name("type")

        # `class C { ... };` and `struct S { ... } s;` carry the definition
        # in the type slot of a declaration.
        if (
            type_node is not None
            and type_node.type in ga.CLASS_SPECIFIER_TYPES
            and ga.is_class_definition(type_node)
        ):
            self._process_class(type_node, scope)

        type_name = ga.type_name_of(type_node)
        is_field = node.type == "field_declaration"

        for raw_declarator in ga.get_declarators(node):
            declarator = ga.unwrap_declarator(raw_declarator)
            if declarator is None:
                continue
            if declarator.type == ga.FUNCTION_DECLARATOR:
                # function / method declaration without a body
                fn_node = self._make_function_node(declarator, scope, is_definition=False)
                if fn_node is not None:
                    fn_node.kind = "method" if fn_node.metadata["is_method"] else "function"
                    self.nodes.append(fn_node)
                continue
            if declarator.type not in ("identifier", "field_identifier"):
                continue
            name = compact_text(declarator)
            if not name:
                continue
            qualified = f"{scope.qualified}::{name}" if scope.qualified else name
            var_id = f"{scope.file}::{qualified}"
            self.nodes.append(
                CodeNode(
                    id=var_id,
                    name=name,
                    qualified_name=qualified,
                    type="variable",
                    kind="field" if is_field else "variable",
                    scope=scope.qualified or None,
                    file=scope.file,
                    line=start_line(declarator),
                    column=start_column(declarator),
                    is_definition=True,
                    metadata={"type_name": type_name},
                )
            )

    # ------------------------------------------------------------------
    # call-site collection (resolution happens in the resolver pass)
    # ------------------------------------------------------------------

    def _parameter_types(self, fn_declarator) -> Dict[str, str]:
        """Map parameter names to best-effort type names for a function."""
        result: Dict[str, str] = {}
        params = fn_declarator.child_by_field_name("parameters")
        if params is None:
            return result
        for param in params.named_children:
            if param.type != "parameter_declaration":
                continue
            type_name = ga.type_name_of(param.child_by_field_name("type"))
            declarator = ga.unwrap_declarator(param.child_by_field_name("declarator"))
            if type_name and declarator is not None and declarator.type == "identifier":
                result[compact_text(declarator)] = type_name
        return result

    def _collect_calls(self, body, caller: CodeNode, local_types: Dict[str, str]) -> None:
        """Walk a function body once, recording call sites and local types."""
        scope_segments = tuple(caller.qualified_name.split("::")[:-1])
        class_scope = caller.scope if caller.metadata.get("is_method") else None

        stack = [body]
        while stack:
            node = stack.pop()
            for i in range(len(node.named_children) - 1, -1, -1):
                stack.append(node.named_children[i])

            if node.type == "declaration":
                # track simple local variable types for member-call resolution
                type_name = ga.type_name_of(node.child_by_field_name("type"))
                if type_name:
                    for raw in ga.get_declarators(node):
                        d = ga.unwrap_declarator(raw)
                        if d is not None and d.type == "identifier":
                            local_types.setdefault(compact_text(d), type_name)
                continue

            if not ga.is_call_expression(node):
                continue

            pending = self._classify_call(
                node, caller, scope_segments, class_scope, dict(local_types)
            )
            if pending is not None:
                self.pending_calls.append(pending)

    def _classify_call(
        self, call_node, caller: CodeNode, scope_segments, class_scope, local_types
    ) -> Optional[PendingCall]:
        fn = ga.call_function_node(call_node)
        if fn is None:
            return None

        base = dict(
            caller_id=caller.id,
            caller_qualified_name=caller.qualified_name,
            file=caller.file,
            line=start_line(call_node),
            scope_segments=scope_segments,
            class_scope=class_scope,
            local_types=local_types,
        )

        fn_type = fn.type
        if fn_type == "identifier":
            return PendingCall(kind="direct", name=compact_text(fn), **base)

        if fn_type == "qualified_identifier":
            raw = compact_text(fn)
            name = raw.split("::")[-1]
            return PendingCall(kind="qualified", name=name, raw=raw, **base)

        if fn_type == "template_function":
            name_node = fn.child_by_field_name("name")
            if name_node is None:
                return None
            raw = compact_text(name_node)
            name = raw.split("::")[-1]
            kind = "qualified" if "::" in raw else "direct"
            return PendingCall(kind=kind, name=name, raw=raw if "::" in raw else None, **base)

        if fn_type == "field_expression":
            argument, field = ga.field_expression_parts(fn)
            if field is None:
                return None
            name = compact_text(field)
            object_name = None
            object_is_this = False
            if argument is not None:
                if argument.type == "this":
                    object_is_this = True
                elif argument.type == "identifier":
                    object_name = compact_text(argument)
                # any other receiver expression (call result, cast, ...) is
                # left as unknown: better unresolved than fabricated.
            return PendingCall(
                kind="member",
                name=name,
                object_name=object_name,
                object_is_this=object_is_this,
                **base,
            )

        # parenthesized callees, function pointers, etc.
        return PendingCall(
            kind="unknown", name=compact_text(fn), raw=compact_text(fn), **base
        )
