import ast
import concurrent.futures
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from llm import ask_json
from dep_graph import build_dependency_graph


# ---------------------------------------------------------------------------
# 1. State Definition
# ---------------------------------------------------------------------------
class S(TypedDict, total=False):
    requirement: str
    code: Any  # str or Dict[str, str] (path -> source)
    changed_files: List[str]
    feedback: str
    plan: dict
    static_findings: dict
    dep_graph: dict
    lint_issues: list
    gaps: list
    fixes: dict
    validation: dict
    retries: int
    approved: bool
    final_code: str


def ensure_code_dict(code_input: Any) -> Dict[str, str]:
    """Ensures code input is formatted as a path -> source dictionary."""
    if isinstance(code_input, dict):
        return code_input
    if isinstance(code_input, str):
        return {"code.py": code_input}
    return {}


def get_code_str(code_input: Any) -> str:
    """Combines all files in code_input into a readable string for LLM prompts."""
    if isinstance(code_input, dict):
        return "\n\n".join([f"# --- File: {path} ---\n{src}" for path, src in code_input.items()])
    return str(code_input)


# ---------------------------------------------------------------------------
# 2. Orchestrator Node
# ---------------------------------------------------------------------------
def orchestrator(state: S) -> dict:
    """
    Orchestrator node:
    Takes requirement and code from state (already text),
    resets retries to 0, and preserves feedback if it exists
    so later nodes can utilize it.
    """
    print(" -> [orchestrator] Initializing/resetting retries and preserving feedback...", flush=True)
    requirement = state.get("requirement", "")
    code = state.get("code", "")
    changed_files = state.get("changed_files", [])
    feedback = state.get("feedback")

    updates: dict = {
        "requirement": requirement,
        "code": code,
        "changed_files": changed_files,
        "retries": 0,
    }

    if feedback:
        updates["feedback"] = feedback

    return updates


# ---------------------------------------------------------------------------
# 3. Planner Node
# ---------------------------------------------------------------------------
def planner(state: S) -> dict:
    """
    Planner node:
    Makes one LLM call using ask_json from llm.py.
    Given requirement and code, returns a JSON plan like:
    {"checks": ["dependencies", "names", "edge_cases", "missing_tests", "requirement_match"], "focus": "..."}
    and stores it in state["plan"].
    """
    print(" -> [planner] Decomposing tasks and determining inspection focus...", flush=True)
    requirement = state.get("requirement", "")
    code_text = get_code_str(state.get("code", ""))
    feedback = state.get("feedback", "")

    feedback_prompt = f"\n[Previous Human Feedback]\n{feedback}\n" if feedback else ""

    prompt = f"""You are a Software Quality Planning Agent in an automated code review and repair pipeline.
Given the requirement specification and the implementation code, analyze what inspection checks are needed and identify the primary focus.

[Requirement Specification]
{requirement}

[Implementation Code]
{code_text}
{feedback_prompt}
Return a valid JSON object strictly matching this format:
{{
    "checks": ["dependencies", "names", "edge_cases", "missing_tests", "requirement_match"],
    "focus": "one sentence on what matters most"
}}
"""
    plan = ask_json(prompt, max_tokens=350)
    return {"plan": plan}


