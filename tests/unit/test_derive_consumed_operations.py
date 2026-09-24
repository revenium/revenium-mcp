"""Pin the call-site extractor behind `invoked_methods` (BACK-3101).

`specs/openapi/consumed-operations.json` carries two method lists: `methods`,
what the spec declares for a path, and `invoked_methods`, what `client.py`
actually calls on it. The second exists because the first was read as call
evidence and produced drift tickets about writes the MCP does not make.

That only holds while the extractor reads the call shapes the client really
uses, and refuses to guess at the ones it cannot read. Both halves are pinned
here: every supported shape, and the unsupported ones that must yield nothing
rather than an invented call site.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "derive_consumed_operations.py"
if not SCRIPT.exists():
    pytest.skip(
        "scripts/derive_consumed_operations.py is an internal-only asset that the public "
        "export leaves out; nothing to test without it",
        allow_module_level=True,
    )


def _load_module() -> Any:
    """Import the script by path; `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("derive_consumed_operations", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


derive_mod = _load_module()


@pytest.fixture()
def extract(tmp_path, monkeypatch):
    """Run `collect_invoked_methods` over a source snippet, with a stub registry."""

    def _extract(source: str, registry: dict[str, set[str]] | None = None):
        module = tmp_path / "client_snippet.py"
        module.write_text(source, encoding="utf-8")
        return derive_mod.collect_invoked_methods(module, registry or {})

    return _extract


def _readable(found: dict[str, set[str]]) -> dict[str, set[str]]:
    """Render SLOT sentinels back to `{}` so assertions read like the file does."""
    return {path.replace(derive_mod.SLOT, "{}"): methods for path, methods in found.items()}


#: (spec, path, verb) the client invokes but the spec never declares, each with
#: the ticket that owns the reconciliation. Mirrors KNOWN_UNDECLARED in
#: test_openapi_contract.py: an entry outliving its gap fails the test too.
KNOWN_UNDECLARED_VERBS = {
    ("hypercurrent", "/v2/api/sources/ai/anomaly", "delete"):
        "BACK-3217 -- bulk anomaly delete (client.py clear_all_anomalies, no id) is not "
        "declared on the anomaly collection path",
    ("hypercurrent", "/v2/api/sources/ai/alert/{id}", "put"):
        "BACK-3217 -- alert update is not declared on the alert-by-id path",
    ("hypercurrent", "/v2/api/sources/ai/alert/{id}", "delete"):
        "BACK-3217 -- alert delete is not declared on the alert-by-id path",
}


class TestSupportedCallShapes:
    """Every way client.py actually puts a request on the wire."""

    def test_literal_path_on_a_verb_wrapper(self, extract):
        found = extract('await self.get("/profitstream/v2/api/products")')
        assert _readable(found) == {"/profitstream/v2/api/products": {"get"}}

    def test_fstring_path_becomes_a_template(self, extract):
        found = extract('await self.delete(f"/profitstream/v2/api/products/{product_id}")')
        assert _readable(found) == {"/profitstream/v2/api/products/{}": {"delete"}}

    def test_one_path_accumulates_every_verb_called_on_it(self, extract):
        found = extract(
            'await self.get("/profitstream/v2/api/agents")\n'
            'await self.post("/profitstream/v2/api/agents", data=body)\n'
        )
        assert _readable(found) == {"/profitstream/v2/api/agents": {"get", "post"}}

    def test_registry_resolver_call_resolves_through_the_registry(self, extract):
        registry = {
            "jobs_roi_summary": {
                "/api/v2/analytics/jobs/roi-summary",
                "/profitstream/v2/api/jobs/roi",
            }
        }
        found = extract('await self.get(get_endpoint_path("jobs_roi_summary"))', registry)
        assert _readable(found) == {
            "/api/v2/analytics/jobs/roi-summary": {"get"},
            "/profitstream/v2/api/jobs/roi": {"get"},
        }

    def test_registry_key_the_registry_does_not_know_yields_nothing(self, extract):
        assert extract('await self.get(get_endpoint_path("no_such_key"))', {}) == {}

    def test_generic_sender_reads_its_explicit_method_argument(self, extract):
        found = extract('await self._request("PUT", "/profitstream/v2/api/tools/x")')
        assert _readable(found) == {"/profitstream/v2/api/tools/x": {"put"}}

    def test_retrying_generic_sender_is_read_the_same_way(self, extract):
        found = extract(
            'await self._request_with_retry("PATCH", f"/profitstream/v2/api/tools/{tool_id}")'
        )
        assert _readable(found) == {"/profitstream/v2/api/tools/{}": {"patch"}}

    def test_endpoint_passed_by_keyword_is_still_read(self, extract):
        found = extract(
            'await self._request("DELETE", endpoint="/profitstream/v2/api/agents/x")\n'
            'await self.get(endpoint="/profitstream/v2/api/users")\n'
        )
        assert _readable(found) == {
            "/profitstream/v2/api/agents/x": {"delete"},
            "/profitstream/v2/api/users": {"get"},
        }

    def test_the_method_argument_is_case_insensitive(self, extract):
        found = extract('await self._request("post", "/profitstream/v2/api/agents")')
        assert _readable(found) == {"/profitstream/v2/api/agents": {"post"}}


class TestShapesTheExtractorRefusesToGuessAt:
    """An invented call site is worse than a missing one.

    `invoked_methods` is the field a reviewer is told to trust over the
    spec-declared list. A shape this extractor cannot read must produce nothing,
    so the gap shows up as a missing verb somebody notices rather than as a
    confident claim about a call the code never makes.
    """

    def test_a_variable_endpoint_yields_nothing(self, extract):
        # This is the verb wrappers' own body: `self._request("GET", endpoint)`.
        # Following it would attribute every verb to every path in the file.
        assert extract('await self._request("GET", endpoint)') == {}

    def test_a_computed_endpoint_yields_nothing(self, extract):
        assert extract('await self.get(base + "/v2/api/products")') == {}
        assert extract('await self.get("/profitstream" + suffix)') == {}

    def test_a_non_literal_method_argument_yields_nothing(self, extract):
        assert extract('await self._request(verb, "/profitstream/v2/api/products")') == {}

    def test_a_method_argument_that_is_not_an_http_verb_yields_nothing(self, extract):
        assert extract('await self._request("FETCH", "/profitstream/v2/api/products")') == {}

    def test_a_verb_on_something_that_is_not_the_client_is_still_read(self, extract):
        # Deliberate: the extractor keys on the attribute name, not the
        # receiver, because client.py's own calls go through several receivers
        # (`self`, `client`, `self.client`). The cost is that a dict `.get` with
        # an API-path-shaped key would be counted -- which is why the path
        # prefixes below are the second filter.
        found = extract('some_mapping.get("/profitstream/v2/api/products")')
        assert _readable(found) == {"/profitstream/v2/api/products": {"get"}}

    def test_strings_that_are_not_api_paths_are_ignored(self, extract):
        assert extract('await self.get("not-a-path")') == {}
        assert extract('await self.get("/internal/health")') == {}

    def test_a_trailing_slash_fragment_is_ignored(self, extract):
        # ast reports the constant half of an f-string on its own; no real
        # endpoint ends in a slash, so it is a fragment, not a call site.
        assert extract('await self.get("/profitstream/v2/api/products/")') == {}


class TestRegistryExtraction:
    """`registry_paths` reads the old/new pairs the analytics routing declares."""

    def test_both_halves_of_an_entry_are_collected(self, tmp_path):
        module = tmp_path / "endpoint_registry.py"
        module.write_text(
            "REGISTRY = {\n"
            '    "cost_by_agent": EndpointConfig(\n'
            '        old_path="/profitstream/v2/api/sources/metrics/ai/cost-by-agent",\n'
            '        new_path="/api/v2/analytics/cost-by-agent",\n'
            "    ),\n"
            '    "unmapped": EndpointConfig(\n'
            '        old_path="/profitstream/v2/api/legacy",\n'
            "        new_path=None,\n"
            "    ),\n"
            "}\n",
            encoding="utf-8",
        )
        found = derive_mod.registry_paths(module)
        assert found["cost_by_agent"] == {
            "/profitstream/v2/api/sources/metrics/ai/cost-by-agent",
            "/api/v2/analytics/cost-by-agent",
        }
        # `new_path=None` contributes nothing rather than a None entry.
        assert found["unmapped"] == {"/profitstream/v2/api/legacy"}

    def test_a_dict_entry_that_is_not_an_endpoint_config_is_skipped(self, tmp_path):
        module = tmp_path / "endpoint_registry.py"
        module.write_text('OTHER = {"key": SomethingElse(old_path="/x")}\n', encoding="utf-8")
        assert derive_mod.registry_paths(module) == {}


class TestAgainstTheRealClient:
    """The shapes above are the shapes the real client.py uses."""

    def test_the_committed_allowlist_matches_a_fresh_derivation(self):
        import json

        allowlist = derive_mod.derive()
        committed = json.loads(derive_mod.ALLOWLIST_PATH.read_text(encoding="utf-8"))
        # The whole document, not just operations: registry_routed_paths feeds
        # the decision-overlap guard and unmatched_call_sites is a reviewed
        # baseline, so either going stale silently would defeat a consumer.
        for key in ("operations", "registry_routed_paths", "unmatched_call_sites"):
            assert allowlist[key] == committed[key], (
                f"specs/openapi/consumed-operations.json is stale under {key!r} -- re-run "
                "`uv run python scripts/derive_consumed_operations.py --write` and read the diff"
            )
        assert set(allowlist) == set(committed), (sorted(allowlist), sorted(committed))

    def test_every_invoked_verb_is_declared_unless_named_here(self):
        """A verb the client invokes that the spec never declares is a finding, not data.

        The extractor merges every verb it sees on a matched path into that
        path's entry, so a mis-attributed call site or an unreviewed write
        against an undocumented operation would otherwise settle into the
        allowlist unnoticed. The two live gaps are pinned by name with their
        ticket; a third fails here, and so does one of these going stale.
        """
        operations = derive_mod.derive()["operations"]
        undeclared = {
            (spec, path, verb)
            for spec, entries in operations.items()
            for path, entry in entries.items()
            for verb in set(entry.get("invoked_methods", [])) - set(entry.get("methods", []))
        }
        assert undeclared == set(KNOWN_UNDECLARED_VERBS), (
            "invoked verbs the spec does not declare changed. New ones need a ticket and an "
            f"entry in KNOWN_UNDECLARED_VERBS; stale ones must be pruned.\n"
            f"unexpected: {sorted(undeclared - set(KNOWN_UNDECLARED_VERBS))}\n"
            f"stale: {sorted(set(KNOWN_UNDECLARED_VERBS) - undeclared)}"
        )

    def test_a_read_only_endpoint_records_only_the_read(self):
        """The case that produced a wrong ticket: declared post, invoked get."""
        operations = derive_mod.derive()["operations"]["hypercurrent"]
        attribution = operations["/v2/api/sessions/{sessionId}/attribution"]
        assert "post" in attribution["methods"], "the spec still declares the write"
        assert attribution["invoked_methods"] == ["get"], attribution

    def test_client_py_parses_and_declares_the_wrappers_this_extractor_reads(self):
        """A rename of the verb wrappers must fail here, not silently empty the field."""
        source = (derive_mod.SRC_DIR / derive_mod.INVOCATION_MODULE).read_text(encoding="utf-8")
        defined = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        }
        for name in derive_mod.VERB_WRAPPERS:
            if name in ("head", "options"):
                continue  # declared for completeness; the client defines no wrapper
            assert name in defined, f"client.py no longer defines a `{name}` wrapper"
        for name in derive_mod.GENERIC_SENDERS:
            assert name in defined, f"client.py no longer defines `{name}`"
