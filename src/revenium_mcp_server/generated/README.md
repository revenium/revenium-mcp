# Generated OpenAPI models

Machine-generated Pydantic v2 models for the two upstream contracts the MCP
consumes. **Never hand-edit anything in this directory** — the next regeneration
overwrites it without warning.

| File | Source contract |
|------|-----------------|
| `hypercurrent_models.py` | `specs/openapi/hypercurrent.json` (the profitstream platform API) |
| `isotope_models.py` | `specs/openapi/isotope.json` (the ClickHouse-backed analytics API) |

## Regenerating

One reproducible, fully offline command — it reads the committed snapshots, never
the network:

```
uv run --extra dev python scripts/generate_openapi_models.py
```

`scripts/generate_openapi_models.py` prunes each snapshot to the operations
listed in `specs/openapi/consumed-operations.json` (plus everything they
reference transitively), runs `datamodel-codegen` over the pruned document, and
prepends the DO-NOT-EDIT header. Output is deterministic: regenerating without a
snapshot change produces a byte-identical file.

To pick up an upstream change, refresh the snapshot first:

```
uv run python scripts/fetch_openapi_specs.py
uv run --extra dev python scripts/generate_openapi_models.py
uv run --extra dev pytest tests/unit/test_openapi_contract.py
```

## Not runtime code

No module under `src/revenium_mcp_server/` imports this package, and none should
in this state. These models exist so `tests/unit/test_openapi_contract.py` can
validate recorded response fixtures against the declared contract. Wiring them
into the client is a separate, deliberate decision — it changes runtime
behavior, since a generated model rejects payloads the current hand-rolled
parsing tolerates.

`datamodel-code-generator` is therefore a **dev-only** dependency
(pyproject `[project.optional-dependencies] dev`). It must never move into
`[project] dependencies`.

## Lint and type checking

- **ruff**: in scope, and passing. Generated code is not exempt from the F-rules
  (undefined names, unused imports) — a failure there would be real breakage,
  not a style quibble.
- **mypy**: excluded, via `exclude` in `[tool.mypy]` plus an
  `ignore_errors` override for `revenium_mcp_server.generated.*` in
  `pyproject.toml`. `datamodel-codegen` emits Pydantic constrained-type calls
  (`conint(ge=0)`) that mypy rejects as annotations; that is a few hundred
  errors nobody can fix by hand, and adding them to `scripts/mypy-baseline.txt`
  would re-churn the baseline on every regeneration and dilute it as a record of
  real debt. Excluding costs no coverage of shipped code, because nothing here
  is imported at runtime.

## Public mirror

This package **is** exported to the public repo by the existing
`src/revenium_mcp_server/` rule in `public-allowlist-mcp.txt` — that is
intended, and the models are self-contained.

Everything else described above is internal-only and carved out of the export
by explicit `!` negations: the `specs/` snapshots, the three `scripts/` entry
points, and `tests/unit/test_openapi_contract.py`. If you are reading this file
in the public mirror, the regeneration commands above refer to files that only
exist in `revenium-mcp-internal`.
