"""C/C++ grammar compatibility layer.

All knowledge of concrete tree-sitter-c / tree-sitter-cpp node types and
named fields lives here, so the rest of the pipeline never touches
grammar-specific details. Node types below are the real ones exposed by
the two grammars (verified against the installed grammar versions).

Key grammar facts relied upon:

- ``function_definition`` fields: ``type``, ``declarator``, ``body``.
- ``function_declarator`` fields: ``declarator`` (name or nested
  declarator / qualified_identifier / destructor_name), ``parameters``.
- ``declaration`` / ``field_declaration`` fields: ``type``, ``declarator``
  (``declarator`` is a repeated field for ``int a, b;``).
- C++ ``class_specifier`` covers both ``class`` and ``struct`` (the first
  anonymous child is the keyword); C uses ``struct_specifier``.
  Fields: ``name``, ``body``; inheritance lives in a ``base_class_clause``
  named child containing ``access_specifier`` markers plus
  ``type_identifier`` / ``qualified_identifier`` / ``template_type`` bases.
- ``namespace_definition`` fields: ``name`` (``namespace_identifier`` or
  ``nested_namespace_specifier`` for ``namespace A::B {}``), ``body``.
- ``call_expression`` fields: ``function``, ``arguments``.
- ``field_expression`` fields: ``argument``, ``field`` (``.`` / ``->`` are
  anonymous operator children).
"""
from __future__ import annotations

from typing import List, Optional

from .ast_utils import compact_text, node_text, normalize_ws

FUNCTION_DEFINITION = "function_definition"
FUNCTION_DECLARATOR = "function_declarator"
CLASS_SPECIFIER_TYPES = {"class_specifier", "struct_specifier"}
CALL_EXPRESSION = "call_expression"

# Declarator wrappers that must be peeled to reach the meaningful core.
_WRAPPER_DECLARATORS = {
    "pointer_declarator",
    "reference_declarator",
    "array_declarator",
    "parenthesized_declarator",
    "init_declarator",
}

_IDENTIFIER_TYPES = {"identifier", "field_identifier", "type_identifier"}


# ---------------------------------------------------------------------------
# node classification
# ---------------------------------------------------------------------------

def is_function_definition(node) -> bool:
    return node.type == FUNCTION_DEFINITION


def is_class_definition(node) -> bool:
    """True for class/struct nodes with a body (real definitions)."""
    return node.type in CLASS_SPECIFIER_TYPES and node.child_by_field_name("body") is not None


def is_forward_declaration(node) -> bool:
    """``class Foo;`` / ``struct Bar;`` -- declared but not defined."""
    return node.type in CLASS_SPECIFIER_TYPES and node.child_by_field_name("body") is None


def is_call_expression(node) -> bool:
    return node.type == CALL_EXPRESSION


def is_variable_declaration(node) -> bool:
    return node.type in ("declaration", "field_declaration")


def class_kind(node) -> str:
    """Return ``"class"`` or ``"struct"`` for a class/struct specifier."""
    if node.type == "struct_specifier":
        return "struct"
    # class_specifier: the first anonymous child is the keyword itself.
    for child in node.children:
        if not child.is_named:
            text = node_text(child)
            if text in ("class", "struct"):
                return text
            break
    return "class"


# ---------------------------------------------------------------------------
# named-field accessors
# ---------------------------------------------------------------------------

def get_node_name(node):
    return node.child_by_field_name("name")


def get_function_body(function_definition):
    return function_definition.child_by_field_name("body")


def get_function_declarator(function_definition):
    """Return the ``function_declarator`` of a function definition.

    The declared ``declarator`` field may be wrapped in pointer/reference/
    parenthesized declarators (e.g. ``void (*signal(int, void(*)(int)))(int)``
    or ``Device &Device::operator=``); peel wrappers until the
    ``function_declarator`` core is found.
    """
    node = function_definition.child_by_field_name("declarator")
    while node is not None:
        if node.type == FUNCTION_DECLARATOR:
            return node
        if node.type in _WRAPPER_DECLARATORS:
            node = node.child_by_field_name("declarator")
            continue
        return None
    return None


def unwrap_declarator(node):
    """Peel pointer/array/reference/paren/init wrappers from a declarator."""
    while node is not None and node.type in _WRAPPER_DECLARATORS:
        node = node.child_by_field_name("declarator")
    return node