# ---------------------------------------------------------------------------
# 4. Static Agent Node (Non-LLM AST Dep Graph + pyflakes + LLM Inspection)
# ---------------------------------------------------------------------------
def static_agent(state: S) -> dict:
    """
    Static Agent node:
    - Part A: Non-LLM AST dependency graph and pyflakes lint check (dep_graph.py).
      Detects missing dependencies, unused imports, broken symbol imports, and cycles.
    - Part B: LLM static check for naming, edge cases, missing tests, and values/validations.
    Feeds broken_links, lint_issues, and dependencies into state["static_findings"],
    and stores dep_graph in state["dep_graph"] and lint_issues in state["lint_issues"].
    """
    print(" -> [static_agent] Running deterministic AST dependency graph & static LLM review...", flush=True)
    requirement = state.get("requirement", "")
    code_dict = ensure_code_dict(state.get("code", ""))
    changed_files = state.get("changed_files", list(code_dict.keys()))

    # Deterministic dependency graph & pyflakes
    dep_graph_data, G, lint_issues = build_dependency_graph(code_dict, changed_files)

    missing_deps = [n["id"] for n in dep_graph_data.get("nodes", []) if n.get("kind") == "missing"]
    broken_links = dep_graph_data.get("broken_links", [])

    code_text = get_code_str(code_dict)

    prompt = f"""You are an Expert Static Code and Defect Analysis Specialist.
Examine the following code against the requirement specification.

[Requirement Specification]
{requirement}

[Implementation Code]
{code_text}

[Deterministic Dependency & Lint Findings]
- Missing Dependencies: {missing_deps}
- Broken Imported Symbols: {json.dumps(broken_links, indent=2)}
- Pyflakes Lint Issues: {json.dumps(lint_issues, indent=2)}

Identify naming defects, edge cases, missing test scenarios, and value/range validation issues.
Return a valid JSON object strictly matching this schema:
{{
    "naming_issues": ["list of strings describing bad, ambiguous, or non-compliant names"],
    "edge_cases": ["list of strings, unhandled edge cases relative to the requirement"],
    "missing_tests": ["list of strings, test scenarios that should exist"],
    "values_issues": ["list of strings, wrong or missing validations and constants"]
}}
"""
    llm_findings = ask_json(prompt, max_tokens=450)
    if not isinstance(llm_findings, dict):
        llm_findings = {}

    static_findings = {
        "dependencies": {
            "all_imports": [e["to"] for e in dep_graph_data.get("edges", [])],
            "missing_dependencies": missing_deps,
            "broken_links": broken_links,
            "cycles": dep_graph_data.get("cycles", []),
        },
        "lint_issues": lint_issues,
        "broken_links": broken_links,
        "naming_issues": llm_findings.get("naming_issues", []),
        "edge_cases": llm_findings.get("edge_cases", []),
        "missing_tests": llm_findings.get("missing_tests", []),
        "values_issues": llm_findings.get("values_issues", []),
    }

    return {
        "static_findings": static_findings,
        "dep_graph": dep_graph_data,
        "lint_issues": lint_issues,
    }


# ---------------------------------------------------------------------------
# 5. CRAG Agent Node (Corrective RAG: Retrieve, Grade, Correct)
# ---------------------------------------------------------------------------
def chunk_code_by_ast(code: str) -> List[str]:
    """Splits code into chunks by function or class using AST, falling back to line chunks."""
    chunks = []
    try:
        tree = ast.parse(code)
        lines = code.splitlines()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                chunks.append("\n".join(lines[start:end]))
        if not chunks:
            chunks = [code]
    except Exception:
        lines = code.splitlines()
        chunk_size = 15
        chunks = ["\n".join(lines[i:i + chunk_size]) for i in range(0, len(lines), chunk_size)]
    return chunks or [code]


def keyword_overlap_score(point: str, chunk: str) -> int:
    """Calculates keyword overlap score between requirement point and code chunk."""
    point_words = set(re.findall(r"\w+", point.lower()))
    chunk_words = set(re.findall(r"\w+", chunk.lower()))
    stop_words = {
        "the", "a", "an", "is", "of", "and", "or", "in", "to", "for",
        "with", "on", "at", "by", "from", "be", "this", "that", "it"
    }
    meaningful_words = point_words - stop_words
    return len(meaningful_words.intersection(chunk_words))


