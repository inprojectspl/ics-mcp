# Micro-applications

A `micro_application` asset is a small web app with its own data: a static
UI (`public/`), a declared data model with generic CRUD and optional
JavaScript handlers (`handlers/*.mjs`) for rules CRUD cannot express. ICS
runs every app on one shared runtime, on its own origin
`https://a-<asset id hex>-prod.<apps host>/`; nothing runs while an app is
not used.

**When to build one**: the user wants something people *use* and that
*keeps data* (a request register, a booking sheet, a poll, a game with a
leaderboard). A page that only shows content is an HTML bundle
(`ics_asset_create_html`), not a micro-application.

## From idea to people using it

1. `ics_microapp_contract()` for the overview, then the sections you need
   (`template` is a complete working package, `manifest_schema` the JSON
   Schema, `sdk_types` the handler SDK, `browser_sdk` the page SDK).
2. Write `microapp.json`, `public/` and handlers. No server, Dockerfile, npm
   install, raw SQL or network calls: the contract has none of them. Name
   permissions after what people do (`requests.read`, `requests.approve`).
3. `ics_microapp_plan(files=[...])` or `ics_microapp_plan(package_dir=...)`
   (stdio). Fix `manifest_invalid` diagnostics by `file`, `pointer`, `code`.
4. `ics_microapp_apply(plan_id, digest=release_digest, expected_generation)`.
   It returns an `operation_id` at once. After a lost response call it again
   with the same `idempotency_key` (the default is derived from the plan);
   never plan a second app "just in case".
5. `ics_microapp_status(operation_id=...)` until `terminal`; `succeeded`
   means the release is active and `app_url` opens it, `failed` leaves the
   previous release serving.
6. **Give people access** (below). Without it nobody, not even the owner,
   can do anything in the app.

## Access: who may open the app and do what

Two things make a person able to work in an app: they can **open** it (a
role on the asset) and they hold the app's **business permissions**. No ICS
role implies the latter, not even ownership. Both are set in one call:

```
ics_microapp_access(asset_id)          # what each permission unlocks, who has what
ics_microapp_access_set(asset_id, user_email="bob@firma.pl",
                        permissions=["requests.read", "requests.create"])
```

- `ics_microapp_access_set` sets **exactly** the given permissions: missing
  ones are granted, extra ones revoked. Repeating the call changes nothing,
  so it is safe after a lost response.
- For a person it also makes sure they can open the app (`can_open`
  defaults to true when `permissions` is not empty; ICS adds a `viewer`
  share). The answer says `added`, `removed`, `open_change` and the person's
  resulting `can_open` and `effective_permissions`.
- Start with yourself: `user_email=<your e-mail>` with the permissions you
  need to try the app.
- A whole team: `project_id=...` instead of `user_email`; accepted members
  get the permissions. `members_can_open` says whether the app is in that
  project; otherwise share it with the project first.
- Remove a person: `permissions=[]`, `can_open=false`. This removes the
  `viewer` share; if they still open the app through another role (project
  membership, editor), the answer says so in `still_opens_via`.
- `app.publish` and `app.control` are platform permissions for co-authors
  and operators; they are set the same way.
- The person must have an ICS account. To invite someone new use
  `ics_share_grant_user(email, role="viewer")` first, then set permissions.

## Links: people without an account

`ics_share_create_link(slug_or_id, mode, app_permissions=[...])` makes a
`/s/<token>` link that opens the app itself with exactly `app_permissions`
(a subset of the release's permissions; required for this kind).

| mode | who gets in |
|---|---|
| `public` | anyone with the link, **without signing in** |
| `password` | anyone who enters the password |
| `org_sso` | people signed in with an allowed domain |
| `magic_email` | the listed e-mails, through the link in their message |

Each visitor gets an anonymous identity kept for 30 days in that browser,
so `rowScope: "own"` records stay theirs. A member who can already open
the app enters as themselves with their own permissions and is not counted
against `max_views`. `ics_share_revoke(share_id=...)` cuts open sessions at
once. Pages show `session.user.displayName` as `null` for link visitors.

## Limits

- **Data**: the owner has one data limit for all their apps (default
  100 MiB, an admin raises it). Over it, inserts and updates answer 507
  `app_data_quota_exceeded`; reads and deletes still work, so the app can
  make room. `ics_microapp_status(asset_id)` shows the measured data size.
- **Requests**: per person and app per second, and per share link; over it
  429 `rate_limited` with `Retry-After`.
- Package, handler and runtime limits: `ics_microapp_contract(section="limits")`.

## Run and control

- `ics_microapp_status(asset_id=...)`: desired state (`enabled` /
  `suspended`), runtime (`sleeping`, `ready`, `running`, sample time), active
  release vs latest package version, data size, your rights, `generation`.
- `ics_microapp_control(asset_id, action, expected_generation)`: `enable`
  (back to enabled + sleeping), `suspend` (blocks new requests, waits for
  in-flight ones, survives restarts), `sleep`, `restart`. No data is deleted.
- `ics_microapp_logs(asset_id)`: redacted log lines, newest first.
- A new release: plan the changed package with `asset_id`, then apply.
  Model changes must be additive (`destructive_change` otherwise).
- `ics_asset_delete` moves the app to the trash: it answers 404 at once and
  stops counting against the data limit, its data stays; `ics_asset_undelete`
  brings it back. Its schema and database roles are dropped only when the
  trash is purged.

## What other tools do with a micro-application

Generic upload, edit, new-version, restore and sync tools refuse it with
`microapp_requires_agent_api`. `ics_asset_read` and `ics_asset_list_files`
show its package only to publishers (`app.publish`); using an app gives no
right to its sources.