def get_declarators(declaration) -> List:
    """All declarators of a declaration (``int a, b;`` has two)."""
    declarators = list(declaration.children_by_field_name("declarator"))
    return declarators


def declarator_qualified_text(function_declarator) -> Optional[str]:
    """Qualified name text of a function declarator, e.g. ``Device::start``.

    Returns text possibly carrying a leading ``::`` for explicitly global
    qualifications; callers handle that. Returns None when no usable name
    exists (e.g. anonymous function-pointer declarators).
    """
    node = function_declarator.child_by_field_name("declarator")
    while node is not None and node.type in _WRAPPER_DECLARATORS:
        node = node.child_by_field_name("declarator")
    if node is None:
        return None
    if node.type in _IDENTIFIER_TYPES:
        return compact_text(node)
    if node.type in ("qualified_identifier", "destructor_name", "operator_function_id"):
        return compact_text(node)
    if node.type == "template_function":
        name = node.child_by_field_name("name")
        return compact_text(name) if name is not None else compact_text(node)
    if node.type == "dependent_name":
        inner = node.child_by_field_name("name")
        return compact_text(inner) if inner is not None else compact_text(node)
    # Last resort: exact source text (still AST-derived, not regex).
    return compact_text(node)


def parameters_text(function_declarator) -> str:
    """Normalized parameter-list text, e.g. ``(int x, char *y)``."""
    params = function_declarator.child_by_field_name("parameters")
    if params is None:
        return "()"
    return normalize_ws(node_text(params))


def namespace_segments(name_node) -> List[str]:
    """Namespace name as a list of segments.

    Handles ``namespace A`` (``namespace_identifier``/``identifier``) and
    ``namespace A::B`` (``nested_namespace_specifier``). Anonymous
    namespaces map to ``["<anonymous>"]``.
    """
    if name_node is None:
        return ["<anonymous>"]
    text = compact_text(name_node)
    if not text:
        return ["<anonymous>"]
    return [segment for segment in text.split("::") if segment]


def get_base_type_names(class_node) -> List[str]:
    """Base class names from a class/struct ``base_class_clause``.

    Skips access specifiers (``public``/``protected``/``private``) and the
    ``virtual`` keyword (anonymous node). Template bases contribute their
    template name only (``Container<T>`` -> ``Container``).
    """
    bases: List[str] = []
    for child in class_node.named_children:
        if child.type != "base_class_clause":
            continue
        for item in child.named_children:
            if item.type == "access_specifier":
                continue
            if item.type in ("type_identifier", "qualified_identifier"):
                bases.append(compact_text(item))
            elif item.type == "template_type":
                name = item.child_by_field_name("name")
                if name is not None:
                    bases.append(compact_text(name))
            elif item.type == "dependent_name":
                name = item.child_by_field_name("name")
                if name is not None:
                    bases.append(compact_text(name))
    return bases


def type_name_of(type_node) -> Optional[str]:
    """Best-effort simple class/type name for a declaration's type node.

    Returns None for primitive/unknown types. Used only for best-effort
    member-call resolution (``obj.start()``), never for fabrication.
    """
    if type_node is None:
        return None
    kind = type_node.type
    if kind == "type_identifier":
        return compact_text(type_node)
    if kind == "qualified_identifier":
        name = type_node.child_by_field_name("name")
        return compact_text(name) if name is not None else compact_text(type_node)
    if kind in ("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"):
        name = type_node.child_by_field_name("name")
        return compact_text(name) if name is not None else None
    if kind == "template_type":
        name = type_node.child_by_field_name("name")
        return compact_text(name) if name is not None else None
    if kind == "dependent_name":
        name = type_node.child_by_field_name("name")
        return compact_text(name) if name is not None else None
    return None


# ---------------------------------------------------------------------------
# call-expression decomposition
# ---------------------------------------------------------------------------

def call_function_node(call_expression):
    return call_expression.child_by_field_name("function")


def field_expression_parts(field_expression):
    """Return (argument_node, field_node) of a ``obj.member`` expression."""
    return (
        field_expression.child_by_field_name("argument"),
        field_expression.child_by_field_name("field"),
    )
