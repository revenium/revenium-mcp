"""Provider validation on the metering write path derives from the platform catalog.

The submit/validate write path used to enforce an eight-value hardcoded provider
enum while the same tool's ``get_supported_providers`` derived a much larger set
from ``client.get_ai_models`` and ``validate_model_provider`` greenlit catalog
pairs the write path then rejected. Validation now accepts the union of a static
baseline (the historical enum plus the known catalog names) and whatever the
live catalog most recently reported, compared case-insensitively. Garbage
strings are still rejected -- the accepted set only ever widens.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed import metering_management as mm
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
    MeteringTransactionManager,
)

# Providers the live catalog reports (lowercase, as persisted by the platform).
CATALOG_PROVIDERS = [
    "azure",
    "azure_ai",
    "bedrock",
    "bedrock_mantle",
    "chatgpt",
    "databricks",
    "dataforseo",
    "exa_ai",
    "fal_ai",
    "gemini",
    "gmi",
    "google_pse",
    "mistral",
    "novita",
    "openai",
    "openrouter",
    "parallel_ai",
    "perplexity",
    "serper",
    "tavily",
    "tencent",
    "vertex_ai",
    "vertex_ai-language-models",
    "vertex_ai-mistral_models",
    "watsonx",
]

VALID_TX = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "input_tokens": 1500,
    "output_tokens": 800,
    "duration_ms": 2500,
}

GARBAGE_PROVIDER = "definitely-not-a-provider"

# A provider the catalog prices but whose models all sit beyond the first page.
# The endpoint truncates pages to ~100 models regardless of the requested size,
# so the bulk fetch cannot see it; only the server-side provider filter can.
DEEP_CATALOG_PROVIDER = "deep_page_provider"


def _catalog_response(providers=None):
    """Build a ``get_ai_models`` envelope carrying the given provider names."""
    names = CATALOG_PROVIDERS if providers is None else providers
    return {
        "_embedded": {
            "aIModelResourceList": [
                {"name": f"model-{index}", "provider": name}
                for index, name in enumerate(names)
            ]
        }
    }


def _provider_names(envelope):
    """The names ``get_ai_model_providers`` would report for a model envelope."""
    models = (
        envelope.get("_embedded", {}).get("aIModelResourceList", [])
        if isinstance(envelope, dict)
        else []
    )
    return sorted(
        {
            model["provider"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("provider"), str)
        }
    )


DEFAULT_TEAM_ID = "test_team_id_456"
DEFAULT_BASE_URL = "https://api.revenium.test"


def _catalog_client(
    response=None,
    side_effect=None,
    *,
    team_id=DEFAULT_TEAM_ID,
    base_url=DEFAULT_BASE_URL,
    filter_hits=(),
    filter_error=None,
    providers=None,
    providers_error=None,
):
    """Fake client serving both catalog reads.

    ``get_ai_model_providers`` is the authoritative provider list and answers by
    default with the names present in the model envelope; ``providers`` overrides
    that answer and ``providers_error`` makes only that endpoint fail, leaving the
    ``get_ai_models`` scan to serve as the fallback. ``side_effect`` stands for
    the whole catalog being unavailable, so it fails both reads.

    ``get_ai_models`` also honours the server-side provider filter:
    ``filter_hits`` names the providers the filtered lookup would match. They are
    deliberately absent from the bulk (unfiltered) page, standing in for models
    that live beyond the ~100-model page the endpoint actually returns.
    """
    client = MagicMock()
    client.team_id = team_id
    client.base_url = base_url
    bulk = _catalog_response() if response is None else response
    hits = {name.strip().lower() for name in filter_hits}
    client.get_ai_model_providers = AsyncMock(
        side_effect=providers_error if providers_error is not None else side_effect,
        return_value=_provider_names(bulk) if providers is None else providers,
    )

    async def _get_ai_models(page=0, size=20, **filters):
        provider = filters.get("provider")
        if provider is None:
            return bulk
        if filter_error is not None:
            raise filter_error
        matches = (
            [{"name": f"{provider}-model", "provider": provider}]
            if provider.strip().lower() in hits
            else []
        )
        return {
            "_embedded": {"aIModelResourceList": matches},
            "page": {"totalElements": len(matches)},
        }

    client.get_ai_models = AsyncMock(side_effect=side_effect or _get_ai_models)
    return client


def _filtered_calls(client):
    """The targeted provider lookups a client received (bulk fetches excluded)."""
    return [call for call in client.get_ai_models.call_args_list if "provider" in call.kwargs]


def _patch_response_cache():
    """Neutralise the persistent validation response cache for a test."""
    mock_cache = MagicMock()
    mock_cache.get_cached_response = AsyncMock(return_value=None)
    mock_cache.set_cached_response = AsyncMock()
    mock_cache.clear_request_cache = MagicMock()
    return patch(
        "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache",
        mock_cache,
    )


@pytest.fixture(autouse=True)
def _clear_provider_catalog_cache():
    """The catalog cache is module-level; isolate every test from its neighbours."""
    mm._provider_catalog_cache.clear()
    token = mm._provider_catalog_key_var.set(None)
    yield
    mm._provider_catalog_key_var.reset(token)
    mm._provider_catalog_cache.clear()


class TestCatalogProviderAcceptance:
    """Catalog providers are accepted on both validation paths, any casing."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["bedrock", "BEDROCK", "  Bedrock  "])
    async def test_catalog_provider_accepted_async_path(self, provider):
        await mm._refresh_provider_catalog(_catalog_client())
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": provider}
        )
        assert not any("Invalid provider" in e for e in errors), errors

    @pytest.mark.asyncio
    async def test_catalog_provider_accepted_sync_path(self):
        """The synchronous fast path reads the same tenant-scoped cache entry."""
        catalog_only = "sync_path_catalog_provider"
        assert catalog_only not in mm._STATIC_PROVIDER_BASELINE
        await mm._refresh_provider_catalog(
            _catalog_client(response=_catalog_response(CATALOG_PROVIDERS + [catalog_only]))
        )
        assert (
            MeteringTransactionManager()._validate_transaction_inputs(
                {**VALID_TX, "provider": catalog_only}
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_every_catalog_provider_accepted(self):
        await mm._refresh_provider_catalog(_catalog_client())
        mgr = MeteringTransactionManager()
        rejected = []
        for provider in CATALOG_PROVIDERS:
            errors = await mgr._validate_string_fields({**VALID_TX, "provider": provider})
            if any("Invalid provider" in e for e in errors):
                rejected.append(provider)
        assert rejected == []


class TestCatalogWidensTheBaseline:
    """A provider the platform adds after this code shipped is accepted."""

    NEW_PROVIDER = "brand_new_provider"

    @pytest.mark.asyncio
    async def test_provider_absent_from_baseline_is_rejected_before_the_fetch(self):
        assert self.NEW_PROVIDER not in mm._STATIC_PROVIDER_BASELINE
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": self.NEW_PROVIDER}
        )
        assert any("Invalid provider" in e for e in errors)

    @pytest.mark.asyncio
    async def test_provider_absent_from_baseline_is_accepted_once_the_catalog_lists_it(self):
        client = _catalog_client(
            response=_catalog_response(CATALOG_PROVIDERS + [self.NEW_PROVIDER])
        )
        await mm._refresh_provider_catalog(client)
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": self.NEW_PROVIDER.upper()}
        )
        assert not any("Invalid provider" in e for e in errors), errors


