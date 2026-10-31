import ast
import importlib.util
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from pyflakes import api as pyflakes_api
from pyflakes import reporter as pyflakes_reporter


class PyflakesLintReporter(pyflakes_reporter.Reporter):
    """Collects pyflakes lint messages into structured dictionaries."""

    def __init__(self):
        self.issues: List[Dict[str, Any]] = []

    def unexpectedError(self, filename: str, msg: str):
        self.issues.append({"file": filename, "line": 0, "message": f"Unexpected error: {msg}"})

    def syntaxError(self, filename: str, msg: str, lineno: int, offset: int, text: str):
        self.issues.append({"file": filename, "line": lineno or 0, "message": f"Syntax error: {msg}"})

    def flake(self, message):
        formatted = message.message % message.message_args
        self.issues.append({
            "file": message.filename,
            "line": message.lineno,
            "message": formatted,
        })


def run_pyflakes_lint(code_dict: Dict[str, str]) -> List[Dict[str, Any]]:
    """Runs pyflakes over each file in code_dict and returns lint issues."""
    reporter = PyflakesLintReporter()
    for filename, source in code_dict.items():
        try:
            pyflakes_api.check(source, filename, reporter=reporter)
        except Exception as e:
            reporter.unexpectedError(filename, str(e))
    return reporter.issues


def resolve_relative_module(current_file: str, module_name: Optional[str], level: int) -> str:
    """
    Resolves relative imports using node.level against the current file's package path.
    level 1: current directory/package
    level 2: parent directory, etc.
    """
    if level == 0:
        return module_name or ""

    curr_path = Path(current_file).parent
    parts = list(curr_path.parts)

    up = level - 1
    if up > 0 and len(parts) >= up:
        parts = parts[:-up]
    elif up > 0:
        parts = []

    prefix = ".".join(parts)
    if prefix and module_name:
        return f"{prefix}.{module_name}"
    elif module_name:
        return module_name
    return base_pkg if (base_pkg := ".".join(parts)) else (module_name or "")


def find_local_target(module_name: str, code_keys: List[str]) -> Optional[str]:
    """
    Attempts to map module_name to a file in code_keys:
    - try module.py and module/__init__.py
    - try with 'src/' prefix stripped or added
    """
    normalized_map = {k.replace("\\", "/").lstrip("./"): k for k in code_keys}
    slash_mod = module_name.replace(".", "/")

    candidates = [
        f"{slash_mod}.py",
        f"{slash_mod}/__init__.py",
        slash_mod,
    ]

    # Try stripping src/
    if slash_mod.startswith("src/"):
        stripped = slash_mod[4:]
        candidates.extend([f"{stripped}.py", f"{stripped}/__init__.py", stripped])
    else:
        # Try adding src/
        candidates.extend([f"src/{slash_mod}.py", f"src/{slash_mod}/__init__.py", f"src/{slash_mod}"])

    for cand in candidates:
        clean_cand = cand.replace("\\", "/").lstrip("./")
        if clean_cand in normalized_map:
            return normalized_map[clean_cand]

    # Basename fallback if path structure is flat or partial
    target_stem = slash_mod.split("/")[-1]
    for norm_k, orig in normalized_map.items():
        p = Path(norm_k)
        if p.stem == target_stem or norm_k.endswith(f"/{slash_mod}.py") or norm_k == f"{slash_mod}.py":
            return orig

    return None


