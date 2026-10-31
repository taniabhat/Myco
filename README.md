# 🛡️ AI-Powered Software Quality Intelligence System

An autonomous, multi-agent code quality assessment and pull request merge-gate intelligence platform built with **LangGraph**, **Groq** (`qwen/qwen3.8-27b`), **NetworkX**, **Pyflakes**, and **Streamlit**.

Designed for the **Myco Engineering Assessment**, this system audits code changes against Product Requirements Documents (PRDs), generates deterministic dependency graphs, identifies blast radiuses and broken symbol links, performs Corrective RAG (CRAG) spec auditing, and executes self-correcting repairs with a human-in-the-loop review gate.

---

## ⚡ Quickstart: Single-Line Setup & Run Commands

Run the exact one-liner below in your terminal for your operating system:

### 🐧 Linux
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && streamlit run app.py
```

### 🍎 macOS
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && streamlit run app.py
```

### 🪟 Windows (PowerShell)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; streamlit run app.py
```

### 🪟 Windows (Command Prompt / CMD)
```cmd
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && streamlit run app.py
```

---

## 🔑 When & Where to Put the API Key

You need a **Groq API Key** (free tier available from [console.groq.com](https://console.groq.com/keys)). You have two options:

### Option A: In the `.env` File (Recommended for Local Dev)
**When to do this:** Before launching the app or running CLI tests.
1. Copy the example file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and insert your key:
   ```env
   GROQ_API_KEY=gsk_your_actual_groq_api_key_here
   GROQ_MODEL=qwen/qwen3.8-27b
   ```
   *(The app will automatically load this key on startup).*

### Option B: Directly in the UI at Runtime (Zero Setup)
**When to do this:** If you already launched the app without creating a `.env` file.
1. Run `streamlit run app.py`.
2. Look at the **left sidebar** under **⚙️ Model Settings**.
3. Paste your key into the **"Groq API Key"** password field. The key applies immediately to all pipeline runs in that session.

> **Note:** If no API key is provided, deterministic components (such as `dep_graph.py` and the AST dependency graph) work 100% offline, and pipeline nodes return baseline fallback plans for evaluation.

---

## 📖 How to Use the Application

### 1. Load Any GitHub Pull Request
In the left sidebar under **🔗 Pull Request Integration**:
- Paste any GitHub PR link into the text box (e.g., `https://github.com/vvkmj/myco-prd-demo/pull/3`).
- Click **"Load PR (Cache)"**: Loads the PR from local disk cache if previously downloaded.
- Click **"🔄 Fetch Fresh"**: Pulls live PR metadata, modified files, patches, and `docs/PRD.md` directly from GitHub using the GitHub REST API (no webhooks needed).
- Or click **"Load Sample PR Repo"** to test with the bundled multi-file demo (`receipt.py`, `utils.py`, `checkout.py`).

### 2. Inspect the Dependency Graph & Static Lints
Open the **"📊 Dependency Graph & Static Analysis"** tab:
- **Interactive Graphviz Rendering**:
  - 🔵 **Local Files** (Blue)
  - 🔲 **Changed PR Files** (Thick dark blue border)
  - 🟠 **Blast Radius** (Orange fill): Every file that depends on the changed files.
  - 🔴 **Missing Modules** (Red fill): Packages not installed or not in stdlib.
  - ⚪ **External Packages** (Gray fill): Installed third-party packages.
  - 🌫️ **Standard Library** (Light gray): Toggle on/off using the **"Show stdlib"** checkbox.
  - **- - - ❌ Broken Links** (Red dashed arrows): Function/symbol imports that do not exist in the target file.
- Review the tables beneath the graph for:
  - **Broken Symbol Links** (e.g. `receipt.py -> round_money`)
  - **Circular Dependencies (Cycles)** detected over local nodes.
  - **Pyflakes Lint Issues** (unused imports, undefined names).

### 3. Review Code & PRD Specification
Open the **"📝 PR Code & Specification"** tab:
- Review the PRD criteria extracted from `docs/PRD.md`.
- Select and edit any file in the PR codebase to test fixes or inject edge cases.

### 4. Run the Multi-Agent Audit Pipeline
Open the **"🚀 Multi-Agent Audit Pipeline"** tab and click **"🚀 Run Quality Intelligence Audit"**:
- **Step 1 (Orchestrator)**: Resets retries and preserves prior human feedback.
- **Step 2 (Planner)**: Decomposes the task into specific checks and primary focus.
- **Step 3 (Parallel Agents)**:
  - `static_agent`: Runs AST dependency graph + pyflakes + LLM static defect review.
  - `crag_agent`: Corrective RAG (splits criteria into points, chunks code by AST, retrieves top 2 chunks by keyword overlap, grades each point, and re-evaluates full code if missing).
- **Step 4 (Generator)**: Synthesizes structured changes, fully patched code, and new `pytest` unit tests.
- **Step 5 (4 Critics Validator)**: Evaluates patched code in parallel:
  1. *Dependencies Critic* (no missing/unused/broken imports)
  2. *Names Critic* (consistent and compliant naming)
  3. *Cases Critic* (coverage of edge cases and missing tests)
  4. *Values Critic* (validations, ranges, tax rates, constants)
  5. *AST Sanity Check* (deterministic compilation check)
- **Automated Self-Correction Loop**: If critics reject the code and `retries < 2`, the pipeline routes back to `generator` with critic feedback to attempt a self-repair.

