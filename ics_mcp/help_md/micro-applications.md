# Micro-applications

A `micro_application` asset is a small web app with its own data: a static
UI (`public/`), a declared data model with generic CRUD and optional
JavaScript handlers (`handlers/*.mjs`) for rules CRUD cannot express. ICS
runs every app on one shared runtime, on its own origin
`https://a-<asset id hex>-prod.<apps host>/`; nothing runs while an app is
not used.

## Build and publish

1. `ics_microapp_contract()` for the overview, then the sections you need
   (`template` is a complete working package, `manifest_schema` the JSON
   Schema, `sdk_types` the handler SDK).
2. Write `microapp.json`, `public/` and handlers. No server, Dockerfile, npm
   install, raw SQL or network calls: the contract has none of them.
3. `ics_microapp_plan(files=[...])` or `ics_microapp_plan(package_dir=...)`
   (stdio). Fix `manifest_invalid` diagnostics by `file`, `pointer`, `code`.
4. `ics_microapp_apply(plan_id, digest=release_digest, expected_generation)`.
   It returns an `operation_id` at once. After a lost response call it again
   with the same `idempotency_key` (the default is derived from the plan);
   never plan a second app "just in case".
5. `ics_microapp_status(operation_id=...)` until `terminal`; `succeeded`
   means the release is active, `failed` leaves the previous release serving.
6. People get business permissions (for example `requests.approve`) in the ICS
   panel, tab Micro-applications. Owning the asset does not grant them.

## Run and control

- `ics_microapp_status(asset_id=...)`: desired state (`enabled` /
  `suspended`), runtime (`sleeping`, `ready`, `running`, sample time), active
  release vs latest package version, data size, your rights, `generation`.
- `ics_microapp_control(asset_id, action, expected_generation)`: `enable`
  (back to enabled + sleeping), `suspend` (blocks new requests, waits for
  in-flight ones, survives restarts), `sleep`, `restart`. No data is deleted.
- `ics_microapp_logs(asset_id)`: redacted log lines, newest first.

## What other tools do with a micro-application

Generic upload, edit, new-version, restore and sync tools refuse it with
`microapp_requires_agent_api`. `ics_asset_read` and `ics_asset_list_files`
show its package only to publishers (`app.publish`); using an app gives no
right to its sources.