def crag_agent(state: S) -> dict:
    """
    CRAG Agent node (Corrective RAG):
    1. Splits requirement into individual points via ask_json.
    2. Chunks code by function/class using AST.
    3. Retrieves top 2 relevant chunks via keyword overlap.
    4. Grades retrieved chunks: satisfied, partial, contradicts, or missing.
    5. Corrective step: if missing or retrieval looked irrelevant, retries once with full code.
    6. Saves graded points into state["gaps"].
    """
    print(" -> [crag_agent] Running Corrective RAG (Retrieve, Grade, Correct)...", flush=True)
    requirement = state.get("requirement", "")
    code_text = get_code_str(state.get("code", ""))

    # Step 1: Split requirement into distinct points
    split_prompt = f"""Extract up to 3 to 4 core requirement criteria from this specification.

[Requirement Specification]
{requirement}

Return a valid JSON object strictly matching this schema:
{{
    "points": ["Short description of criteria 1", "Short description of criteria 2", "Short description of criteria 3"]
}}
"""
    split_res = ask_json(split_prompt, max_tokens=250)
    points = split_res.get("points", []) if isinstance(split_res, dict) else [requirement]
    if not points:
        points = [requirement]

    # Step 2: Chunk code
    chunks = chunk_code_by_ast(code_text)

    def grade_single_point(point: str) -> dict:
        # Step 3: Keyword overlap retrieval (top 2 chunks)
        scored_chunks = sorted(chunks, key=lambda c: keyword_overlap_score(point, c), reverse=True)
        top_chunks = scored_chunks[:2]
        retrieved_snippet = "\n---\n".join(top_chunks)

        # Step 4: Grade retrieved chunks
        grade_prompt = f"""You are a Corrective RAG (CRAG) Spec Grading Agent.
Grade whether the retrieved code chunk(s) satisfy the given requirement point.

[Requirement Point]
{point}

[Retrieved Code Chunk(s)]
{retrieved_snippet}

Return a valid JSON object strictly matching:
{{
    "status": "satisfied" | "partial" | "contradicts" | "missing",
    "evidence": "short quote or line reference",
    "reason": "one sentence"
}}
"""
        grade = ask_json(grade_prompt, max_tokens=250)
        if not isinstance(grade, dict):
            grade = {"status": "missing", "evidence": "", "reason": "Failed to parse grade"}

        # Step 5: Correction step if status is missing or retrieval looked irrelevant
        if grade.get("status") == "missing" or keyword_overlap_score(point, retrieved_snippet) == 0:
            correction_prompt = f"""[Corrective RAG Step: Full Code Evaluation]
The initial code chunk retrieval was inconclusive or marked missing.
Evaluate the requirement point against the ENTIRE implementation code.

[Requirement Point]
{point}

[Full Implementation Code]
{code_text}

Return a valid JSON object strictly matching:
{{
    "status": "satisfied" | "partial" | "contradicts" | "missing",
    "evidence": "short quote or line reference from code",
    "reason": "one sentence"
}}
"""
            corrected_grade = ask_json(correction_prompt, max_tokens=250)
            if isinstance(corrected_grade, dict):
                grade = corrected_grade

        return {
            "point": point,
            "status": grade.get("status", "missing"),
            "evidence": grade.get("evidence", ""),
            "reason": grade.get("reason", ""),
        }

    # Grade points concurrently with ThreadPoolExecutor
    gaps = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(points))) as executor:
        futures = [executor.submit(grade_single_point, pt) for pt in points]
        for f in concurrent.futures.as_completed(futures):
            gaps.append(f.result())

    return {"gaps": gaps}


