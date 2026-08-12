"""Data models for the code graph analyzer.

All entities and relationships flow through these dataclasses so the
pipeline stages (parse -> extract -> index -> resolve -> serialize) share
one canonical representation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class CodeNode:
    """A single indexed source-code entity (graph node)."""

    id: str
    name: str
    qualified_name: str
    type: str                       # "function" | "class" | "variable"
    file: str                       # path relative to the analyzed root
    kind: Optional[str] = None      # "class" | "struct" | "function" | "method" | ...
    scope: Optional[str] = None     # qualified enclosing scope (class/namespace)
    signature: Optional[str] = None
    line: int = 0                   # 1-based
    column: int = 0                 # 0-based
    is_definition: bool = True
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "type": self.type,
            "kind": self.kind,
            "scope": self.scope,
            "signature": self.signature,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "is_definition": self.is_definition,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class CodeLink:
    """A directed, typed relationship between two nodes."""

    source: str
    target: str
    type: str                       # "calls" | "inherits" | "defines"

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "type": self.type}


@dataclass
class PendingCall:
    """A call site captured during extraction, resolved in a later pass."""

    caller_id: str
    caller_qualified_name: str
    kind: str                       # "direct" | "member" | "qualified" | "unknown"
    name: str                       # simple callee name
    raw: Optional[str] = None       # qualified text, e.g. "A::B::foo"
    object_name: Optional[str] = None   # receiver text for member calls
    object_is_this: bool = False
    file: str = ""
    line: int = 0
    scope_segments: Tuple[str, ...] = ()    # caller scope chain (longest first usable)
    class_scope: Optional[str] = None       # enclosing class qname for methods
    local_types: Dict[str, str] = field(default_factory=dict)  # var -> type name


@dataclass
class PendingInheritance:
    """A base-class specifier captured during extraction."""

    derived_id: str
    derived_qualified_name: str
    base_raw: str                   # textual base name, e.g. "Base" or "ns::Base"
    file: str
    line: int
    scope_segments: Tuple[str, ...] = ()
