import re
from typing import Any, Dict, List, Optional, Set


def sanitize_mermaid_id(name: str) -> str:
    """Sanitizes an arbitrary file or module path into a safe Mermaid node ID."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if not safe or safe[0].isdigit():
        safe = f"n_{safe}"
    return safe


def to_dot(dep_graph: Dict[str, Any], show_stdlib: bool = False) -> str:
    """
    Renders dep_graph into Graphviz DOT syntax with rankdir=LR.
    Styling:
    - local = blue fill (#E1F5FE)
    - external = gray fill (#EEEEEE)
    - stdlib = light gray (#FAFAFA, hidden if show_stdlib=False)
    - missing = red fill (#FFEBEE)
    - blast_radius = orange fill (#FFE0B2)
    - changed = thick border (penwidth=3.0)
    - broken edges = red dashed with imported name label (#D32F2F)
    """
    lines = [
        "digraph DependencyGraph {",
        "    rankdir=LR;",
        '    node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11, margin="0.2,0.1"];',
        '    edge [fontname="Helvetica", fontsize=9, color="#757575"];',
        "",
    ]

    hidden_nodes: Set[str] = set()
    if not show_stdlib:
        for node in dep_graph.get("nodes", []):
            if node.get("kind") == "stdlib":
                hidden_nodes.add(node["id"])

    # Render Nodes
    lines.append("    // Nodes")
    for node in dep_graph.get("nodes", []):
        node_id = node["id"]
        if node_id in hidden_nodes:
            continue

        kind = node.get("kind", "local")
        is_changed = node.get("changed", False)
        is_blast = node.get("blast_radius", False)

        # Base color attributes
        if kind == "missing":
            fillcolor = "#FFCDD2"  # Red
            color = "#C62828"
            fontcolor = "#B71C1C"
        elif is_blast:
            fillcolor = "#FFE0B2"  # Orange (blast radius)
            color = "#E65100"
            fontcolor = "#BF360C"
        elif kind == "local":
            fillcolor = "#E1F5FE"  # Blue (local)
            color = "#0288D1"
            fontcolor = "#01579B"
        elif kind == "stdlib":
            fillcolor = "#F5F5F5"  # Light gray (stdlib)
            color = "#BDBDBD"
            fontcolor = "#616161"
        else:  # external
            fillcolor = "#E0E0E0"  # Gray (external)
            color = "#757575"
            fontcolor = "#424242"

        # Thick border for changed files
        penwidth = "3.0" if is_changed else "1.2"
        if is_changed:
            color = "#0D47A1"  # Emphasize changed files with dark blue border

        label_parts = [node_id]
        flags = []
        if is_changed:
            flags.append("CHANGED")
        if is_blast:
            flags.append("BLAST RADIUS")
        if kind == "missing":
            flags.append("MISSING")
        if flags:
            label_parts.append(f"[{', '.join(flags)}]")

        label_str = "\\n".join(label_parts)
        lines.append(
            f'    "{node_id}" [label="{label_str}", fillcolor="{fillcolor}", color="{color}", '
            f'penwidth={penwidth}, fontcolor="{fontcolor}"];'
        )

    lines.append("")
    lines.append("    // Edges")

    # Render Edges
    for edge in dep_graph.get("edges", []):
        src = edge["from"]
        dst = edge["to"]

        if src in hidden_nodes or dst in hidden_nodes:
            continue

        is_broken = edge.get("broken", False)
        names = edge.get("names", [])
        names_str = ", ".join(names) if isinstance(names, list) else str(names)

        if is_broken:
            # Red dashed with label
            lines.append(
                f'    "{src}" -> "{dst}" [color="#D32F2F", fontcolor="#D32F2F", style="dashed", '
                f'penwidth=2.0, label="{names_str} (BROKEN)"];'
            )
        else:
            label_attr = f', label="{names_str}"' if names_str and names_str != dst else ""
            lines.append(f'    "{src}" -> "{dst}" [color="#616161"{label_attr}];')

    lines.append("}")
    return "\n".join(lines)


def to_mermaid(dep_graph: Dict[str, Any], show_stdlib: bool = False) -> str:
    """
    Renders dep_graph into GitHub-compatible Mermaid flowchart syntax with classDef styles.
    """
    lines = [
        "flowchart LR",
        "    classDef local fill:#e1f5fe,stroke:#0288d1,stroke-width:1px;",
        "    classDef external fill:#eeeeee,stroke:#757575,stroke-width:1px;",
        "    classDef stdlib fill:#fafafa,stroke:#bdbdbd,stroke-width:1px;",
        "    classDef missing fill:#ffcdd2,stroke:#c62828,stroke-width:2px,color:#b71c1c;",
        "    classDef blast fill:#ffe0b2,stroke:#e65100,stroke-width:2px,color:#bf360c;",
        "    classDef changed stroke-width:3px,stroke:#0d47a1;",
        "",
    ]

    hidden_nodes: Set[str] = set()
    if not show_stdlib:
        for node in dep_graph.get("nodes", []):
            if node.get("kind") == "stdlib":
                hidden_nodes.add(node["id"])

    # Render Nodes
    node_id_map: Dict[str, str] = {}
    for node in dep_graph.get("nodes", []):
        raw_id = node["id"]
        if raw_id in hidden_nodes:
            continue

        m_id = sanitize_mermaid_id(raw_id)
        node_id_map[raw_id] = m_id

        kind = node.get("kind", "local")
        is_changed = node.get("changed", False)
        is_blast = node.get("blast_radius", False)

        label = raw_id
        if is_changed:
            label += " (CHANGED)"
        elif is_blast:
            label += " (BLAST RADIUS)"

        lines.append(f'    {m_id}["{label}"]')

        # Apply classes
        if kind == "missing":
            lines.append(f"    class {m_id} missing;")
        elif is_blast:
            lines.append(f"    class {m_id} blast;")
        elif kind == "local":
            lines.append(f"    class {m_id} local;")
        elif kind == "stdlib":
            lines.append(f"    class {m_id} stdlib;")
        else:
            lines.append(f"    class {m_id} external;")

        if is_changed:
            lines.append(f"    class {m_id} changed;")

    lines.append("")

    # Render Edges
    for edge in dep_graph.get("edges", []):
        src = edge["from"]
        dst = edge["to"]

        if src in hidden_nodes or dst in hidden_nodes:
            continue

        src_id = node_id_map.get(src, sanitize_mermaid_id(src))
        dst_id = node_id_map.get(dst, sanitize_mermaid_id(dst))

        is_broken = edge.get("broken", False)
        names = edge.get("names", [])
        names_str = ", ".join(names) if isinstance(names, list) else str(names)

        if is_broken:
            lines.append(f'    {src_id} -. "{names_str} [BROKEN]" .-> {dst_id}')
        else:
            if names_str and names_str != dst:
                lines.append(f'    {src_id} -- "{names_str}" --> {dst_id}')
            else:
                lines.append(f"    {src_id} --> {dst_id}")

    return "\n".join(lines)