class TestGarbageProviderStillRejected:
    """Widening the accepted set must not remove validation."""

    @pytest.mark.asyncio
    async def test_garbage_rejected_with_steer_async_path(self):
        await mm._refresh_provider_catalog(_catalog_client())
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": GARBAGE_PROVIDER}
        )
        provider_errors = [e for e in errors if "Invalid provider" in e]
        assert provider_errors, errors
        assert GARBAGE_PROVIDER in provider_errors[0]
        assert "get_supported_providers()" in provider_errors[0]

    @pytest.mark.asyncio
    async def test_rejection_does_not_enumerate_the_whole_catalog(self):
        """The message shows a few examples and a steer, never the full set."""
        await mm._refresh_provider_catalog(_catalog_client())
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": GARBAGE_PROVIDER}
        )
        message = next(e for e in errors if "Invalid provider" in e)
        assert "dataforseo" not in message
        assert "vertex_ai-mistral_models" not in message

    def test_garbage_rejected_sync_path(self):
        assert (
            MeteringTransactionManager()._validate_transaction_inputs(
                {**VALID_TX, "provider": GARBAGE_PROVIDER}
            )
            is False
        )


class TestStaticBaselineFallback:
    """A catalog fetch failure must never narrow the accepted set."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provider",
        ["ANTHROPIC", "anthropic", "GOOGLE", "COHERE", "TOGETHER", "GROQ", "OPENAI"],
    )
    async def test_historical_enum_accepted_when_fetch_fails(self, provider):
        client = _catalog_client(side_effect=RuntimeError("catalog unavailable"))
        await mm._refresh_provider_catalog(client)
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": provider}
        )
        assert not any("Invalid provider" in e for e in errors), errors

    @pytest.mark.asyncio
    async def test_known_catalog_name_accepted_when_fetch_fails(self):
        """The baseline already carries the catalog names, so bedrock survives."""
        client = _catalog_client(side_effect=RuntimeError("catalog unavailable"))
        await mm._refresh_provider_catalog(client)
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": "bedrock"}
        )
        assert not any("Invalid provider" in e for e in errors), errors

    @pytest.mark.asyncio
    async def test_garbage_still_rejected_when_fetch_fails(self):
        client = _catalog_client(side_effect=RuntimeError("catalog unavailable"))
        await mm._refresh_provider_catalog(client)
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": GARBAGE_PROVIDER}
        )
        assert any("Invalid provider" in e for e in errors)

    @pytest.mark.asyncio
    async def test_a_transient_failure_does_not_drop_a_good_catalog(self):
        good = _catalog_client()
        await mm._refresh_provider_catalog(good)
        key = mm._provider_catalog_key(good)
        mm._provider_catalog_cache[key]["fetched_at"] -= (
            mm._PROVIDER_CATALOG_TTL_SECONDS + 1
        )  # force a refresh
        await mm._refresh_provider_catalog(
            _catalog_client(side_effect=RuntimeError("catalog unavailable"))
        )
        assert "bedrock" in mm._provider_catalog_cache[key]["providers"]


class TestProviderCatalogCache:
    """One catalog fetch per TTL window, shared across managers."""

    @pytest.mark.asyncio
    async def test_fetch_happens_once_within_ttl(self):
        client = _catalog_client()
        await mm._refresh_provider_catalog(client)
        await mm._refresh_provider_catalog(client)
        await mm._refresh_provider_catalog(client)
        client.get_ai_model_providers.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_is_not_keyed_on_the_caller_identity(self):
        """Two per-request clients for one tenant share a fetch; the key is the tenant."""
        client_a = _catalog_client()
        client_b = _catalog_client()
        await mm._refresh_provider_catalog(client_a)
        await mm._refresh_provider_catalog(client_b)
        client_b.get_ai_model_providers.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_ttl_refetches(self):
        client = _catalog_client()
        await mm._refresh_provider_catalog(client)
        key = mm._provider_catalog_key(client)
        mm._provider_catalog_cache[key]["fetched_at"] -= mm._PROVIDER_CATALOG_TTL_SECONDS + 1
        await mm._refresh_provider_catalog(client)
        assert client.get_ai_model_providers.call_count == 2

    @pytest.mark.asyncio
    async def test_malformed_envelope_leaves_the_baseline_in_place(self):
        """The fallback scan's envelope is unusable and the endpoint is down."""
        client = _catalog_client(
            response={"unexpected": "shape"},
            providers_error=RuntimeError("providers endpoint unavailable"),
        )
        await mm._refresh_provider_catalog(client)
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": "OPENAI"}
        )
        assert not any("Invalid provider" in e for e in errors), errors


