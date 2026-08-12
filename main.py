#!/usr/bin/env python3
"""Code Graph Analyzer — entry point.

Pipeline:
    scan -> parse -> validate AST -> extract entities -> build symbol index
    -> resolve relationships -> validate graph -> JSON -> 3D HTML graph

Usage:
    python main.py /path/to/source [--output code_graph.json]
                                   [--html code_graph.html] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from analyzer.extractor import EntityExtractor
from analyzer.parser import SourceParser
from analyzer.resolver import RelationshipResolver
from analyzer.scanner import normalize_relative, scan
from analyzer.serializer import build_payload, write_json
from analyzer.symbol_table import SymbolTable
from analyzer.validator import validate_graph
from visualization.visualizer import render

log = logging.getLogger("code_graph_analyzer")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code_graph_analyzer",
        description=(
            "Statically analyze a C/C++ source tree with Tree-sitter, build a "
            "symbol/relationship graph, and render it as an interactive 3D "
            "HTML visualization."
        ),
    )
    parser.add_argument("source", help="root directory of the C/C++ source tree")
    parser.add_argument(
        "--output", default="code_graph.json",
        help="JSON output path (default: code_graph.json)",
    )
    parser.add_argument(
        "--html", default="code_graph.html",
        help="HTML visualization output path (default: code_graph.html)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="enable debug-level logging"
    )
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def run(source: Path, output: Path, html: Path) -> int:
    root = source.resolve()
    if not root.exists():
        log.error("source directory does not exist: %s", source)
        return 2
    if not root.is_dir():
        log.error("source path is not a directory: %s", source)
        return 2

    # ---- Pass 1: scan + parse -------------------------------------------
    files = scan(root)
    parser = SourceParser()
    parsed_files = []
    for path in files:
        parsed_files.append(parser.parse_file(path, normalize_relative(path, root)))

    # ---- Pass 2: entity extraction --------------------------------------
    extractor = EntityExtractor()
    for parsed in parsed_files:
        try:
            extractor.extract_file(parsed)
        except Exception as exc:  # one bad file must not kill the pipeline
            log.error("extraction failed for %s: %s", parsed.relative_path, exc)

    # ---- Pass 3: global symbol index ------------------------------------
    symbols = SymbolTable()
    symbols.add_all(extractor.nodes)
    log.info("symbol index: %d unique entities", len(symbols.nodes))

    # ---- Pass 4: relationship resolution --------------------------------
    resolver = RelationshipResolver(symbols)
    links = resolver.resolve_all(extractor.pending_calls, extractor.pending_inheritance)

    # ---- Pass 5: validation ----------------------------------------------
    nodes, links, validation_issues = validate_graph(
        list(symbols.nodes.values()), links
    )

    # ---- statistics + diagnostics ---------------------------------------
    files_with_errors = [p for p in parsed_files if p.has_syntax_error]
    files_unreadable = [p for p in parsed_files if p.read_error]
    statistics = {
        "files_scanned": len(files),
        "files_parsed": sum(1 for p in parsed_files if p.parsed_ok),
        "files_with_syntax_errors": len(files_with_errors),
        "files_unreadable": len(files_unreadable),
        "ast_nodes": sum(p.total_nodes for p in parsed_files),
        "nodes": len(nodes),
        "links": len(links),
        "functions": sum(1 for n in nodes if n.type == "function" and n.is_definition),
        "function_declarations": sum(
            1 for n in nodes if n.type == "function" and not n.is_definition
        ),
        "classes": sum(1 for n in nodes if n.type == "class" and n.kind == "class"),
        "structs": sum(1 for n in nodes if n.type == "class" and n.kind == "struct"),
        "variables": sum(1 for n in nodes if n.type == "variable"),
        "calls": resolver.resolved_calls,
        "inherits": resolver.resolved_inheritance,
        "defines": resolver.resolved_defines,
        "resolved_relationships": (
            resolver.resolved_calls
            + resolver.resolved_inheritance
            + resolver.resolved_defines
        ),
        "ambiguous_calls": len(resolver.ambiguous_calls),
        "unresolved_calls": len(resolver.unresolved_calls),
        "unresolved_inheritance": len(resolver.unresolved_inheritance),
        "duplicate_symbols": len(symbols.duplicate_ids),
        "validation_issues": len(validation_issues),
    }
    diagnostics = {
        "files": sorted(
            (p.diagnostic() for p in parsed_files),
            key=lambda d: d["file"],
        ),
        "duplicate_symbols": sorted(set(symbols.duplicate_ids)),
        "unresolved_calls": resolver.unresolved_calls,
        "ambiguous_calls": resolver.ambiguous_calls,
        "unresolved_inheritance": resolver.unresolved_inheritance,
        "ambiguous_defines": resolver.ambiguous_defines,
        "validation_issues": validation_issues,
    }

    # ---- outputs ----------------------------------------------------------
    payload = build_payload(str(root), nodes, links, statistics, diagnostics)
    write_json(payload, output)
    try:
        render(output, html)
    except Exception as exc:
        log.error("visualization failed: %s", exc)
        return 1

    log.info(
        "done: %d files, %d nodes, %d links (calls=%d inherits=%d defines=%d, "
        "unresolved_calls=%d)",
        statistics["files_scanned"],
        statistics["nodes"],
        statistics["links"],
        statistics["calls"],
        statistics["inherits"],
        statistics["defines"],
        statistics["unresolved_calls"],
    )
    return 0


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.verbose)
    return run(Path(args.source), Path(args.output), Path(args.html))


if __name__ == "__main__":
    sys.exit(main())
