"""BACK-5093: list_ai_models renders every model on the requested page.

The handler used to show five models per provider and collapse the rest into
"... and N more models". Those models appeared on no other page, so walking the
catalog page by page could never reach the reported total.
"""

from __future__ import annotations

import re

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)
from tests.unit._helpers_hal import wire_embedded_reader

_MODEL_ROW = re.compile(r"^- \*\*(?P<name>[^*]+)\*\* \(Input: ", re.MULTILINE)


def _model(name: str, provider: str) -> dict:
    return {
        "name": name,
        "provider": provider,
        "inputCostPerToken": 0.000001,
        "outputCostPerToken": 0.000002,
    }


def _page(models: list, total: int) -> dict:
    return {
        "_embedded": {"aIModelResourceList": models},
        "page": {"totalElements": total, "size": len(models)},
    }


async def _render(models: list, total: int, size: int) -> str:
    mgmt = MeteringManagement()
    client = wire_embedded_reader(AsyncMock())
    client.get_ai_models = AsyncMock(return_value=_page(models, total))
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        result = await mgmt._handle_list_ai_models({"page": 0, "size": size})
    return result[0].text


class TestListAiModelsRendersTheWholePage:
    @pytest.mark.asyncio
    async def test_every_model_from_a_large_provider_is_rendered(self):
        models = [_model(f"openai-model-{i}", "OPENAI") for i in range(23)]

        text = await _render(models, total=23, size=23)

        rendered = _MODEL_ROW.findall(text)
        assert rendered == [m["name"] for m in models]
        assert "more models" not in text

    @pytest.mark.asyncio
    async def test_full_page_of_mixed_providers_renders_size_rows(self):
        providers = ["OPENAI", "ANTHROPIC", "GOOGLE", "MISTRAL", "COHERE"]
        models = [
            _model(f"model-{i}", providers[i % len(providers)]) for i in range(100)
        ]

        text = await _render(models, total=5354, size=100)

        assert len(_MODEL_ROW.findall(text)) == 100
        assert sorted(_MODEL_ROW.findall(text)) == sorted(m["name"] for m in models)
        assert "more models" not in text
        assert "## **OPENAI** (20 models)" in text

    @pytest.mark.asyncio
    async def test_walking_every_page_reaches_the_reported_total(self):
        catalog = [_model(f"m-{i}", "OPENAI" if i % 3 else "GOOGLE") for i in range(47)]
        size = 10
        seen: set = set()

        async def platform(*, page: int, size: int) -> dict:
            return _page(catalog[page * size : (page + 1) * size], len(catalog))

        for page in range(0, (len(catalog) + size - 1) // size):
            mgmt = MeteringManagement()
            client = wire_embedded_reader(AsyncMock())
            client.get_ai_models = AsyncMock(side_effect=platform)
            with patch.object(
                mgmt, "get_client", new_callable=AsyncMock, return_value=client
            ):
                result = await mgmt._handle_list_ai_models({"page": page, "size": size})
            seen.update(_MODEL_ROW.findall(result[0].text))

        assert len(seen) == len(catalog)