class TestProviderListReadsTheProvidersEndpoint:
    """The catalog's providers endpoint answers the allowlist; the scan is a fallback.

    The endpoint returns the sorted distinct provider names in one call, so the
    page scan it replaces only has to cover an upstream that does not serve that
    path yet.
    """

    @pytest.mark.asyncio
    async def test_the_endpoint_is_the_only_read_when_it_answers(self):
        client = _catalog_client()
        providers = await mm._refresh_provider_catalog(client)
        assert "bedrock" in providers
        client.get_ai_model_providers.assert_called_once_with()
        client.get_ai_models.assert_not_called()

    @pytest.mark.asyncio
    async def test_endpoint_names_are_normalized(self):
        """Names arrive as the platform persists them; comparisons are lower-case."""
        catalog_only = "providers_endpoint_only"
        assert catalog_only not in mm._STATIC_PROVIDER_BASELINE
        client = _catalog_client(providers=[f"  {catalog_only.upper()}  ", "", "OPENAI"])
        assert await mm._fetch_catalog_providers(client) == frozenset(
            {catalog_only, "openai"}
        )

    @pytest.mark.asyncio
    async def test_a_failing_endpoint_falls_back_to_the_model_scan(self):
        client = _catalog_client(providers_error=RuntimeError("no such path"))
        providers = await mm._refresh_provider_catalog(client)
        assert "bedrock" in providers
        assert client.get_ai_models.call_args.kwargs == {
            "page": 0,
            "size": mm._PROVIDER_CATALOG_PAGE_SIZE,
        }

    @pytest.mark.asyncio
    async def test_a_non_array_answer_falls_back_to_the_model_scan(self):
        """A HAL page would otherwise contribute its envelope keys as providers."""
        client = _catalog_client(providers={"_embedded": {"aIModelResourceList": []}})
        providers = await mm._fetch_catalog_providers(client)
        assert "_embedded" not in providers
        assert "bedrock" in providers

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_not_second_guessed(self):
        """No providers is a legitimate answer for a team with no models."""
        client = _catalog_client(providers=[])
        assert await mm._fetch_catalog_providers(client) == frozenset()
        client.get_ai_models.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_reads_failing_leaves_the_baseline_in_place(self):
        client = _catalog_client(side_effect=RuntimeError("catalog unavailable"))
        assert await mm._fetch_catalog_providers(client) == frozenset()
        errors = await MeteringTransactionManager()._validate_string_fields(
            {**VALID_TX, "provider": "OPENAI"}
        )
        assert not any("Invalid provider" in e for e in errors), errors


