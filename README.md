# Code Graph Analyzer

A static-analysis tool that recursively analyzes a C/C++ source tree using
**Tree-sitter**, builds a global symbol index, resolves relationships
between code entities (calls, inheritance, containment), stores the result
as deterministic JSON, and renders it as an interactive 3D graph.

## Architecture

```
SOURCE TREE
    |
    v
Recursive Scanner          (analyzer/scanner.py)
    |
    v
Tree-sitter Parser         (analyzer/parser.py, grammar_adapter.py)
    |
    v
AST Validation             (analyzer/ast_utils.py — ERROR/MISSING nodes)
    |
    v
Entity Extraction          (analyzer/extractor.py — scope/context tracking)
    |
    v
Global Symbol Index        (analyzer/symbol_table.py)
    |
    v
Relationship Resolution    (analyzer/resolver.py — calls/inherits/defines)
    |
    v
Graph Validation           (analyzer/validator.py)
    |
    v
JSON Index                 (analyzer/serializer.py -> code_graph.json)
    |
    v
NetworkX DiGraph + 3D Force Layout + Plotly   (visualization/visualizer.py -> code_graph.html)
```

Parsing, extraction, indexing and resolution are strictly separate passes.
The symbol index always exists before any relationship is resolved.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py ./my_cpp_project
```

Full options:

```bash
python main.py /path/to/source \
    --output code_graph.json \
    --html code_graph.html \
    --verbose
```

Outputs:

- `code_graph.json` — deterministic node/link index with statistics and diagnostics
- `code_graph.html` — interactive 3D graph (rotate, zoom, pan, hover, legend selection)

## Supported files

| Extension                              | Grammar         |
|----------------------------------------|-----------------|
| `.c`                                   | tree-sitter-c   |
| `.cpp .cc .cxx .h .hpp .hh .hxx`       | tree-sitter-cpp |

Headers use the C++ grammar by default. Ignored directories (`.git`,
`build*`, `cmake-build-*`, `out`, `node_modules`, `.vscode`, `.idea`,
`__pycache__`) and ignored files (`Makefile`, `CMakeLists.txt`, objects,
archives, shared libraries, executables) are configured at the top of
`analyzer/scanner.py` and are easy to extend.

## What is extracted

- **Functions** — free, static, namespaced, and qualified out-of-class
  definitions; constructors and destructors; declaration-only functions are
  indexed too (flagged `is_definition: false`) so calls can still resolve.
- **Classes and structs** — `type: "class"` nodes with `kind: "class"` or
  `"struct"`; nested and namespaced types supported; forward declarations
  are recognized but not indexed as nodes.
- **Variables** — translation-unit, namespace and class-member scope only.
  Local variables and parameters never become graph nodes.

## Relationship resolution

Resolution happens only after the global symbol index is complete:

- **calls** — resolved in scope order: exact qualified match → enclosing
  class → enclosing namespaces (longest first) → global → unique
  unqualified name. Member calls (`obj.start()`, `ptr->start()`,
  `this->start()`) resolve through best-effort receiver type tracking
  (locals, parameters, globals). Qualified calls (`ns::foo()`,
  `A::B::process()`) use the qualified AST representation. Recursive
  self-edges are kept.
- **inherits** — base classes come from real `base_class_clause` AST nodes;
  public/protected/private/virtual and multiple inheritance supported.
- **defines** — every entity whose scope is a known class gets a
  `defines` edge from that class.

Every relationship is classified `resolved` / `ambiguous` / `unresolved`.
Ambiguous or unresolved relationships are recorded in diagnostics and
never guessed — correct omission beats incorrect edges.

## JSON format

```json
{
  "metadata": {"schema_version": "1.0", "source_root": "..."},
  "statistics": {"files_scanned": 0, "functions": 0, "classes": 0, "...": 0},
  "diagnostics": {"files": [], "unresolved_calls": [], "ambiguous_calls": []},
  "nodes": [
    {"id": "src/device.cpp::Device::start::()", "name": "start",
     "qualified_name": "Device::start", "type": "function",
     "kind": "method", "scope": "Device", "file": "src/device.cpp",
     "line": 42, "is_definition": true}
  ],
  "links": [
    {"source": "...", "target": "...", "type": "calls"}
  ]
}
```

Node IDs are `<relative_file>::<qualified_name>::<parameters>` for
functions and `<relative_file>::<qualified_name>` for classes/variables —
globally unique and deterministic. All output arrays are sorted, so the
same source tree always produces the same JSON.

## Limitations

Tree-sitter is a parser, not a compiler. Resolution is **best-effort,
syntactic/name-based**:

- No template instantiation (templates parse fine; entities are indexed
  under their uninstantiated names).
- Overloads are distinguished by parameter text in IDs, but call resolution
  does not perform argument-type overload resolution — overloaded call
  targets are reported as ambiguous rather than guessed.
- Function pointers, virtual dispatch, ADL, implicit conversions and
  typedef/using-alias type chasing are not resolved.
- The preprocessor is not expanded: conditional compilation (`#ifdef`)
  is parsed as written, and macro-generated functions/calls may be
  missing or unresolvable.
- Member calls whose receiver type cannot be determined syntactically
  (e.g. returned from another call) are recorded as unresolved.
- Files with syntax errors are still analyzed best-effort, but
  relationships from error regions may be missing; such files are flagged
  in `diagnostics.files`.

## Performance

Each file is parsed once, each AST walked once for extraction, the symbol
index built once, and relationships resolved once via dictionary lookups:

```
O(total AST size + relationship count)
```

No per-entity rescans of files or ASTs. Thousands of files are fine.

## Project layout

```
main.py                    pipeline orchestration + CLI
analyzer/
    scanner.py             recursive file discovery, ignore rules
    parser.py              tree-sitter grammar loading, parsing, diagnostics
    grammar_adapter.py     all C/C++ grammar-specific node handling
    ast_utils.py           traversal, locations, syntax-error detection
    extractor.py           entity extraction with scope tracking
    symbol_table.py        global multi-index symbol store
    resolver.py            calls / inherits / defines resolution
    validator.py           graph integrity checks, duplicate removal
    serializer.py          deterministic JSON output
visualization/
    visualizer.py          NetworkX + 3D spring layout + Plotly HTML
```
