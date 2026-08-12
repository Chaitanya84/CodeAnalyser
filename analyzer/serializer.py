"""Deterministic JSON serialization of the code graph.

All collections are sorted before writing so the same source tree always
produces byte-identical output (modulo the omitted timestamps, which are
intentionally left out for source-control friendliness).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from .models import CodeLink, CodeNode

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


def build_payload(
    root: str,
    nodes: List[CodeNode],
    links: List[CodeLink],
    statistics: Dict,
    diagnostics: Dict,
) -> dict:
    sorted_nodes = sorted(nodes, key=lambda n: n.id)
    sorted_links = sorted(links, key=lambda l: (l.source, l.target, l.type))
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generator": "code_graph_analyzer",
            "source_root": root,
        },
        "statistics": statistics,
        "diagnostics": diagnostics,
        "nodes": [n.to_dict() for n in sorted_nodes],
        "links": [l.to_dict() for l in sorted_links],
    }


def write_json(payload: dict, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    output_path.write_text(text + "\n", encoding="utf-8")
    log.info("wrote %s (%d nodes, %d links)",
             output_path,
             len(payload["nodes"]),
             len(payload["links"]))