class TestOnMissTargetedProviderLookup:
    """A provider missing from the cached provider list is still priced by the catalog.

    The list the write path validates against can lag: the fallback scan reads
    one page and the listing endpoint truncates pages to ~100 models, and either
    read is at most one TTL window old. Membership alone would therefore reject a
    legitimate provider, so on a miss the write path asks the catalog directly,
    using the server-side provider filter.
    """

    @pytest.mark.asyncio
    async def test_the_catalog_provider_list_cannot_see_the_provider(self):
        """Guard the premise: the provider is in neither the baseline nor the list."""
        assert DEEP_CATALOG_PROVIDER not in mm._STATIC_PROVIDER_BASELINE
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        providers = await mm._refresh_provider_catalog(client)
        assert DEEP_CATALOG_PROVIDER not in providers

    @pytest.mark.asyncio
    async def test_validate_accepts_a_filter_only_provider(self):
        mgmt = MeteringManagement()
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
        assert "Validation Successful" in result[0].text, result[0].text

    @pytest.mark.asyncio
    async def test_submit_dry_run_accepts_a_filter_only_provider(self):
        mgmt = MeteringManagement()
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "submit_ai_transaction",
                {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER, "dry_run": True},
            )
        assert "Validation Successful" in result[0].text, result[0].text

    @pytest.mark.asyncio
    async def test_lookup_is_one_targeted_normalized_page(self):
        """One model, one page, provider normalized to the catalog's lower case."""
        mgmt = MeteringManagement()
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": f"  {DEEP_CATALOG_PROVIDER.upper()}  "}
            )
        lookups = _filtered_calls(client)
        assert len(lookups) == 1, client.get_ai_models.call_args_list
        assert lookups[0].kwargs == {
            "page": 0,
            "size": 1,
            "provider": DEEP_CATALOG_PROVIDER,
        }

    @pytest.mark.asyncio
    async def test_a_hit_is_cached_so_the_next_request_does_not_look_up_again(self):
        mgmt = MeteringManagement()
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            first = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
            second = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
        assert "Validation Successful" in first[0].text, first[0].text
        assert "Validation Successful" in second[0].text, second[0].text
        assert len(_filtered_calls(client)) == 1

    @pytest.mark.asyncio
    async def test_a_hit_does_not_leak_to_another_tenant(self):
        mgmt = MeteringManagement()
        tenant_a = _catalog_client(team_id="team-a", filter_hits=[DEEP_CATALOG_PROVIDER])
        tenant_b = _catalog_client(team_id="team-b")

        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=tenant_a)
        ):
            allowed = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
        assert "Validation Successful" in allowed[0].text, allowed[0].text

        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=tenant_b)
        ):
            refused = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
        assert "Validation Failed" in refused[0].text, refused[0].text
        assert len(_filtered_calls(tenant_b)) == 1

    @pytest.mark.asyncio
    async def test_unknown_provider_is_still_rejected_with_the_steer(self):
        mgmt = MeteringManagement()
        client = _catalog_client(filter_hits=[DEEP_CATALOG_PROVIDER])
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": GARBAGE_PROVIDER}
            )
        text = result[0].text
        assert "Validation Failed" in text, text
        assert GARBAGE_PROVIDER in text
        assert "get_supported_providers()" in text

    @pytest.mark.asyncio
    async def test_a_miss_is_not_cached(self):
        """A provider the platform adds a moment later must not stay rejected."""
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            await mgmt.handle_action("validate", {**VALID_TX, "provider": GARBAGE_PROVIDER})
            await mgmt.handle_action("validate", {**VALID_TX, "provider": GARBAGE_PROVIDER})
        assert len(_filtered_calls(client)) == 2

    @pytest.mark.asyncio
    async def test_an_accepted_provider_never_triggers_a_lookup(self):
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action("validate", {**VALID_TX, "provider": "bedrock"})
        assert "Validation Successful" in result[0].text, result[0].text
        assert _filtered_calls(client) == []

    @pytest.mark.asyncio
    async def test_a_failing_lookup_falls_back_to_the_rejection(self):
        mgmt = MeteringManagement()
        client = _catalog_client(filter_error=RuntimeError("catalog unavailable"))
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": DEEP_CATALOG_PROVIDER}
            )
        text = result[0].text
        assert "Validation Failed" in text, text
        assert "get_supported_providers()" in text