# ---------------------------------------------------------------------------
# 6. Generator Node
# ---------------------------------------------------------------------------
def generator(state: S) -> dict:
    """
    Generator node:
    Receives requirement, code, static_findings, gaps, human feedback,
    and critic validation complaints from previous attempts.
    Produces suggested_changes, patched_code, and new_tests.
    Stores in state["fixes"] and increments state["retries"] by 1.
    """
    print(" -> [generator] Synthesizing suggested changes, patched code, and unit tests...", flush=True)
    requirement = state.get("requirement", "")
    code_text = get_code_str(state.get("code", ""))
    static_findings = state.get("static_findings", {})
    gaps = state.get("gaps", [])
    feedback = state.get("feedback", "")
    validation = state.get("validation", {})
    current_retries = state.get("retries", 0)

    feedback_sec = f"\n[Human Rejection Feedback]\n{feedback}\n" if feedback else ""
    critic_sec = ""
    if validation and not validation.get("all_passed", True):
        critic_sec = f"\n[Critic Complaints from Previous Attempt]\n{json.dumps(validation.get('critics', {}), indent=2)}\n"

    prompt = f"""You are an Expert Automated Code Repair & Generation Agent.
Generate a complete, production-ready fix for the implementation code based on the specification requirements, static analysis findings (including broken links and lint issues), spec gaps, human feedback, and critic complaints.

[Requirement Specification]
{requirement}

[Original Implementation Code]
{code_text}

[Static Analysis Findings (Including Broken Links & Pyflakes Lints)]
{json.dumps(static_findings, indent=2)}

[Specification Gaps (CRAG Analysis)]
{json.dumps(gaps, indent=2)}
{feedback_sec}{critic_sec}

Provide the complete patched code and accompanying test suite.
Return a valid JSON object matching this schema:
{{
    "suggested_changes": [
        {{"issue": "Brief description of issue", "change": "Description of resolution"}}
    ],
    "patched_code": "Full corrected, production-ready implementation code as a string",
    "new_tests": "A complete python string with pytest test functions covering all missing scenarios, edge cases, and validations"
}}
"""
    fixes = ask_json(prompt, max_tokens=750)
    if not isinstance(fixes, dict):
        fixes = {
            "suggested_changes": [],
            "patched_code": code_text,
            "new_tests": "# No tests generated",
        }

    return {
        "fixes": fixes,
        "retries": current_retries + 1,
    }


# ---------------------------------------------------------------------------
# 7. Validate Node (4 Critic LLMs in Parallel + Syntax Check)
# ---------------------------------------------------------------------------
def validate(state: S) -> dict:
    """
    Validate node:
    Runs four critic prompts in parallel using ThreadPoolExecutor:
    1. dependencies critic
    2. names critic
    3. cases critic
    4. values critic
    Additionally runs a non-LLM ast.parse sanity check on patched_code.
    Stores all verdicts in state["validation"] as {"critics": {...}, "all_passed": bool}.
    """
    print(" -> [validate] Running 4 Critic LLMs in parallel + AST syntax check...", flush=True)
    requirement = state.get("requirement", "")
    static_findings = state.get("static_findings", {})
    gaps = state.get("gaps", [])
    fixes = state.get("fixes", {})
    patched_code = fixes.get("patched_code", "")
    new_tests = fixes.get("new_tests", "")

    # Non-LLM sanity check: compile patched code with ast.parse
    syntax_pass = True
    syntax_reason = "Code successfully parsed via ast.parse without syntax errors."
    try:
        ast.parse(patched_code)
    except SyntaxError as e:
        syntax_pass = False
        syntax_reason = f"Syntax error at line {e.lineno}: {e.msg}"

    shared_context = f"""
[Requirement Specification]
{requirement}

[Static Analysis Findings (Including Broken Links & Pyflakes Lints)]
{json.dumps(static_findings, indent=2)}

[Spec Gaps]
{json.dumps(gaps, indent=2)}

[Patched Code Under Review]
{patched_code}

[Generated Unit Tests Under Review]
{new_tests}
"""

    critic_questions = {
        "dependencies": (
            "You are the Dependencies Critic. Does the patched code import only available modules, "
            "with NO uninstalled/missing external packages, NO broken symbol imports, and NO unused imports?"
        ),
        "names": (
            "You are the Naming and API Consistency Critic. Are function, variable, and test names "
            "clear, consistent, and compliant with standard conventions and the specification?"
        ),
        "cases": (
            "You are the Test Cases & Coverage Critic. Do the new tests and the patched code thoroughly "
            "cover the edge cases and missing test scenarios that were identified in the findings and gaps?"
        ),
        "values": (
            "You are the Validations, Ranges & Constants Critic. Are all validations, ranges, percentages, "
            "calculations, and constants correct per the requirement specification?"
        ),
    }

    def evaluate_critic(name: str, question: str) -> tuple[str, dict]:
        critic_prompt = f"""{question}

{shared_context}

Return a valid JSON object strictly matching:
{{
    "pass": boolean,
    "reason": "Clear explanation of verdict"
}}
"""
        verdict = ask_json(critic_prompt, max_tokens=250)
        if not isinstance(verdict, dict):
            verdict = {"pass": False, "reason": str(verdict)}
        return name, verdict

    critics_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(evaluate_critic, name, q): name
            for name, q in critic_questions.items()
        }
        for future in concurrent.futures.as_completed(futures):
            c_name, res = future.result()
            critics_results[c_name] = res

    # Include syntax check in critics results
    critics_results["syntax"] = {"pass": syntax_pass, "reason": syntax_reason}

    all_passed = syntax_pass and all(c.get("pass", False) for c in critics_results.values())

    validation_state = {
        "critics": critics_results,
        "all_passed": all_passed,
    }

    return {"validation": validation_state}