def extract_top_level_symbols(source_code: str) -> Set[str]:
    """Parses Python source code and collects all top-level symbols."""
    symbols: Set[str] = set()
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return symbols

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            symbols.add(elt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                symbols.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                symbols.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                symbols.add(alias.asname or alias.name)

    return symbols


def classify_module_kind(
    module_name: str,
    code_keys: List[str],
) -> Tuple[str, Optional[str]]:
    """
    Resolves an imported module into (kind, target_node_id):
    - 'local': maps to a file in the code dict
    - 'stdlib': top-level name in sys.stdlib_module_names
    - 'external': importlib.util.find_spec succeeds
    - 'missing': none of the above
    """
    local_target = find_local_target(module_name, code_keys)
    if local_target is not None:
        return "local", local_target

    top_level = module_name.split(".")[0]
    stdlib_modules = getattr(sys, "stdlib_module_names", set())
    if top_level in stdlib_modules:
        return "stdlib", top_level

    try:
        spec = importlib.util.find_spec(top_level)
        if spec is not None:
            return "external", top_level
    except Exception:
        pass

    return "missing", module_name


def build_dependency_graph(
    code: Dict[str, str],
    changed_files: List[str],
) -> Tuple[Dict[str, Any], nx.DiGraph, List[Dict[str, Any]]]:
    """
    Deterministic dependency graph builder:
    Input:
      code: dict of path -> source
      changed_files: list of paths
    Output:
      (dep_graph_dict, G_networkx, lint_issues)
    """
    G = nx.DiGraph()
    code_keys = list(code.keys())
    target_symbols_cache: Dict[str, Set[str]] = {}

    # Initialize all local files as local nodes in the graph
    for file_path in code_keys:
        G.add_node(file_path, kind="local")
        target_symbols_cache[file_path] = extract_top_level_symbols(code[file_path])

    edges: List[Dict[str, Any]] = []
    broken_links: List[Dict[str, Any]] = []

    # 1. Parse each file with AST
    for file_path, source in code.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name
                    kind, target_id = classify_module_kind(mod_name, code_keys)
                    target_node = target_id or mod_name

                    G.add_node(target_node, kind=kind)
                    G.add_edge(file_path, target_node, names=[alias.name], broken=False)

                    edges.append({
                        "from": file_path,
                        "to": target_node,
                        "names": [alias.name],
                        "broken": False,
                    })

            elif isinstance(node, ast.ImportFrom):
                resolved_mod = resolve_relative_module(file_path, node.module, node.level)
                if not resolved_mod:
                    continue

                kind, target_id = classify_module_kind(resolved_mod, code_keys)
                target_node = target_id or resolved_mod

                imported_names = [alias.name for alias in node.names]
                is_broken = False

                # 3. Symbol-level check for local modules
                if kind == "local":
                    target_file = target_id or find_local_target(resolved_mod, code_keys)
                    if target_file and target_file in target_symbols_cache:
                        available_symbols = target_symbols_cache[target_file]
                        for imp_name in imported_names:
                            if imp_name != "*" and imp_name not in available_symbols:
                                is_broken = True
                                broken_links.append({
                                    "file": file_path,
                                    "imported_name": imp_name,
                                    "target": target_file,
                                    "reason": f"Symbol '{imp_name}' is not defined in '{target_file}'",
                                })

                G.add_node(target_node, kind=kind)
                G.add_edge(file_path, target_node, names=imported_names, broken=is_broken)

                edges.append({
                    "from": file_path,
                    "to": target_node,
                    "names": imported_names,
                    "broken": is_broken,
                })

    # 4. Run pyflakes on every file
    lint_issues = run_pyflakes_lint(code)

    # 5. NetworkX graph analysis:
    # Blast radius = all ancestors (files that depend on) of every changed file
    blast_radius_nodes: Set[str] = set()
    norm_changed = {cf.replace("\\", "/").lstrip("./") for cf in changed_files}

    for cf in changed_files:
        norm_cf = cf.replace("\\", "/").lstrip("./")
        matching_nodes = [
            n for n in G.nodes
            if n.replace("\\", "/").lstrip("./") == norm_cf or Path(n).name == Path(cf).name
        ]
        for mn in matching_nodes:
            blast_radius_nodes.update(nx.ancestors(G, mn))

    # Cycles over local nodes only
    local_nodes = [n for n, d in G.nodes(data=True) if d.get("kind") == "local"]
    local_subgraph = G.subgraph(local_nodes)
    cycles = list(nx.simple_cycles(local_subgraph))

    # 6. Prepare output nodes structure
    nodes_list: List[Dict[str, Any]] = []
    for node_id, data in G.nodes(data=True):
        norm_id = node_id.replace("\\", "/").lstrip("./")
        is_changed = any(norm_id == nc or Path(node_id).name == Path(nc).name for nc in norm_changed)
        is_blast = node_id in blast_radius_nodes

        nodes_list.append({
            "id": node_id,
            "kind": data.get("kind", "local"),
            "changed": is_changed,
            "blast_radius": is_blast,
        })

    dep_graph = {
        "nodes": nodes_list,
        "edges": edges,
        "broken_links": broken_links,
        "cycles": cycles,
    }

    return dep_graph, G, lint_issues


# ---------------------------------------------------------------------------
# Self-Test Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_dir = Path(__file__).parent / "sample" / "repo"

    receipt_file = sample_dir / "receipt.py"
    utils_file = sample_dir / "utils.py"
    checkout_file = sample_dir / "checkout.py"

    test_code = {
        "receipt.py": receipt_file.read_text(encoding="utf-8"),
        "utils.py": utils_file.read_text(encoding="utf-8"),
        "checkout.py": checkout_file.read_text(encoding="utf-8"),
    }
    test_changed = ["utils.py"]

    print("=== Running Deterministic Dependency Graph Analysis (dep_graph.py) ===")
    dep_graph_result, nx_graph, lints = build_dependency_graph(test_code, test_changed)

    print("\n[Nodes]:")
    for n in dep_graph_result["nodes"]:
        print(f" - {n['id']} (kind={n['kind']}, changed={n['changed']}, blast_radius={n['blast_radius']})")

    print("\n[Edges]:")
    for e in dep_graph_result["edges"]:
        print(f" - {e['from']} -> {e['to']} (names={e['names']}, broken={e['broken']})")

    print("\n[Broken Links]:")
    for b in dep_graph_result["broken_links"]:
        print(f" - {b['file']} imports '{b['imported_name']}' from '{b['target']}': {b['reason']}")

    print("\n[Cycles]:", dep_graph_result["cycles"])
    print("\n[Pyflakes Lint Issues]:", len(lints), "found")

    # Required Self-Test Assertions
    # 1. Assert receipt.py -> round_money is reported as a broken link
    has_broken_round_money = any(
        b["file"].endswith("receipt.py") and b["imported_name"] == "round_money"
        for b in dep_graph_result["broken_links"]
    )
    assert has_broken_round_money, "Self-test failed: receipt.py -> round_money not reported as broken link!"

    # 2. Assert fastmath is marked as 'missing'
    has_missing_fastmath = any(
        n["id"] == "fastmath" and n["kind"] == "missing"
        for n in dep_graph_result["nodes"]
    )
    assert has_missing_fastmath, "Self-test failed: fastmath not marked as 'missing'!"

    print("\n✅ All self-test assertions PASSED successfully!")
