import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

CACHE_DIR = Path(__file__).parent / ".cache_prs"
CACHE_DIR.mkdir(exist_ok=True)


def parse_pr_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parses GitHub PR URL into owner, repo, and pull_number.
    Accepts formats:
    - https://github.com/owner/repo/pull/123
    - github.com/owner/repo/pull/123
    """
    pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    match = re.search(pattern, url)
    if not match:
        return None
    return {
        "owner": match.group(1),
        "repo": match.group(2),
        "pull_number": match.group(3),
    }


def fetch_github_json(api_url: str) -> Any:
    """Helper to fetch JSON from GitHub API with standard user agent."""
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "Antigravity-Software-Quality-Intelligence"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_raw_content(raw_url: str) -> str:
    """Helper to fetch raw text content from GitHub."""
    req = urllib.request.Request(
        raw_url,
        headers={"User-Agent": "Antigravity-Software-Quality-Intelligence"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def load_pr(
    pr_url: str,
    force_refresh: bool = False,
    default_sample_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Loads pull request information.
    Checks local cache first; only fetches via GitHub API if not cached or force_refresh=True.
    Returns:
    {
        "url": str,
        "owner": str,
        "repo": str,
        "pull_number": str,
        "title": str,
        "body": str,
        "requirement": str,
        "code": Dict[str, str],        # file_path -> source code
        "changed_files": List[str],    # list of changed file paths
        "is_cached": bool
    }
    """
    parsed = parse_pr_url(pr_url)
    if not parsed:
        raise ValueError(f"Invalid GitHub PR URL format: {pr_url}")

    cache_file = CACHE_DIR / f"{parsed['owner']}_{parsed['repo']}_{parsed['pull_number']}.json"

    if cache_file.exists() and not force_refresh:
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_data["is_cached"] = True
            return cached_data
        except Exception:
            pass

    # Fetch live data from GitHub API
    owner = parsed["owner"]
    repo = parsed["repo"]
    pull_num = parsed["pull_number"]

    pr_api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_num}"
    files_api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_num}/files"

    pr_meta = fetch_github_json(pr_api_url)
    files_meta = fetch_github_json(files_api_url)

    head_ref = pr_meta.get("head", {}).get("ref", "main")
    code_dict: Dict[str, str] = {}
    changed_files: List[str] = []

    for f in files_meta:
        filename = f.get("filename")
        if not filename:
            continue
        changed_files.append(filename)

        # Try to download the raw file from the PR head branch
        raw_url = f.get("raw_url")
        if raw_url:
            try:
                code_dict[filename] = fetch_raw_content(raw_url)
            except Exception:
                # Fallback to patch if raw content cannot be retrieved
                code_dict[filename] = f.get("patch", "")
        else:
            code_dict[filename] = f.get("patch", "")

    # Requirement spec: Check for docs/PRD.md in repository, fallback to PR description
    requirement_text = pr_meta.get("body", "")
    try:
        prd_raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/docs/PRD.md"
        prd_content = fetch_raw_content(prd_raw_url)
        if prd_content:
            requirement_text = prd_content
    except Exception:
        pass

    if not requirement_text.strip():
        requirement_text = f"PR Title: {pr_meta.get('title', '')}\nPR Description:\n{pr_meta.get('body', '')}"

    result = {
        "url": pr_url,
        "owner": owner,
        "repo": repo,
        "pull_number": pull_num,
        "title": pr_meta.get("title", ""),
        "body": pr_meta.get("body", ""),
        "requirement": requirement_text,
        "code": code_dict,
        "changed_files": changed_files,
        "is_cached": False,
    }

    # Save to cache
    try:
        cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass

    return result