def route_validation(state: S) -> str:
    """
    Routing function:
    If all_passed is False and retries < 2, return 'retry' (back to generator).
    Otherwise return 'ok' (proceed to human approval).
    """
    validation = state.get("validation", {})
    all_passed = validation.get("all_passed", False)
    retries = state.get("retries", 0)

    if not all_passed and retries < 2:
        print(f" -> [route_validation] Critics flagged issues and retries={retries} < 2. Returning 'retry'...", flush=True)
        return "retry"
    print(" -> [route_validation] Validation passed or retry ceiling reached. Returning 'ok'...", flush=True)
    return "ok"


# ---------------------------------------------------------------------------
# 8. Human Approval & Finalize Nodes
# ---------------------------------------------------------------------------
def approval(state: S) -> dict:
    """
    Pass-through node representing the human review gate.
    The graph pauses before this node via interrupt_before.
    """
    print(" -> [approval] Human review gate reached.", flush=True)
    return {}


def finalize(state: S) -> dict:
    """
    Finalize node:
    Sets state["final_code"] = state["fixes"]["patched_code"].
    """
    print(" -> [finalize] Exporting verified final_code...", flush=True)
    fixes = state.get("fixes", {})
    return {"final_code": fixes.get("patched_code", "")}


def route_approval(state: S) -> str:
    """
    Routing function from human approval:
    If state["approved"] is True return 'yes' (to finalize),
    otherwise return 'no' (back to orchestrator with feedback).
    """
    if state.get("approved") is True:
        return "yes"
    return "no"


# ---------------------------------------------------------------------------
# 9. Pipeline Assembly & Graph Builder
# ---------------------------------------------------------------------------
def build_app():
    """
    Constructs and compiles the full Software Quality Intelligence LangGraph pipeline:
    - orchestrator -> planner
    - planner branches in parallel to static_agent and crag_agent
    - static_agent & crag_agent fan-in to generator
    - generator -> validate
    - validate routes conditionally: 'retry' -> generator, 'ok' -> approval
    - approval routes conditionally: 'yes' -> finalize, 'no' -> orchestrator
    - finalize -> END

    Compiled with MemorySaver checkpointer and interrupt_before=['approval'].
    """
    builder = StateGraph(S)

    # Register nodes
    builder.add_node("orchestrator", orchestrator)
    builder.add_node("planner", planner)
    builder.add_node("static_agent", static_agent)
    builder.add_node("crag_agent", crag_agent)
    builder.add_node("generator", generator)
    builder.add_node("validate", validate)
    builder.add_node("approval", approval)
    builder.add_node("finalize", finalize)

    # Entry point
    builder.set_entry_point("orchestrator")

    # Sequential edge: orchestrator -> planner
    builder.add_edge("orchestrator", "planner")

    # Parallel execution: planner -> static_agent & crag_agent
    builder.add_edge("planner", "static_agent")
    builder.add_edge("planner", "crag_agent")

    # Fan-in: both agents write to their own keys and feed into generator
    builder.add_edge("static_agent", "generator")
    builder.add_edge("crag_agent", "generator")

    builder.add_edge("generator", "validate")

    # Critic validation conditional routing
    builder.add_conditional_edges(
        "validate",
        route_validation,
        {
            "retry": "generator",
            "ok": "approval",
        },
    )

    # Human approval conditional routing
    builder.add_conditional_edges(
        "approval",
        route_approval,
        {
            "yes": "finalize",
            "no": "orchestrator",
        },
    )

    builder.add_edge("finalize", END)

    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer, interrupt_before=["approval"])


