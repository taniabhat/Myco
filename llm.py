import json
import os
import re
import threading
import time
from typing import Any, Optional
from dotenv import load_dotenv
import json_repair

# Load variables from .env file
load_dotenv()

DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Semaphore to prevent concurrent requests from exceeding Groq output token limits (OTPM)
API_SEMAPHORE = threading.Semaphore(1)


def get_chat_model(
    model_name: Optional[str] = None,
    temperature: float = 0.2,
    api_key: Optional[str] = None,
    max_tokens: int = 800,
):
    """
    Returns an instance of ChatGroq (or ChatGoogleGenerativeAI fallback)
    reading credentials from the environment (.env) or arguments.
    Enforces max_tokens to stay within Groq's 1000 Output Tokens Per Minute (OTPM) limit.
    """
    # 1. Primary: Groq API with Qwen model
    groq_key = api_key or os.getenv("GROQ_API_KEY")
    if groq_key and groq_key != "your_groq_api_key_here":
        from langchain_groq import ChatGroq

        chosen_model = model_name or DEFAULT_GROQ_MODEL
        return ChatGroq(
            model=chosen_model,
            groq_api_key=groq_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # 2. Secondary fallback: Google GenAI
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key and google_key != "your_key_here":
        from langchain_google_genai import ChatGoogleGenerativeAI

        chosen_model = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return ChatGoogleGenerativeAI(
            model=chosen_model,
            google_api_key=google_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    return None


def strip_markdown_fences(text: str) -> str:
    """
    Strips markdown code fences (e.g. ```json ... ``` or ``` ... ```) from text.
    """
    text = text.strip()
    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.search(fence_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback line-by-line strip if regex didn't match surrounding text
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return text


def parse_json_response(raw_text: str) -> Any:
    """
    Parses a string into JSON after cleaning markdown fences and trailing text.
    Falls back to json_repair for robustness.
    """
    cleaned = strip_markdown_fences(raw_text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    try:
        return json_repair.loads(cleaned)
    except Exception:
        pass

    # Fallback regex search
    json_match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if json_match:
        try:
            return json_repair.loads(json_match.group(1))
        except Exception:
            return json.loads(json_match.group(1))

    raise ValueError(f"Unable to parse valid JSON from model response: {raw_text[:200]}")


def ask_json(
    prompt: str,
    model: Optional[Any] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
) -> Any:
    """
    Calls the Groq/Qwen chat model and parses a JSON reply.
    Uses a semaphore to ensure threads do not overwhelm the Groq rate limit.
    Strips markdown fences and retries once if JSON parsing fails.
    If no API key is configured, provides a mock response for pipeline verification.
    """
    llm = model or get_chat_model(
        model_name=model_name,
        temperature=temperature,
        api_key=api_key,
        max_tokens=max_tokens,
    )

    if llm is None:
        print("[Notice: GROQ_API_KEY not found in .env; returning baseline plan for pipeline execution test]", flush=True)
        return {
            "checks": [
                "dependencies",
                "names",
                "edge_cases",
                "missing_tests",
                "requirement_match",
            ],
            "focus": "Validate boundary checks, ensure requirement compliance, and remove missing/unused dependencies.",
        }

    formatting_instruction = (
        "\n\nIMPORTANT: Output valid, parseable JSON only. "
        "Do NOT include markdown formatting, code fences (e.g. ```json), or explanatory text outside JSON."
    )

    with API_SEMAPHORE:
        time.sleep(0.3)  # Gentle pacing to avoid per-second burst throttling
        try:
            response = llm.invoke(prompt + formatting_instruction)
            content = response.content if hasattr(response, "content") else str(response)
            return parse_json_response(content)
        except Exception as first_error:
            # Handle rate limit by cooling down
            err_str = str(first_error).lower()
            if "429" in err_str or "rate_limit" in err_str:
                time.sleep(3.0)

            # Retry once with error feedback
            retry_prompt = (
                f"{prompt}\n\n"
                f"Note: Your previous attempt failed to parse as valid JSON due to: {first_error}.\n"
                "Please return ONLY raw, strictly valid JSON without any markdown code fences or conversational text."
            )
            response = llm.invoke(retry_prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return parse_json_response(content)
