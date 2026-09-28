from __future__ import annotations

import json
import os
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from scoring.prompt import build_prompt

DEFAULT_MODEL = "gemini-3.1-pro-preview"
TRANSIENT_RETRY_DELAYS = (5, 15)  # seconds, for 503/overloaded-style errors

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _generate(prompt: str, temperature: float, json_mode: bool) -> str:
    client = _get_client()
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_mode else "text/plain",
    )

    last_error = None
    for delay in (0, *TRANSIENT_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            text = response.text
            if not text:
                raise RuntimeError("Gemini response had no text content.")
            return text
        except genai_errors.ServerError as e:
            last_error = e
            continue
    raise RuntimeError(f"Gemini API unavailable after {len(TRANSIENT_RETRY_DELAYS) + 1} attempts: {last_error}")


def call_llm(redacted_cv_text: str, rubrics: dict, repair_note: str | None = None) -> dict:
    """Scoring call: strict JSON mode, temperature 0 (deterministic)."""
    prompt = build_prompt(redacted_cv_text, rubrics)
    if repair_note:
        prompt += (
            f"\n\nYour previous submission was rejected for this reason: {repair_note}\n"
            "Submit again, correcting that issue. Respond with ONLY the corrected JSON object."
        )
    return json.loads(_generate(prompt, temperature=0, json_mode=True))


def generate_json(prompt: str, temperature: float = 0.4) -> dict:
    """Free-form generation (interview briefs) that still returns structured JSON."""
    return json.loads(_generate(prompt, temperature=temperature, json_mode=True))


def generate_text(prompt: str, temperature: float = 0.5) -> str:
    """Free-form generation (email drafts) returning plain text."""
    return _generate(prompt, temperature=temperature, json_mode=False).strip()