def build_graph():
    """Alias for build_app() for backward compatibility."""
    return build_app()


def get_dependency_graph_mermaid() -> str:
    """Returns the Mermaid syntax representation of the pipeline architecture."""
    return """flowchart TD
    orchestrator["1. orchestrator (Entry / Reset retries)"] --> planner["2. planner (Task Decomposition)"]
    planner --> static_agent["3a. static_agent (AST & Dependency Check)"]
    planner --> crag_agent["3b. crag_agent (Corrective RAG Gaps)"]
    static_agent --> generator["4. generator (Code Repair & Tests)"]
    crag_agent --> generator
    generator --> validate["5. validate (4 Critic LLMs + Syntax)"]
    validate -->|retry (all_passed=False & retries < 2)| generator
    validate -->|ok (all_passed=True or retries >= 2)| approval["6. approval (Human Gate Interrupt)"]
    approval -->|yes (approved=True)| finalize["7. finalize (Export Final Code)"]
    approval -->|no (feedback)| orchestrator
    finalize --> END([END])
"""


# ---------------------------------------------------------------------------
# 10. Standalone Execution / Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_dir = Path(__file__).parent / "sample" / "repo"

    receipt_file = sample_dir / "receipt.py"
    utils_file = sample_dir / "utils.py"
    checkout_file = sample_dir / "checkout.py"

    test_code = {
        "receipt.py": receipt_file.read_text(encoding="utf-8") if receipt_file.exists() else "",
        "utils.py": utils_file.read_text(encoding="utf-8") if utils_file.exists() else "",
        "checkout.py": checkout_file.read_text(encoding="utf-8") if checkout_file.exists() else "",
    }
    test_changed = ["utils.py"]

    req_file = Path(__file__).parent / "sample" / "requirement.txt"
    requirement_content = req_file.read_text(encoding="utf-8") if req_file.exists() else "Checkout and receipt requirements"

    print("=================================================================")
    print("AI-POWERED SOFTWARE QUALITY INTELLIGENCE PIPELINE")
    print("Target: Multi-file PR Codebase with Dependency Graph & Linting")
    print("=================================================================\n")

    print("--- Initializing StateGraph Pipeline with Checkpointer & Human Interrupt ---", flush=True)
    app = build_app()

    initial_input: S = {
        "requirement": requirement_content,
        "code": test_code,
        "changed_files": test_changed,
    }

    thread_config = {"configurable": {"thread_id": "pr-review-session-multidoc"}}

    print("--- Executing Pipeline through Planner -> Parallel Agents -> Generator -> Validate ---", flush=True)
    state_after_run = app.invoke(initial_input, config=thread_config)

    current_checkpoint = app.get_state(thread_config)
    values = current_checkpoint.values

    print("\n[1] --- PLAN (state['plan']) ---", flush=True)
    print(json.dumps(values.get("plan"), indent=2), flush=True)

    print("\n[2] --- STATIC FINDINGS (state['static_findings']) ---", flush=True)
    print(json.dumps(values.get("static_findings"), indent=2), flush=True)

    print("\n[3] --- GAPS FROM CRAG AGENT (state['gaps']) ---", flush=True)
    print(json.dumps(values.get("gaps"), indent=2), flush=True)

    print("\n[4] --- GENERATED FIXES (state['fixes']['suggested_changes']) ---", flush=True)
    fixes = values.get("fixes", {})
    print(json.dumps(fixes.get("suggested_changes", []), indent=2), flush=True)

    print("\n[5] --- VALIDATION VERDICTS (state['validation']) ---", flush=True)
    print(json.dumps(values.get("validation"), indent=2), flush=True)

    print(f"\n[6] --- GRAPH PAUSE STATUS ---", flush=True)
    print(f"Next Node in Execution Queue: {current_checkpoint.next}", flush=True)
    print(f"Retries Elapsed: {values.get('retries', 0)}", flush=True)
    print("Graph has paused before 'approval' for human-in-the-loop review.", flush=True)
