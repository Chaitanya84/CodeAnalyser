"""Tree-sitter parser layer.

Owns grammar loading, per-file language selection, parsing and parser
diagnostics. This module never extracts entities or resolves relationships:
parsing and indexing are separate pipeline phases.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from tree_sitter import Language, Parser
import tree_sitter_c
import tree_sitter_cpp

from .ast_utils import collect_syntax_errors, count_nodes
from .scanner import C_EXTENSIONS

log = logging.getLogger(__name__)


def get_language_name_for_file(path: Path) -> str:
    """Select the grammar for a source file.

    Only ``.c`` uses the C grammar; every other supported extension
    (including all headers) uses the C++ grammar.
    """
    return "c" if path.suffix.lower() in C_EXTENSIONS else "cpp"


@dataclass
class ParsedFile:
    """Result of parsing one source file."""

    path: Path
    relative_path: str
    language: str
    source: bytes = b""
    tree: Optional[object] = None
    total_nodes: int = 0
    error_nodes: int = 0
    missing_nodes: int = 0
    has_syntax_error: bool = False
    errors: List[dict] = field(default_factory=list)
    read_error: Optional[str] = None

    @property
    def parsed_ok(self) -> bool:
        return self.tree is not None and self.read_error is None

    def diagnostic(self) -> dict:
        return {
            "file": self.relative_path,
            "language": self.language,
            "total_nodes": self.total_nodes,
            "error_nodes": self.error_nodes,
            "missing_nodes": self.missing_nodes,
            "has_syntax_error": self.has_syntax_error,
            "read_error": self.read_error,
            "errors": self.errors,
        }


class SourceParser:
    """Loads both grammars once and parses files on demand."""

    def __init__(self) -> None:
        self._languages: Dict[str, Language] = {
            "c": Language(tree_sitter_c.language()),
            "cpp": Language(tree_sitter_cpp.language()),
        }
        self._parsers: Dict[str, Parser] = {
            name: Parser(language) for name, language in self._languages.items()
        }
        log.debug("tree-sitter grammars loaded: %s", sorted(self._languages))

    def parse_file(self, path: Path, relative_path: str) -> ParsedFile:
        language = get_language_name_for_file(path)
        result = ParsedFile(path=path, relative_path=relative_path, language=language)

        try:
            source = path.read_bytes()
        except OSError as exc:
            result.read_error = f"{type(exc).__name__}: {exc}"
            log.warning("cannot read %s: %s", path, exc)
            return result

        result.source = source
        try:
            tree = self._parsers[language].parse(source)
        except Exception as exc:  # grammar/driver failure must not kill the run
            result.read_error = f"parser failure: {type(exc).__name__}: {exc}"
            log.warning("failed to parse %s: %s", path, exc)
            return result

        result.tree = tree
        result.total_nodes = count_nodes(tree.root_node)
        errors = collect_syntax_errors(tree.root_node)
        result.errors = errors
        result.error_nodes = sum(1 for e in errors if e["type"] == "ERROR")
        result.missing_nodes = sum(1 for e in errors if e["type"] == "MISSING")
        # counts above are capped by MAX_REPORTED_ERRORS; also check flags so a
        # file with more errors than the reporting cap is still flagged.
        result.has_syntax_error = bool(errors) or tree.root_node.has_error
        if result.has_syntax_error:
            log.debug(
                "syntax errors in %s (errors=%d missing=%d)",
                relative_path,
                result.error_nodes,
                result.missing_nodes,
            )
        return result