### 5. Human-In-The-Loop Approval Gate
Once validation completes, the pipeline reaches the `approval` node where LangGraph pauses execution (`interrupt_before=['approval']`):
- Click **"✅ Approve & Merge PR"**: Resumes the graph to `finalize`, storing `final_code` and marking the PR ready for release.
- Enter change notes and click **"❌ Reject & Loop Back to Orchestrator"**: Passes your feedback back to `orchestrator` to trigger targeted remediation.

---

## 🏗️ Architecture & Component Overview

```mermaid
flowchart TD
    orchestrator["1. orchestrator (Entry / Reset retries / Preserve feedback)"] --> planner["2. planner (Task Decomposition & Focus)"]
    
    %% Parallel Agents
    planner --> static_agent["3a. static_agent (AST Dep Graph + Pyflakes)"]
    planner --> crag_agent["3b. crag_agent (Corrective RAG: Retrieve, Grade, Correct)"]
    
    %% Fan-in to Generator
    static_agent --> generator["4. generator (Code Repair & Test Suite)"]
    crag_agent --> generator
    
    %% Validation & Critic Consensus
    generator --> validate["5. validate (4 Critic LLMs + AST Syntax Check)"]
    
    %% Self-Correction Loop
    validate -->|retry (all_passed=False & retries < 2)| generator
    validate -->|ok (all_passed=True or retries >= 2)| approval["6. approval (Human Gate Interrupt)"]
    
    %% Human Review Decisions
    approval -->|yes (approved=True)| finalize["7. finalize (Export Final Code)"]
    approval -->|no (approved=False + feedback)| orchestrator
    finalize --> END([END])
```

### Module Summary
| File | Responsibility |
|---|---|
| [`dep_graph.py`](file:///home/rythm/Desktop/didi/dep_graph.py) | **Deterministic AST Dependency Graph**: Parses imports (including relative imports), resolves node kinds (`local`, `stdlib`, `external`, `missing`), performs symbol-level broken import checks, runs `pyflakes`, and computes `blast_radius` and cycles using `networkx`. |
| [`graph_viz.py`](file:///home/rythm/Desktop/didi/graph_viz.py) | **Graph Visualizer**: Converts dependency graphs to Graphviz DOT (`to_dot`) and GitHub-flavored Mermaid (`to_mermaid`) with semantic styling. |
| [`pr_loader.py`](file:///home/rythm/Desktop/didi/pr_loader.py) | **PR Ingestion & Cache**: Pulls PR metadata and files for arbitrary GitHub PR URLs, caching in `.cache_prs/` to eliminate redundant network calls. |
| [`graph.py`](file:///home/rythm/Desktop/didi/graph.py) | **LangGraph Multi-Agent Pipeline**: Implements `orchestrator`, `planner`, `static_agent`, `crag_agent`, `generator`, `validate` (4 critics), `approval` interrupt, and `finalize`. |
| [`llm.py`](file:///home/rythm/Desktop/didi/llm.py) | **LLM Interface**: Groq client for `qwen/qwen3.8-27b` with token limits enforcement (`max_tokens`), rate-limiting pacing semaphore, markdown stripping, and `json-repair` fallback parsing. |
| [`app.py`](file:///home/rythm/Desktop/didi/app.py) | **Streamlit UI**: Complete dashboard with visual graphviz diagrams, PR URL loaders, code editors, and human-in-the-loop review controls. |

---

## 🧪 Running Self-Tests (CLI)

You can run both core modules independently from the terminal:

### 1. Deterministic Dependency Graph Test
Verifies that `receipt.py -> round_money` is flagged as a broken symbol link and that `fastmath` is identified as missing (0 LLM calls):
```bash
python dep_graph.py
```
*Expected output:*
```text
[Broken Links]:
 - receipt.py imports 'round_money' from 'utils.py': Symbol 'round_money' is not defined in 'utils.py'
[Nodes]:
 - fastmath (kind=missing, changed=False, blast_radius=False)
✅ All self-test assertions PASSED successfully!
```

### 2. Multi-Agent Pipeline End-to-End Test
Executes the full LangGraph pipeline on the sample codebase up to the human review interrupt:
```bash
python graph.py
```

---

## 📂 Project Directory Structure

```text
.
├── .cache_prs/                 # Local cache directory for fetched PRs (gitignored)
├── .env.example                # Example environment variables template
├── .gitignore                  # Git ignore rules for Python, venv, and cache
├── app.py                      # Streamlit interactive UI application
├── dep_graph.py                # Deterministic AST & NetworkX dependency graph builder
├── graph_viz.py                # Graphviz DOT & Mermaid syntax generators
├── graph.py                    # LangGraph multi-agent quality intelligence pipeline
├── llm.py                      # Groq & Qwen chat model helper with JSON repair
├── pr_loader.py                # GitHub Pull Request loader and local caching engine
├── requirements.txt            # Project Python dependencies
└── sample/                     # Sample PR and benchmark test files
    ├── code.py                 # Non-compliant PR checkout sample
    ├── pr_metadata.json        # Live GitHub PR #3 metadata cache
    ├── requirement.txt         # PRD specification for checkout & coupons
    └── repo/                   # Multi-file dependency test repository
        ├── checkout.py         # Checkout service
        ├── receipt.py          # Receipt generator (imports broken symbol & missing module)
        └── utils.py            # Utility module
```

---

## 📄 License
MIT License. Developed for the Myco Engineering Assessment.