class TestProviderCatalogCacheIsTenantKeyed:
    """One worker serves many tenants, each with its own per-request client.

    A process-wide entry would hand the first caller's catalog to every other
    caller inside the TTL window, so the cache is keyed on the client identity
    that actually determines the catalog contents.
    """

    PRIVATE_PROVIDER = "tenant_a_only_provider"

    @pytest.mark.asyncio
    async def test_each_tenant_fetches_its_own_catalog(self):
        tenant_a = _catalog_client(team_id="team-a")
        tenant_b = _catalog_client(team_id="team-b")
        await mm._refresh_provider_catalog(tenant_a)
        await mm._refresh_provider_catalog(tenant_b)
        tenant_a.get_ai_model_providers.assert_called_once()
        tenant_b.get_ai_model_providers.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_tenants_catalog_does_not_widen_anothers(self):
        tenant_a = _catalog_client(
            response=_catalog_response(CATALOG_PROVIDERS + [self.PRIVATE_PROVIDER]),
            team_id="team-a",
        )
        tenant_b = _catalog_client(team_id="team-b")
        mgr = MeteringTransactionManager()

        await mm._refresh_provider_catalog(tenant_a)
        for_a = await mgr._validate_string_fields(
            {**VALID_TX, "provider": self.PRIVATE_PROVIDER}
        )
        assert not any("Invalid provider" in e for e in for_a), for_a

        await mm._refresh_provider_catalog(tenant_b)
        for_b = await mgr._validate_string_fields(
            {**VALID_TX, "provider": self.PRIVATE_PROVIDER}
        )
        assert any("Invalid provider" in e for e in for_b), for_b

    @pytest.mark.asyncio
    async def test_base_url_discriminates_the_key(self):
        """Same team id against two deployments is two different catalogs."""
        prod = _catalog_client(team_id="same-team", base_url="https://api.revenium.test")
        dev = _catalog_client(team_id="same-team", base_url="https://api.dev.revenium.test")
        await mm._refresh_provider_catalog(prod)
        await mm._refresh_provider_catalog(dev)
        prod.get_ai_model_providers.assert_called_once()
        dev.get_ai_model_providers.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_entries_are_pruned_on_insert(self):
        """The key space is per tenant, so stale entries must not accumulate."""
        stale = _catalog_client(team_id="team-stale")
        await mm._refresh_provider_catalog(stale)
        stale_key = mm._provider_catalog_key(stale)
        mm._provider_catalog_cache[stale_key]["fetched_at"] -= (
            mm._PROVIDER_CATALOG_TTL_SECONDS + 1
        )

        fresh = _catalog_client(team_id="team-fresh")
        await mm._refresh_provider_catalog(fresh)

        assert stale_key not in mm._provider_catalog_cache
        assert mm._provider_catalog_key(fresh) in mm._provider_catalog_cache

    @pytest.mark.asyncio
    async def test_submit_does_not_reuse_another_tenants_catalog(self):
        """End-to-end: tenant B's submit is validated against tenant B's catalog."""
        mgmt = MeteringManagement()
        tenant_a = _catalog_client(
            response=_catalog_response(CATALOG_PROVIDERS + [self.PRIVATE_PROVIDER]),
            team_id="team-a",
        )
        tenant_b = _catalog_client(team_id="team-b")

        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=tenant_a)
        ):
            allowed = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": self.PRIVATE_PROVIDER}
            )
        assert "Validation Successful" in allowed[0].text, allowed[0].text

        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=tenant_b)
        ):
            refused = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": self.PRIVATE_PROVIDER}
            )
        assert "Validation Failed" in refused[0].text, refused[0].text
        assert "get_supported_providers()" in refused[0].text


