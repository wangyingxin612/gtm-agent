"""
TDD tests for src/agents/icp_interpreter.py.
All Claude API calls are mocked — no real API calls ever made.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.icp import ICPDefinition
from src.agents.icp_interpreter import ICPInterpreter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_json(**overrides) -> str:
    """Return a valid LLM JSON response string with sensible defaults."""
    base = {
        "industries": ["Financial Services"],
        "company_size_min": 50,
        "company_size_max": 500,
        "locations": ["US"],
        "keywords": ["compliance", "operations"],
        "pain_points": ["manual documentation"],
        "growth_stages": ["Series A", "Series B"],
        "interpretation_confidence": 0.9,
        "warnings": [],
    }
    base.update(overrides)
    return json.dumps(base)


def _mock_anthropic_response(content: str) -> MagicMock:
    """Simulate an Anthropic Messages API response object."""
    block = MagicMock()
    block.text = content
    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture
def interpreter():
    return ICPInterpreter(api_key="test-api-key")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_raises_for_empty_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            ICPInterpreter(api_key="")

    def test_raises_for_none_api_key(self):
        with pytest.raises((ValueError, TypeError)):
            ICPInterpreter(api_key=None)

    def test_valid_key_stores_on_instance(self):
        interp = ICPInterpreter(api_key="sk-test")
        assert interp.api_key == "sk-test"


# ---------------------------------------------------------------------------
# Core: interpret() returns ICPDefinition
# ---------------------------------------------------------------------------

class TestInterpret:
    async def test_returns_icp_definition(self, interpreter):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(_make_llm_json())
        )

        result = await interpreter.interpret(
            target="compliance software companies in the US with 50-500 employees",
            client=mock_client,
        )

        assert isinstance(result, ICPDefinition)

    async def test_basic_field_mapping(self, interpreter):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(_make_llm_json())
        )

        result = await interpreter.interpret(
            target="compliance software companies in the US",
            client=mock_client,
        )

        assert result.industries == ["Financial Services"]
        assert result.company_size_min == 50
        assert result.company_size_max == 500
        assert result.locations == ["US"]
        assert result.keywords == ["compliance", "operations"]
        assert result.pain_points == ["manual documentation"]
        assert result.growth_stages == ["Series A", "Series B"]
        assert result.interpretation_confidence == 0.9
        assert result.warnings == []

    async def test_optional_inputs_forwarded_to_prompt(self, interpreter):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(_make_llm_json())
        )

        await interpreter.interpret(
            target="fintech companies",
            website="https://acme.com",
            description="We sell compliance tools",
            existing_customers=["stripe.com", "square.com"],
            competitors=["competitor.com"],
            client=mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args
        prompt_text = str(call_kwargs)
        assert "acme.com" in prompt_text or "https://acme.com" in prompt_text
        assert "stripe.com" in prompt_text
        assert "competitor.com" in prompt_text

    async def test_uses_model_from_config(self, interpreter):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(_make_llm_json())
        )

        await interpreter.interpret(target="test", client=mock_client)

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("model") == "claude-sonnet-4-6"

    async def test_missing_optional_llm_fields_produce_none(self, interpreter):
        minimal_json = json.dumps({
            "industries": ["Insurance"],
            "company_size_min": 10,
            "company_size_max": 200,
            "locations": ["GB"],
            "interpretation_confidence": 0.75,
            "warnings": [],
        })
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(minimal_json)
        )

        result = await interpreter.interpret(target="insurance companies UK", client=mock_client)

        assert result.keywords is None
        assert result.pain_points is None
        assert result.growth_stages is None
        assert result.industries == ["Insurance"]


# ---------------------------------------------------------------------------
# Warnings passthrough
# ---------------------------------------------------------------------------

class TestWarnings:
    async def test_llm_warnings_appear_in_result(self, interpreter):
        llm_json = _make_llm_json(warnings=["Very broad ICP — may return 10,000+ companies"])
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(llm_json)
        )

        result = await interpreter.interpret(target="all companies", client=mock_client)

        assert len(result.warnings) == 1
        assert "broad" in result.warnings[0].lower()

    async def test_low_confidence_adds_warning(self, interpreter):
        llm_json = _make_llm_json(interpretation_confidence=0.5, warnings=[])
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(llm_json)
        )

        result = await interpreter.interpret(target="vague description", client=mock_client)

        assert result.interpretation_confidence == 0.5
        assert any("confidence" in w.lower() or "unclear" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Error handling: malformed LLM output
# ---------------------------------------------------------------------------

class TestMalformedLLMOutput:
    async def test_json_wrapped_in_markdown_fences_is_parsed(self, interpreter):
        fenced = f"```json\n{_make_llm_json()}\n```"
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(fenced)
        )

        result = await interpreter.interpret(target="test", client=mock_client)

        assert isinstance(result, ICPDefinition)
        assert result.industries == ["Financial Services"]

    async def test_preamble_before_json_is_stripped(self, interpreter):
        with_preamble = f"Here is my analysis:\n{_make_llm_json()}"
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(with_preamble)
        )

        result = await interpreter.interpret(target="test", client=mock_client)

        assert isinstance(result, ICPDefinition)

    async def test_invalid_json_raises_value_error(self, interpreter):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response("This is not JSON at all.")
        )

        with pytest.raises((ValueError, RuntimeError)):
            await interpreter.interpret(target="test", client=mock_client)

    async def test_valid_json_missing_required_field_raises(self, interpreter):
        bad_json = json.dumps({"company_size_min": 50, "interpretation_confidence": 0.8})
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_anthropic_response(bad_json)
        )

        with pytest.raises((ValueError, RuntimeError)):
            await interpreter.interpret(target="test", client=mock_client)


# ---------------------------------------------------------------------------
# Retry on API errors
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    async def test_retries_on_api_error_and_succeeds(self, interpreter):
        import anthropic

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                anthropic.APIStatusError(
                    "rate limit",
                    response=MagicMock(status_code=429, headers={}),
                    body={},
                ),
                _mock_anthropic_response(_make_llm_json()),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await interpreter.interpret(target="test", client=mock_client)

        assert isinstance(result, ICPDefinition)
        assert mock_client.messages.create.call_count == 2

    async def test_raises_after_all_retries_exhausted(self, interpreter):
        import anthropic

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                "rate limit",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception):
                await interpreter.interpret(target="test", client=mock_client)

    async def test_retries_on_connection_error(self, interpreter):
        """APIConnectionError (subclass of APIError) should also trigger retry."""
        import anthropic

        mock_client = MagicMock()
        conn_err = anthropic.APIConnectionError(request=MagicMock())
        mock_client.messages.create = AsyncMock(
            side_effect=[
                conn_err,
                _mock_anthropic_response(_make_llm_json()),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await interpreter.interpret(target="test", client=mock_client)

        assert isinstance(result, ICPDefinition)
        assert mock_client.messages.create.call_count == 2
