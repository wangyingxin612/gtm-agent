"""
ICPInterpreter — converts a natural-language ICP description into a structured
ICPDefinition by calling the Claude Sonnet API.

Config read from scoring_config.json (llm section):
  icp_interpretation_model  — model id
  icp_max_tokens            — max response tokens
  icp_temperature           — sampling temperature
"""

import asyncio
import json
import re
from typing import List, Optional

import anthropic

from src.agents.scoring_engine import load_scoring_config
from src.models.icp import ICPDefinition

_SYSTEM_PROMPT = (
    "You are an expert B2B sales strategist. Your job is to interpret "
    "a user's description of their ideal customer and convert it into structured "
    "criteria. Be specific and practical. Focus on observable, filterable signals."
)

_USER_TEMPLATE = """User Input:
- Company website: {website}
- Company description (from website): {description}
- Target customer description: {target}
- Existing customers (if provided): {customers}
- Competitors (if provided): {competitors}

Output ONLY a valid JSON object with this exact schema:
{{
  "industries": ["list", "of", "industries"],
  "company_size_min": number,
  "company_size_max": number,
  "locations": ["list", "of", "countries_or_cities"],
  "keywords": ["relevant", "keywords"],
  "pain_points": ["specific", "pain", "points"],
  "growth_stages": ["Series A", "Series B"],
  "interpretation_confidence": 0.0-1.0,
  "warnings": ["any", "warnings"]
}}

Do not include any explanation or preamble. Output only the JSON."""

_LOW_CONFIDENCE_THRESHOLD = 0.7
_MAX_RETRIES = 3


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the LLM response, stripping markdown fences."""
    # Strip ```json ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find the first '{' … last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _build_icp(data: dict) -> ICPDefinition:
    """Construct ICPDefinition from parsed LLM dict, appending low-confidence warning."""
    warnings: List[str] = list(data.get("warnings") or [])
    confidence = float(data.get("interpretation_confidence", 0.0))
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Low confidence ({confidence:.0%}): ICP description was unclear or ambiguous."
        )
    try:
        return ICPDefinition(
            industries=data["industries"],
            company_size_min=data.get("company_size_min", 10),
            company_size_max=data.get("company_size_max", 5000),
            locations=data["locations"],
            keywords=data.get("keywords") or None,
            pain_points=data.get("pain_points") or None,
            growth_stages=data.get("growth_stages") or None,
            revenue_min=data.get("revenue_min"),
            revenue_max=data.get("revenue_max"),
            exclude_industries=data.get("exclude_industries") or None,
            exclude_companies=data.get("exclude_companies") or None,
            recent_funding=data.get("recent_funding", False),
            recent_funding_months=data.get("recent_funding_months", 6),
            hiring_growth=data.get("hiring_growth", False),
            prefer_short_decision_chain=data.get("prefer_short_decision_chain", True),
            interpretation_confidence=confidence,
            warnings=warnings,
        )
    except Exception as exc:
        raise ValueError(f"LLM response missing required ICP fields: {exc}") from exc


class ICPInterpreter:
    """LLM-based agent: NL description → ICPDefinition."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("api_key is required and must be non-empty")
        self.api_key = api_key
        cfg = load_scoring_config()
        llm = cfg.get("llm", {})
        self._model = llm.get("icp_interpretation_model", "claude-sonnet-4-6")
        self._max_tokens = llm.get("icp_max_tokens", 800)
        self._temperature = llm.get("icp_temperature", 0.2)

    async def interpret(
        self,
        target: str,
        website: str = "",
        description: str = "",
        existing_customers: Optional[List[str]] = None,
        competitors: Optional[List[str]] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ) -> ICPDefinition:
        """Convert a natural-language ICP description into a structured ICPDefinition."""
        if client is None:
            client = anthropic.AsyncAnthropic(api_key=self.api_key)

        user_msg = _USER_TEMPLATE.format(
            website=website or "not provided",
            description=description or "not provided",
            target=target,
            customers=", ".join(existing_customers) if existing_customers else "none",
            competitors=", ".join(competitors) if competitors else "none",
        )

        raw = await self._call_with_retry(client, user_msg)
        data = _extract_json(raw)
        return _build_icp(data)

    async def _call_with_retry(self, client, user_msg: str) -> str:
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                return response.content[0].text
            except anthropic.APIStatusError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
        raise last_exc
