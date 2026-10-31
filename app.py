import json
import os
from pathlib import Path
import uuid
import streamlit as st
from dotenv import load_dotenv

from graph import build_app, S, get_dependency_graph_mermaid
from dep_graph import build_dependency_graph
from graph_viz import to_dot, to_mermaid
from pr_loader import load_pr, parse_pr_url

# Load environment variables
load_dotenv()

# Streamlit Page Config
st.set_page_config(
    page_title="AI Software Quality Intelligence System",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .legend-box {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        padding: 10px 14px;
        background-color: #f8f9fa;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        margin-bottom: 15px;
        font-size: 13px;
    }
    .legend-item { display: flex; align-items: center; gap: 6px; }
    .color-swatch {
        width: 14px;
        height: 14px;
        border-radius: 3px;
        display: inline-block;
        border: 1px solid #999;
    }
    .check-pill {
        display: inline-block;
        background-color: #f0f2f6;
        color: #31333f;
        padding: 3px 10px;
        border-radius: 14px;
        margin: 3px;
        font-size: 12px;
        font-weight: 500;
        border: 1px solid #dcdfe6;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SAMPLE_DIR = Path(__file__).parent / "sample"


def load_sample_repo_files() -> tuple[dict, list, str]:
    sample_repo = SAMPLE_DIR / "repo"
    code = {}
    if sample_repo.exists():
        for p in sample_repo.glob("*.py"):
            code[p.name] = p.read_text(encoding="utf-8")
    changed = ["utils.py"] if "utils.py" in code else list(code.keys())
    req_file = SAMPLE_DIR / "requirement.txt"
    req_text = req_file.read_text(encoding="utf-8") if req_file.exists() else "Sample requirement specification"
    return code, changed, req_text


# Session state initialization
if "pr_url" not in st.session_state:
    st.session_state["pr_url"] = "https://github.com/vvkmj/myco-prd-demo/pull/3"

if "pr_code" not in st.session_state or "pr_req" not in st.session_state:
    sample_code, sample_changed, sample_req = load_sample_repo_files()
    st.session_state["pr_code"] = sample_code
    st.session_state["pr_changed"] = sample_changed
    st.session_state["pr_req"] = sample_req

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = f"session_{uuid.uuid4().hex[:8]}"

if "app_instance" not in st.session_state:
    st.session_state["app_instance"] = build_app()

if "pipeline_results" not in st.session_state:
    st.session_state["pipeline_results"] = None

# Sidebar Configuration
with st.sidebar:
    st.header("🔗 Pull Request Integration")
    st.caption("Inspect any GitHub Pull Request URL without requiring webhooks.")

    pr_input = st.text_input(
        "GitHub PR URL",
        value=st.session_state["pr_url"],
        help="Paste any GitHub PR link, e.g. https://github.com/owner/repo/pull/123",
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Load PR (Cache)", use_container_width=True):
            try:
                with st.spinner("Loading PR from local cache..."):
                    pr_data = load_pr(pr_input, force_refresh=False)
                    st.session_state["pr_url"] = pr_input
                    if pr_data.get("code"):
                        st.session_state["pr_code"] = pr_data["code"]
                        st.session_state["pr_changed"] = pr_data.get("changed_files", list(pr_data["code"].keys()))
                        st.session_state["pr_req"] = pr_data.get("requirement", "")
                    st.session_state["pipeline_results"] = None
                    st.session_state["thread_id"] = f"session_{uuid.uuid4().hex[:8]}"
                    is_c = "from Cache" if pr_data.get("is_cached") else "from GitHub"
                    st.success(f"Loaded PR #{pr_data.get('pull_number')} ({is_c})!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error loading PR: {e}")

    with col_btn2:
        if st.button("🔄 Fetch Fresh", use_container_width=True):
            try:
                with st.spinner("Fetching live PR from GitHub API..."):
                    pr_data = load_pr(pr_input, force_refresh=True)
                    st.session_state["pr_url"] = pr_input
                    if pr_data.get("code"):
                        st.session_state["pr_code"] = pr_data["code"]
                        st.session_state["pr_changed"] = pr_data.get("changed_files", list(pr_data["code"].keys()))
                        st.session_state["pr_req"] = pr_data.get("requirement", "")
                    st.session_state["pipeline_results"] = None
                    st.session_state["thread_id"] = f"session_{uuid.uuid4().hex[:8]}"
                    st.success(f"Fetched fresh data for PR #{pr_data.get('pull_number')}!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error fetching PR: {e}")

    if st.button("Load Sample PR Repo (receipt.py / utils.py)", use_container_width=True):
        sample_code, sample_changed, sample_req = load_sample_repo_files()
        st.session_state["pr_code"] = sample_code
        st.session_state["pr_changed"] = sample_changed
        st.session_state["pr_req"] = sample_req
        st.session_state["pipeline_results"] = None
        st.session_state["thread_id"] = f"session_{uuid.uuid4().hex[:8]}"
        st.rerun()

    st.divider()
    st.header("⚙️ Model Settings")

    groq_key_env = os.getenv("GROQ_API_KEY", "")
    api_key_input = st.text_input(
        "Groq API Key",
        value=groq_key_env if groq_key_env != "your_groq_api_key_here" else "",
        type="password",
        help="Reads GROQ_API_KEY from environment by default",
    )
    if api_key_input:
        os.environ["GROQ_API_KEY"] = api_key_input

    model_choice = st.text_input(
        "Groq Model",
        value=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
    )
    os.environ["GROQ_MODEL"] = model_choice

# Header
st.title("🛡️ AI Software Quality Intelligence System")
st.markdown("Automated Code Quality, Deterministic Dependency Graphing & Corrective RAG (CRAG) for Pull Requests.")

# PR Summary Header
st.markdown(f"**Inspecting Target:** `{st.session_state['pr_url']}` | **Changed Files:** `{st.session_state['pr_changed']}`")

# Tabs for Main View
tab_dep_graph, tab_code_editor, tab_pipeline_audit = st.tabs([
    "📊 Dependency Graph & Static Analysis",
    "📝 PR Code & Specification",
    "🚀 Multi-Agent Audit Pipeline",
])

# ---------------------------------------------------------------------------
# TAB 1: Dependency Graph (Requirement 8)
# ---------------------------------------------------------------------------
with tab_dep_graph:
    st.subheader("NetworkX & AST Deterministic Dependency Graph")

    # Compute dependency graph on the active codebase
    active_code = st.session_state["pr_code"]
    active_changed = st.session_state["pr_changed"]
    dep_graph_data, nx_g, lint_issues = build_dependency_graph(active_code, active_changed)

    col_ctrl1, col_ctrl2 = st.columns([1, 3])
    with col_ctrl1:
        show_stdlib = st.checkbox("Show stdlib", value=False, help="Toggle visibility of standard library module nodes")

    # Legend
    st.markdown(
        """
        <div class="legend-box">
            <div class="legend-item"><span class="color-swatch" style="background-color: #E1F5FE; border-color: #0288D1;"></span> <strong>Local Code File</strong></div>
            <div class="legend-item"><span class="color-swatch" style="background-color: #FFE0B2; border-color: #E65100;"></span> <strong>Blast Radius (Dependents)</strong></div>
            <div class="legend-item"><span class="color-swatch" style="background-color: #E1F5FE; border: 3px solid #0D47A1;"></span> <strong>Changed PR File</strong></div>
            <div class="legend-item"><span class="color-swatch" style="background-color: #FFCDD2; border-color: #C62828;"></span> <strong>Missing Module</strong></div>
            <div class="legend-item"><span class="color-swatch" style="background-color: #E0E0E0; border-color: #757575;"></span> <strong>External Package</strong></div>
            <div class="legend-item"><span class="color-swatch" style="background-color: #F5F5F5; border-color: #BDBDBD;"></span> <strong>Standard Library</strong></div>
            <div class="legend-item"><span style="color: #D32F2F; font-weight: bold;">- - - ❌</span> <strong>Broken Symbol Link</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Render Graphviz Chart
    dot_graph = to_dot(dep_graph_data, show_stdlib=show_stdlib)
    st.graphviz_chart(dot_graph, use_container_width=True)

    # Tables below the graph
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.markdown("### ❌ Broken Symbol Links")
        broken = dep_graph_data.get("broken_links", [])
        if broken:
            st.dataframe(broken, use_container_width=True)
        else:
            st.success("No broken symbol imports detected!")

    with col_t2:
        st.markdown("### 🔄 Circular Dependencies (Cycles)")
        cycles = dep_graph_data.get("cycles", [])
        if cycles:
            st.error(f"Detected {len(cycles)} circular dependencies:")
            for c in cycles:
                st.write(" -> ".join(c) + " -> " + c[0])
        else:
            st.success("No circular dependencies detected.")

    st.markdown("### ⚠️ Pyflakes Static Lint Issues")
    if lint_issues:
        st.dataframe(lint_issues, use_container_width=True)
    else:
        st.success("Pyflakes reported no linting or unused import issues.")

# ---------------------------------------------------------------------------
# TAB 2: PR Code & Specification
# ---------------------------------------------------------------------------
with tab_code_editor:
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        st.subheader("📋 Specification Requirements (docs/PRD.md)")
        new_req = st.text_area(
            "PRD Specification:",
            value=st.session_state["pr_req"],
            height=380,
            key="spec_editor",
        )
        st.session_state["pr_req"] = new_req

    with col_e2:
        st.subheader("💻 Pull Request Code Files")
        selected_file = st.selectbox("Select file to view/edit:", options=list(active_code.keys()))
        if selected_file:
            file_src = st.text_area(
                f"Source: {selected_file}",
                value=active_code[selected_file],
                height=340,
                key=f"editor_{selected_file}",
            )
            st.session_state["pr_code"][selected_file] = file_src

# ---------------------------------------------------------------------------
# TAB 3: Multi-Agent Audit Pipeline
# ---------------------------------------------------------------------------
with tab_pipeline_audit:
    st.subheader("Multi-Agent Intelligence Pipeline")
    st.caption("Orchestrator -> Planner -> [Parallel: Static Agent + CRAG Agent] -> Generator -> 4 Critics Validator -> Human Approval")

    col_run, col_status = st.columns([1, 3])
    with col_run:
        run_btn = st.button("🚀 Run Quality Intelligence Audit", type="primary", use_container_width=True)

    app = st.session_state["app_instance"]
    cfg = {"configurable": {"thread_id": st.session_state["thread_id"]}}

    if run_btn:
        with st.status("Executing Multi-Agent Intelligence Pipeline...", expanded=True) as status:
            try:
                st.write("1. Orchestrator initializing...")
                initial_input: S = {
                    "requirement": st.session_state["pr_req"],
                    "code": st.session_state["pr_code"],
                    "changed_files": st.session_state["pr_changed"],
                }

                st.write("2. Planner formulating inspection focus...")
                st.write("3. Parallel execution: Static Agent (AST Dep Graph) + CRAG Agent (Corrective RAG)...")
                st.write("4. Generator repairing code & generating pytest suite...")
                st.write("5. Validator running 4 Critic LLMs in parallel...")

                app.invoke(initial_input, config=cfg)
                status.update(label="Pipeline Execution Paused at Human Approval Gate!", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Pipeline Execution Failed", state="error", expanded=True)
                st.error(f"Execution Error: {e}")

    # Inspect current checkpoint
    checkpoint = app.get_state(cfg)
    results = checkpoint.values if checkpoint else None

    if results and "plan" in results:
        st.divider()
        st.subheader("📊 Audit Findings & Quality Report")

        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Retries Elapsed", results.get("retries", 0))
        with m2:
            val = results.get("validation", {})
            st.metric("Critic Consensus", "PASSED" if val.get("all_passed") else "FAILED")
        with m3:
            broken_ct = len(results.get("static_findings", {}).get("broken_links", []))
            st.metric("Broken Symbols", broken_ct)
        with m4:
            next_step = checkpoint.next[0] if checkpoint and checkpoint.next else "COMPLETED"
            st.metric("Next Gate Node", next_step)

        # Human Review Gate
        if checkpoint and "approval" in checkpoint.next:
            st.info("🛑 Human-In-The-Loop review gate reached. The pipeline has paused before 'approval'.")

            c_h1, c_h2 = st.columns([1, 2])
            with c_h1:
                if st.button("✅ Approve & Merge PR", type="primary", use_container_width=True):
                    app.update_state(cfg, {"approved": True})
                    final_state = app.invoke(None, config=cfg)
                    st.success("PR Approved! Code finalized.")
                    st.rerun()

            with c_h2:
                rej_notes = st.text_input("Rejection Feedback / Requested Changes:")
                if st.button("❌ Reject & Loop Back to Orchestrator", use_container_width=True):
                    app.update_state(cfg, {"approved": False, "feedback": rej_notes or "Please address critic concerns."})
                    app.invoke(None, config=cfg)
                    st.warning("Feedback delivered to Orchestrator.")
                    st.rerun()

        # Detailed breakdown tabs
        t_fixes, t_critics, t_crag, t_static = st.tabs([
            "🛠️ Patched Code & Tests",
            "⚖️ Critic Verdicts",
            "🧩 CRAG Gaps",
            "🔍 Static Findings",
        ])

        with t_fixes:
            fixes = results.get("fixes", {})
            st.markdown("### Suggested Changes")
            for chg in fixes.get("suggested_changes", []):
                st.markdown(f"- **{chg.get('issue')}:** {chg.get('change')}")

            st.markdown("### Patched Implementation Code")
            st.code(fixes.get("patched_code", ""), language="python")

            st.markdown("### Generated Automated Pytest Tests")
            st.code(fixes.get("new_tests", ""), language="python")

        with t_critics:
            critics = results.get("validation", {}).get("critics", {})
            for c_name, verdict in critics.items():
                p = verdict.get("pass", False)
                icon = "✅ PASS" if p else "❌ FAIL"
                with st.expander(f"{icon} — Critic: {c_name.capitalize()}"):
                    st.markdown(f"**Verdict:** {'PASS' if p else 'FAIL'}")
                    st.markdown(f"**Reason:** {verdict.get('reason')}")

        with t_crag:
            for g in results.get("gaps", []):
                s = g.get("status", "missing")
                badge = "🟢 Satisfied" if s == "satisfied" else f"🔴 {s.upper()}"
                with st.expander(f"{badge} — {g.get('point')}"):
                    st.markdown(f"**Evidence:** `{g.get('evidence')}`")
                    st.markdown(f"**Reason:** {g.get('reason')}")

        with t_static:
            st.json(results.get("static_findings", {}))
