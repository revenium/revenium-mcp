"""BACK-4840: an update made while the platform still serves the pre-write copy keeps the earlier write.

The platform's get-by-id serves the record as it was before a PUT for 25 to 30 s.
`LaggingClient` reproduces that: after a PUT, its next reads keep returning the
copy from before the first write of the window, while its PUT answer echoes
what it stored, as the platform's does.
"""

import asyncio
from typing import Any, Callable, Dict, FrozenSet, List, Optional

import pytest

from src.revenium_mcp_server.auth.claims_middleware import _current_tenant
from src.revenium_mcp_server.auth.tenant_context import TenantContext
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
from src.revenium_mcp_server.common.recent_writes import (
    RECENT_WRITE_MAX_CHAIN,
    RecentWrites,
    writer_scope,
)
from src.revenium_mcp_server.common.update_configs import UpdateConfigs

LAGGING_READS = 5


class LaggingClient:
    """Stores every PUT at once but keeps serving the pre-write copy for a few reads."""

    team_id = "team_1"

    class auth_config:
        tenant_id = "tenant_1"
        team_id = "team_1"

    def __init__(
        self,
        stored: Dict[str, Any],
        lagging_reads: int = LAGGING_READS,
        ignored_fields: FrozenSet[str] = frozenset(),
        echoes_record: bool = True,
        stores_instead: Optional[Dict[str, Any]] = None,
    ):
        self.committed = dict(stored)
        self._lagging_reads = lagging_reads
        self._ignored_fields = ignored_fields
        self._echoes_record = echoes_record
        self._stores_instead = stores_instead or {}
        self._served = dict(stored)
        self._reads_left_stale = 0
        self.put_bodies: List[Dict[str, Any]] = []

    async def _get(self, resource_id: str) -> Dict[str, Any]:
        await asyncio.sleep(0)
        if self._reads_left_stale > 0:
            self._reads_left_stale -= 1
            return dict(self._served)
        return dict(self.committed)

    async def _put(self, resource_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.put_bodies.append(body)
        if self._reads_left_stale == 0:
            self._served = dict(self.committed)
        self._reads_left_stale = self._lagging_reads
        stored = {field: value for field, value in body.items() if field not in self._ignored_fields}
        self.committed = {**self.committed, **stored, **self._stores_instead}
        return dict(self.committed) if self._echoes_record else {"id": resource_id}

    def serve(self, **fields: Any) -> None:
        """Let the lagging reads catch up to some of the writes, as the platform's do over time."""
        self._served.update(fields)

    def __getattr__(self, name: str):
        if name.startswith("get_") and name.endswith("_by_id"):
            return self._get
        if name.startswith("update_"):
            return self._put
        raise AttributeError(name)


def _ref(resource_id: str) -> Dict[str, Any]:
    return {"id": resource_id, "resourceType": "x", "label": "x"}


RESOURCES: Dict[str, Callable[[Any], Any]] = {
    "product": UpdateConfigs.create_products_config,
    "source": UpdateConfigs.create_sources_config,
    "organization": lambda client: UpdateConfigs.create_customers_config(client, "organization"),
    "metering_element": UpdateConfigs.create_metering_elements_config,
    "subscription": UpdateConfigs.create_subscriptions_config,
}

STORED: Dict[str, Dict[str, Any]] = {
    "product": {
        "id": "prod_1",
        "name": "Old name",
        "description": "Old description",
        "version": "1.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {"type": "SUBSCRIPTION", "tiers": [{"name": "Base", "unitAmount": "1"}]},
        "owner": _ref("own_1"),
        "team": _ref("team_1"),
    },
    "source": {
        "id": "src_1",
        "name": "Old name",
        "description": "Old description",
        "version": "1.0",
        "type": "API",
        "owner": _ref("own_1"),
        "team": _ref("team_1"),
    },
    "organization": {"id": "org_1", "name": "Old name", "description": "Old description"},
    "metering_element": {
        "id": "elem_1",
        "name": "Old name",
        "description": "Old description",
        "team": _ref("team_1"),
    },
    "subscription": {
        "id": "subn_1",
        "name": "Old name",
        "description": "Old description",
        "product": _ref("prod_1"),
        "client": {"id": "subr_1", "label": "buyer@example.com"},
    },
}


def _config(resource: str, client: LaggingClient):
    return RESOURCES[resource](client)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", sorted(RESOURCES))
async def test_two_quick_updates_of_different_fields_both_end_up_stored(resource):
    client = LaggingClient(STORED[resource])
    config = _config(resource, client)
    record_id = STORED[resource]["id"]
    handler = PartialUpdateHandler()

    first = await handler.update_with_merge(record_id, {"name": "New name"}, config)
    second = await handler.update_with_merge(record_id, {"description": "New description"}, config)

    second_body = client.put_bodies[1]
    assert second_body["name"] == "New name"
    assert second_body["description"] == "New description"
    assert first["name"] == "New name"
    assert second["name"] == "New name"
    assert second["description"] == "New description"
    assert client.committed["name"] == "New name"
    assert client.committed["description"] == "New description"


@pytest.mark.asyncio
async def test_three_quick_updates_keep_every_earlier_write():
    client = LaggingClient(STORED["source"])
    config = _config("source", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("src_1", {"name": "New name"}, config)
    await handler.update_with_merge("src_1", {"description": "New description"}, config)
    await handler.update_with_merge("src_1", {"version": "2.0"}, config)

    assert client.put_bodies[2]["name"] == "New name"
    assert client.put_bodies[2]["description"] == "New description"
    assert client.put_bodies[2]["version"] == "2.0"


@pytest.mark.asyncio
async def test_a_quick_second_value_for_the_same_field_wins():
    client = LaggingClient(STORED["product"])
    config = _config("product", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("prod_1", {"name": "First"}, config)
    await handler.update_with_merge("prod_1", {"name": "Second"}, config)

    assert client.put_bodies[1]["name"] == "Second"
    assert client.committed["name"] == "Second"


@pytest.mark.asyncio
async def test_a_partial_plan_written_earlier_is_kept_when_a_later_update_changes_the_name():
    client = LaggingClient(STORED["product"])
    config = _config("product", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("prod_1", {"plan": {"currency": "EUR"}}, config)
    await handler.update_with_merge("prod_1", {"name": "New name"}, config)

    plan = client.put_bodies[1]["plan"]
    assert plan["currency"] == "EUR"
    assert plan["tiers"] == STORED["product"]["plan"]["tiers"]


@pytest.mark.asyncio
async def test_earlier_nested_edits_survive_a_later_nested_edit_and_a_name_only_update():
    client = LaggingClient(STORED["product"], lagging_reads=100)
    config = _config("product", client)
    handler = PartialUpdateHandler()
    new_tiers = [{"name": "Pro", "unitAmount": "5"}]

    await handler.update_with_merge("prod_1", {"plan": {"currency": "EUR"}}, config)
    await handler.update_with_merge("prod_1", {"plan": {"tiers": new_tiers}}, config)
    await handler.update_with_merge("prod_1", {"name": "New name"}, config)

    third_body = client.put_bodies[2]
    assert third_body["name"] == "New name"
    assert third_body["plan"]["currency"] == "EUR"
    assert third_body["plan"]["tiers"] == new_tiers
    assert client.committed["plan"]["currency"] == "EUR"


@pytest.mark.asyncio
async def test_concurrent_updates_of_one_record_both_end_up_stored():
    client = LaggingClient(STORED["organization"])
    config = _config("organization", client)
    handler = PartialUpdateHandler()

    await asyncio.gather(
        handler.update_with_merge("org_1", {"name": "New name"}, config),
        handler.update_with_merge("org_1", {"description": "New description"}, config),
    )

    assert client.committed["name"] == "New name"
    assert client.committed["description"] == "New description"


@pytest.mark.asyncio
async def test_a_value_changed_elsewhere_after_the_write_is_not_overwritten():
    client = LaggingClient(STORED["source"], lagging_reads=0)
    config = _config("source", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("src_1", {"name": "New name"}, config)
    client.committed["name"] = "Renamed elsewhere"
    await handler.update_with_merge("src_1", {"description": "New description"}, config)

    assert client.put_bodies[1]["name"] == "Renamed elsewhere"


@pytest.mark.asyncio
async def test_a_remembered_write_expires_after_the_ttl_and_a_still_stale_read_is_merged_as_read():
    now = [1000.0]
    memory = RecentWrites(ttl_seconds=120.0, clock=lambda: now[0])
    client = LaggingClient(STORED["source"], lagging_reads=100)
    config = _config("source", client)
    handler = PartialUpdateHandler(recent_writes=memory)

    await handler.update_with_merge("src_1", {"name": "New name"}, config)
    now[0] += 121.0
    await handler.update_with_merge("src_1", {"description": "New description"}, config)

    assert client.put_bodies[1]["name"] == "Old name"


def test_memory_keeps_at_most_its_record_cap():
    memory = RecentWrites(max_records=2)
    scope = _scope("team_a")
    for index in range(5):
        memory.remember(scope, f"source:src_{index}", {"name": "x"}, read_before={"name": "old"})

    assert len(memory) == 2
    assert memory.unseen_fields(scope, "source:src_0", {"name": "old"}) == {}
    assert memory.unseen_fields(scope, "source:src_4", {"name": "old"}) == {"name": "x"}


def test_many_quick_writes_of_one_field_keep_the_original_and_the_most_recent_values():
    memory = RecentWrites()
    scope = _scope("team_a")
    record = "source:src_1"
    written = [f"name {index}" for index in range(RECENT_WRITE_MAX_CHAIN * 2)]
    for value in written:
        memory.remember(scope, record, {"name": value}, read_before={"name": "Old name"})

    oldest_kept = written[-(RECENT_WRITE_MAX_CHAIN - 1)]
    assert memory.unseen_fields(scope, record, {"name": "Old name"}) == {"name": written[-1]}
    assert memory.unseen_fields(scope, record, {"name": oldest_kept}) == {"name": written[-1]}
    assert memory.unseen_fields(scope, record, {"name": written[0]}) == {}


@pytest.mark.asyncio
async def test_quick_writes_filling_the_chain_cap_still_repair_a_read_showing_the_original():
    client = LaggingClient(STORED["source"], lagging_reads=100)
    config = _config("source", client)
    handler = PartialUpdateHandler()
    names = [f"name {index}" for index in range(RECENT_WRITE_MAX_CHAIN)]

    for name in names:
        await handler.update_with_merge("src_1", {"name": name}, config)
    await handler.update_with_merge("src_1", {"description": "New description"}, config)

    assert client.put_bodies[-1]["name"] == names[-1]
    assert client.committed["name"] == names[-1]


@pytest.mark.asyncio
async def test_a_reverted_name_is_not_undone_when_the_read_moves_to_the_intermediate_value():
    client = LaggingClient(STORED["product"], lagging_reads=100)
    config = _config("product", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("prod_1", {"name": "Interim"}, config)
    await handler.update_with_merge("prod_1", {"name": "Old name"}, config)
    await handler.update_with_merge("prod_1", {"version": "2.0"}, config)
    client.serve(name="Interim")
    await handler.update_with_merge("prod_1", {"description": "New description"}, config)

    assert [body["name"] for body in client.put_bodies] == [
        "Interim",
        "Old name",
        "Old name",
        "Old name",
    ]
    assert client.committed["name"] == "Old name"


def test_a_read_that_caught_up_retires_every_earlier_value():
    memory = RecentWrites()
    scope = _scope("team_a")
    record = "source:src_1"
    memory.remember(scope, record, {"name": "First"}, read_before={"name": "Old name"})
    memory.remember(scope, record, {"name": "Second"}, read_before={"name": "Old name"})

    assert memory.unseen_fields(scope, record, {"name": "Old name"}) == {"name": "Second"}
    assert memory.unseen_fields(scope, record, {"name": "Second"}) == {}
    assert memory.unseen_fields(scope, record, {"name": "Old name"}) == {"name": "Second"}
    memory.observe_read(scope, record, {"name": "Second"})
    assert memory.unseen_fields(scope, record, {"name": "Old name"}) == {}
    assert memory.unseen_fields(scope, record, {"name": "First"}) == {}


@pytest.mark.asyncio
async def test_a_preview_never_retires_earlier_values_but_a_locked_update_does():
    memory = RecentWrites()
    client = LaggingClient({**STORED["source"], "name": "Second"}, lagging_reads=0)
    config = _config("source", client)
    handler = PartialUpdateHandler(recent_writes=memory)
    record = "source:src_1"
    memory.remember(writer_scope(), record, {"name": "First"}, read_before={"name": "Old name"})
    memory.remember(writer_scope(), record, {"name": "Second"}, read_before={"name": "Old name"})

    await handler.build_update_payload("src_1", {"description": "Previewed"}, config)
    assert memory.known_values(writer_scope(), record, "name") == ("Old name", "First", "Second")

    await handler.update_with_merge("src_1", {"description": "Updated"}, config)
    assert memory.known_values(writer_scope(), record, "name") == ("Second",)


def test_only_fields_the_read_names_are_remembered():
    memory = RecentWrites()
    scope = _scope("team_a")
    stored = {"name": "Old name", "parent": _ref("org_a")}

    memory.remember(
        scope, "organization:org_1", {"name": "New name", "parentId": "org_b"}, read_before=stored
    )

    assert memory.unseen_fields(scope, "organization:org_1", stored) == {"name": "New name"}


@pytest.mark.asyncio
async def test_a_caller_field_the_body_drops_is_not_remembered():
    stored = {**STORED["source"], "updated": "2026-01-01"}
    memory = RecentWrites()
    client = LaggingClient(stored)
    handler = PartialUpdateHandler(recent_writes=memory)

    await handler.update_with_merge(
        "src_1", {"name": "New name", "updated": "2026-10-19"}, _config("source", client)
    )

    assert "updated" not in client.put_bodies[0]
    assert memory.unseen_fields(writer_scope(), "source:src_1", stored) == {"name": "New name"}


@pytest.mark.asyncio
async def test_a_parent_moved_elsewhere_is_not_undone_by_a_remembered_parent_id():
    stored = {**STORED["organization"], "parent": _ref("org_a")}
    client = LaggingClient(stored, lagging_reads=0, ignored_fields=frozenset({"parentId"}))
    config = _config("organization", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("org_1", {"parentId": "org_b"}, config)
    client.committed["parent"] = _ref("org_c")
    await handler.update_with_merge("org_1", {"name": "New name"}, config)

    assert client.put_bodies[1]["parentId"] == "org_c"


@pytest.mark.asyncio
async def test_reads_catching_up_through_earlier_writes_never_bring_them_back():
    client = LaggingClient(STORED["product"], lagging_reads=100)
    config = _config("product", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("prod_1", {"name": "First"}, config)
    await handler.update_with_merge("prod_1", {"name": "Second"}, config)
    client.serve(name="First")
    await handler.update_with_merge("prod_1", {"description": "New description"}, config)
    client.serve(name="Second")
    await handler.update_with_merge("prod_1", {"version": "2.0"}, config)

    assert [body["name"] for body in client.put_bodies] == ["First", "Second", "Second", "Second"]
    assert client.committed["name"] == "Second"


SUBSCRIPTION_NAMING_EMAIL = {**STORED["subscription"], "clientEmailAddress": "buyer@example.com"}


@pytest.mark.asyncio
async def test_a_remembered_email_is_dropped_when_the_caller_changes_the_subscriber():
    client = LaggingClient(SUBSCRIPTION_NAMING_EMAIL)
    config = _config("subscription", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("subn_1", {"clientEmailAddress": "new@example.com"}, config)
    await handler.update_with_merge("subn_1", {"subscriberId": "subr_2"}, config)

    second_body = client.put_bodies[1]
    assert second_body["subscriberId"] == "subr_2"
    assert "clientEmailAddress" not in second_body


@pytest.mark.asyncio
async def test_a_remembered_email_is_kept_on_a_name_only_update():
    client = LaggingClient(SUBSCRIPTION_NAMING_EMAIL)
    config = _config("subscription", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("subn_1", {"clientEmailAddress": "new@example.com"}, config)
    await handler.update_with_merge("subn_1", {"name": "New name"}, config)

    second_body = client.put_bodies[1]
    assert second_body["clientEmailAddress"] == "new@example.com"
    assert second_body["subscriberId"] == "subr_1"


@pytest.mark.asyncio
async def test_a_field_the_write_answer_shows_unchanged_fails_the_update_naming_it():
    client = LaggingClient(STORED["metering_element"], ignored_fields=frozenset({"description"}))
    config = _config("metering_element", client)

    with pytest.raises(ToolError) as refusal:
        await PartialUpdateHandler().update_with_merge(
            "elem_1", {"name": "New name", "description": "New description"}, config
        )

    message = refusal.value.message
    assert "description (sent 'New description', stored 'Old description')" in message
    assert "name (" not in message


@pytest.mark.asyncio
async def test_a_field_the_answer_omits_is_checked_against_one_read_back():
    client = LaggingClient(
        STORED["organization"],
        lagging_reads=0,
        echoes_record=False,
        stores_instead={"description": "New descr"},
    )
    config = _config("organization", client)

    with pytest.raises(ToolError) as refusal:
        await PartialUpdateHandler().update_with_merge(
            "org_1", {"description": "New description"}, config
        )

    assert "description (sent 'New description', stored 'New descr')" in (
        refusal.value.message
    )


@pytest.mark.asyncio
async def test_a_later_update_keeps_the_value_the_read_back_showed_was_stored_instead():
    client = LaggingClient(
        STORED["organization"],
        lagging_reads=0,
        echoes_record=False,
        stores_instead={"description": "Stored elsewhere"},
    )
    config = _config("organization", client)
    read_descriptions = ["Old description", "Stored elsewhere", "Old description", "Stored elsewhere"]
    reads = iter(read_descriptions)
    reads_served: List[str] = []

    async def lagging_after_the_read_back(resource_id: str) -> Dict[str, Any]:
        reads_served.append(next(reads))
        return {**STORED["organization"], "description": reads_served[-1]}

    config.get_method = lagging_after_the_read_back
    handler = PartialUpdateHandler()

    with pytest.raises(ToolError):
        await handler.update_with_merge("org_1", {"description": "New description"}, config)
    await handler.update_with_merge("org_1", {"name": "New name"}, config)

    assert client.put_bodies[1]["description"] == "Stored elsewhere"
    assert reads_served == read_descriptions


@pytest.mark.asyncio
async def test_a_later_update_keeps_the_value_the_write_answer_showed_was_stored_instead():
    client = LaggingClient(STORED["organization"], lagging_reads=100)
    config = _config("organization", client)
    puts = [0]

    async def answers_another_name_on_the_second_write(
        resource_id: str, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        answer = await client._put(resource_id, body)
        puts[0] += 1
        return {**answer, "name": "Stored elsewhere"} if puts[0] == 2 else answer

    config.update_method = answers_another_name_on_the_second_write
    handler = PartialUpdateHandler()

    await handler.update_with_merge("org_1", {"name": "First"}, config)
    with pytest.raises(ToolError):
        await handler.update_with_merge("org_1", {"name": "Second"}, config)
    await handler.update_with_merge("org_1", {"description": "New description"}, config)

    assert client.put_bodies[2]["name"] == "Stored elsewhere"


@pytest.mark.asyncio
async def test_a_read_back_showing_an_earlier_write_of_the_same_field_is_a_slow_read():
    client = LaggingClient(STORED["organization"], echoes_record=False)
    config = _config("organization", client)
    read_descriptions = [
        "Old description",
        "Old description",
        "Old description",
        "First",
        "First",
        "Second",
    ]
    reads = iter(read_descriptions)
    reads_served: List[str] = []

    async def read_back_lags_one_write(resource_id: str) -> Dict[str, Any]:
        reads_served.append(next(reads))
        return {**STORED["organization"], "description": reads_served[-1]}

    config.get_method = read_back_lags_one_write
    handler = PartialUpdateHandler()

    await handler.update_with_merge("org_1", {"description": "First"}, config)
    answer = await handler.update_with_merge("org_1", {"description": "Second"}, config)
    await handler.update_with_merge("org_1", {"name": "New name"}, config)

    assert answer == {"id": "org_1"}
    assert client.put_bodies[2]["description"] == "Second"
    assert reads_served == read_descriptions


@pytest.mark.asyncio
async def test_a_read_back_still_showing_the_old_value_is_not_taken_for_a_dropped_field():
    client = LaggingClient(STORED["organization"], echoes_record=False)
    config = _config("organization", client)

    answer = await PartialUpdateHandler().update_with_merge(
        "org_1", {"description": "New description"}, config
    )

    assert answer == {"id": "org_1"}


@pytest.mark.asyncio
async def test_a_failed_read_back_after_an_applied_write_answers_success_and_remembers_it():
    client = LaggingClient(STORED["organization"], echoes_record=False)
    config = _config("organization", client)
    reads: List[str] = []

    async def read_back_fails_once(resource_id: str) -> Dict[str, Any]:
        reads.append(resource_id)
        if len(reads) == 2:
            raise ConnectionError("read timed out")
        return await client._get(resource_id)

    config.get_method = read_back_fails_once
    handler = PartialUpdateHandler()

    answer = await handler.update_with_merge("org_1", {"description": "New description"}, config)
    await handler.update_with_merge("org_1", {"name": "New name"}, config)

    assert answer == {"id": "org_1"}
    assert client.put_bodies[1]["description"] == "New description"


@pytest.mark.asyncio
async def test_no_read_back_when_the_write_answer_carries_every_field():
    client = LaggingClient(STORED["source"], lagging_reads=0)
    config = _config("source", client)
    reads: List[str] = []
    original_get = client._get

    async def counting_get(resource_id: str) -> Dict[str, Any]:
        reads.append(resource_id)
        return await original_get(resource_id)

    config.get_method = counting_get
    await PartialUpdateHandler().update_with_merge("src_1", {"name": "New name"}, config)

    assert reads == ["src_1"]


def _scope(team_id: str):
    from src.revenium_mcp_server.auth.tenant_scope import TenantScope

    return TenantScope(team_id=team_id, tenant_id="", base_url="https://api.example")


def _tenant(team_id: str) -> TenantContext:
    return TenantContext(team_id=team_id, api_key="rev_test_key_0123456789", base_url="https://api.example")


async def _update_as(
    tenant: TenantContext, client: LaggingClient, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    token = _current_tenant.set(tenant)
    try:
        return await PartialUpdateHandler().update_with_merge(
            "prod_1", fields, _config("product", client)
        )
    finally:
        _current_tenant.reset(token)


@pytest.mark.asyncio
async def test_one_organizations_write_never_reaches_anothers_record_with_the_same_id(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    client_a = LaggingClient(STORED["product"])
    client_b = LaggingClient(STORED["product"])

    await _update_as(_tenant("team_a"), client_a, {"name": "A's new name"})
    await _update_as(_tenant("team_b"), client_b, {"description": "B's new description"})
    await _update_as(_tenant("team_a"), client_a, {"description": "A's new description"})

    assert client_b.put_bodies[0]["name"] == "Old name"
    assert client_a.put_bodies[1]["name"] == "A's new name"


@pytest.mark.asyncio
async def test_without_a_tenant_context_on_the_hosted_server_nothing_is_remembered(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "api_key")
    client = LaggingClient(STORED["source"])
    config = _config("source", client)
    handler = PartialUpdateHandler()

    await handler.update_with_merge("src_1", {"name": "New name"}, config)
    await handler.update_with_merge("src_1", {"description": "New description"}, config)

    assert client.put_bodies[1]["name"] == "Old name"
