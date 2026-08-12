"""Recursive C/C++ source file discovery.

Responsible only for filesystem traversal, extension filtering, ignore
rules and deterministic path normalization. No parsing happens here.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

# Extensions analyzed by the tool. Everything else is skipped.
SOURCE_EXTENSIONS = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"}

# Files with these extensions use the C grammar; all others use C++.
C_EXTENSIONS = {".c"}

# Directories never entered. Extend freely.
IGNORED_DIRECTORIES = {
    ".git",
    ".vscode",
    ".idea",
    "__pycache__",
    "node_modules",
    "out",
}

# Directory names equal to a prefix or starting with "<prefix>-" are ignored
# (covers build/, build-*/, cmake-build-*/).
IGNORED_DIRECTORY_PREFIXES = ("build", "cmake-build")

IGNORED_FILES = {"Makefile", "makefile", "CMakeLists.txt", ".gitignore"}
IGNORED_SUFFIXES = {".o", ".a", ".so", ".dll", ".exe"}


def is_ignored_dir(name: str) -> bool:
    if name in IGNORED_DIRECTORIES:
        return True
    for prefix in IGNORED_DIRECTORY_PREFIXES:
        if name == prefix or name.startswith(prefix + "-"):
            return True
    return False


def is_ignored_file(name: str) -> bool:
    if name in IGNORED_FILES:
        return True
    return Path(name).suffix.lower() in IGNORED_SUFFIXES


def normalize_relative(path: Path, root: Path) -> str:
    """Return a deterministic, forward-slash relative path string."""
    return path.relative_to(root).as_posix()


def scan(root: Path) -> List[Path]:
    """Recursively collect analyzable source files under *root*.

    Returns a sorted list (deterministic ordering). Unreadable directories
    are logged and skipped rather than aborting the scan.
    """
    root = root.resolve()
    collected: List[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            log.warning("cannot read directory %s: %s", current, exc)
            continue
        for entry in entries:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    if not is_ignored_dir(entry.name):
                        stack.append(entry)
                elif entry.is_file():
                    if is_ignored_file(entry.name):
                        continue
                    if entry.suffix.lower() in SOURCE_EXTENSIONS:
                        collected.append(entry)
            except OSError as exc:
                log.warning("cannot stat %s: %s", entry, exc)
    collected.sort(key=lambda p: normalize_relative(p, root))
    log.info("scanner discovered %d source files under %s", len(collected), root)
    return collected