class TestSubmitActionUsesTheCatalog:
    """End-to-end through the dispatcher: submit accepts a catalog provider."""

    @pytest.mark.asyncio
    async def test_submit_dry_run_accepts_bedrock(self):
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "submit_ai_transaction",
                {**VALID_TX, "provider": "bedrock", "dry_run": True},
            )
        text = result[0].text
        assert "Validation Successful" in text, text
        client.get_ai_model_providers.assert_called_once()
        client.get_ai_models.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_dry_run_rejects_garbage(self):
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "submit_ai_transaction",
                {**VALID_TX, "provider": GARBAGE_PROVIDER, "dry_run": True},
            )
        text = result[0].text
        assert "get_supported_providers()" in text, text


class TestValidateActionUsesTheCatalog:
    """End-to-end through the dispatcher: validate accepts a catalog provider."""

    @pytest.mark.asyncio
    async def test_validate_action_accepts_bedrock(self):
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": "bedrock"}
            )
        text = result[0].text
        assert "Validation Successful" in text, text
        client.get_ai_model_providers.assert_called_once()
        client.get_ai_models.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_action_rejects_garbage(self):
        mgmt = MeteringManagement()
        client = _catalog_client()
        with _patch_response_cache(), patch.object(
            mgmt, "get_client", new=AsyncMock(return_value=client)
        ):
            result = await mgmt.handle_action(
                "validate", {**VALID_TX, "provider": GARBAGE_PROVIDER}
            )
        text = result[0].text
        assert "Validation Failed" in text, text
        assert "get_supported_providers()" in text
