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

**Not every ICS has them.** Micro-applications are an optional feature of
the ICS server; an instance without them answers `microapps_disabled`. Then
say that this ICS runs without micro-applications, offer an HTML bundle when
the user only needs to show content, and do not retry.

## What fits and what does not

Check the idea against this before writing a package; say early when it
does not fit instead of building half of it.

**Fits well**: forms and registers with an approval flow, booking and
reservations, polls and votes, checklists and trackers, small catalogues,
team games with a leaderboard, simple dashboards over the app's own data.
Tens of users, thousands to tens of thousands of records.

| | What you get |
|---|---|
| Data | up to 20 collections, 40 fields each: `string`, `integer`, `decimal`, `boolean`, `date`, `timestamp`, `uuid`, `enum`, `json` (up to 64 KiB); system fields `id`, `created_by`, `created_at`, `updated_at`, `revision`; indexes, also `unique` |
| CRUD without code | per operation: permission, `rowScope` (`own`, `not_own`, `all`), `writeFields`, `conditions` (e.g. editable only while `status=submitted`), `allowedValues` |
| Queries | filters `eq`, `in`, `lt`, `lte`, `gt`, `gte`; sort by one field; keyset pages of up to 200; `count`, `groupCount` |
| Own logic | JavaScript handlers on your own endpoints: any validation, calculation or state machine, writes to several collections in one transaction, idempotent and with `If-Match`; data only through the capabilities declared in the manifest |
| Page | any static HTML, CSS and JS, libraries bundled into `public/`, works on phones; a single-page app routes with `#` (other paths are files or 404); the SDK gives the user, their roles and permissions |
| People | ICS accounts by role, project members, link visitors without an account (anonymous, kept 30 days per browser) |

**Does not exist** (and the usual way around it):

- No network: no external APIs, webhooks, CDN scripts or fonts (CSP allows
  only the app's own origin). Bundle libraries into `public/`.
- No e-mail, chat or push notifications. The page shows what changed.
- No scheduled or background jobs: code runs only when someone calls an
  endpoint. Do periodic work on a button or when the page opens.
- No live push (WebSocket, SSE): poll every few seconds (the rate limit is
  20 requests per second per person).
- No file uploads or binary attachments; store a link (e.g. to an ICS
  document) in a `string` field.
- No full-text or `LIKE` search, no joins, no `SUM`/`AVG` in the database:
  filter on indexed fields, join and add up in a handler (at most 20 database
  calls of up to 200 rows, 250 ms of JavaScript, 32 MiB of memory, 5 s, a
  256 KiB answer per request).
- No access to ICS documents, other apps' data or the list of ICS users;
  `created_by` and the session say who is who.
- No imports in handlers (one file per handler, up to 256 KiB), no
  `fetch`, timers, files or `eval`.
- Model changes are additive only: no rename, drop or type change of a field
  (add a new field instead).
- Size: the owner's data limit (100 MiB by default) for all their apps; a
  package of up to 50 files and 5 MiB.

**Does not fit**: integrations with other systems, anything that must act
on its own at a set time, file storage, heavy computing or reports over
large data, public sites with many anonymous users, or an app that needs to
read ICS content. Say so and suggest an HTML bundle (content only) or a
regular service instead.

## From idea to people using it

1. `ics_microapp_contract()` for the overview, then the sections you need
   (`template` is a complete working package, `manifest_schema` the JSON
   Schema, `sdk_types` the handler SDK, `browser_sdk` the page SDK).
2. Write `microapp.json`, `public/` and handlers. No server, Dockerfile, npm
   install, raw SQL or network calls: the contract has none of them. Name
   permissions after what people do (`requests.read`, `requests.approve`),
   give each a `label`, and declare the `roles` of the kinds of people who
   use the app (below; both are required).
3. `ics_microapp_plan(files=[...])` or `ics_microapp_plan(package_dir=...)`
   (stdio). Fix `manifest_invalid` diagnostics by `file`, `pointer`, `code`.
   `app_changes` says what the release changes for the people using the app
   against the running one (a role gains or loses a permission, a collection
   gets a field; for a new app, everything it brings): tell the user before
   applying. Give `change_note` (one sentence) for the version history. A
   package that would exceed the owner's storage quota is refused here.
4. `ics_microapp_apply(plan_id, digest=release_digest, expected_generation)`.
   It returns an `operation_id` at once. After a lost response call it again
   with the same `idempotency_key` (the default is derived from the plan);
   never plan a second app "just in case".
5. `ics_microapp_status(operation_id=...)` until `terminal`; `succeeded`
   means the release is active and `app_url` opens it, `failed` leaves the
   previous release serving.
6. **Give people a role** (below). Without it nobody, not even the owner,
   can do anything in the app.

## Two kinds of role: on the asset and in the app

A person has two independent roles around a micro-application. Keep them
apart:

| | ICS role on the asset | App role |
|---|---|---|
| what | `viewer`, `editor`, owner (of the asset or its project) | the app's own roles, e.g. `employee`, `reviewer` |
| comes from | a share, project membership, ownership | `ics_microapp_access_set`, a share link |
| decides | what the person does **with the asset** | what the person does **in the app** |

What the ICS role decides for a micro-application:

- any role (`viewer` and up): the person can **open** the app;
- `editor`: can also prepare a plan of a new release (`ics_microapp_plan`),
  not apply it;
- owner of the asset or of its home project: applies releases
  (`app.publish`), controls the runtime (`app.control`) and gives access
  (`app.access.manage`). A co-author or operator can be given `app.publish`
  or `app.control` as a permission; giving access stays with owners.

It gives **nothing inside the app**: an editor or the owner without an app
role cannot list, create or approve a single record. An app role, in turn,
lets nobody open the app, publish or give access.

An app role given to a **project** reaches every accepted member the same
way, whatever their role in the project: a project `viewer` gets exactly what
the project's `editor` or owner gets. There is no "reviewers are the
project's editors" rule. When people of one project need different app
roles, give the project the common one (or none) and the others to those
people directly (`user_email=...`); a person's own roles add to the
project's.

## Roles: the kinds of people who use the app

Permissions are the app's fine-grained rights; people think in roles
("employee", "reviewer"). `microapp.json` declares both, and both are
required:

```json
"permissions": {
  "requests.create": {"label": "File requests"},
  "requests.read": {"label": "See own requests"},
  "requests.approve": {"label": "Approve other people's requests",
                       "description": "Only requests still waiting."}
},
"roles": {
  "employee": {"label": "Employee", "description": "Files own requests.",
               "permissions": ["requests.create", "requests.read"]},
  "reviewer": {"label": "Reviewer", "description": "Approves requests.",
               "permissions": ["requests.approve"]}
}
```

- Every permission has a `label` (and may have a `description`); rules,
  capabilities, endpoints and roles name only declared permissions
  (`permission_not_declared` otherwise), never `app.*`.
- Every permission belongs to at least one role (`permission_without_role`
  otherwise): access is given by role, so a right no role holds would be
  handed out one person at a time.
- Role keys are identifiers (`^[a-z][a-z0-9_]*$`, 1 to 20 roles). Labels
  are shown to the people who give access, in the app's language.
- A person may hold several roles; they add up. Make a role whole on its
  own when one kind of person needs everything another has (a `manager`
  with the `employee` permissions plus `requests.approve`).
- A role is stored by name: a new release that changes what a role gives
  changes it for everyone who holds it. A plan that drops a role or a
  permission people still hold warns `grant_orphaned`; they lose it on apply.
- The page sees `ics.session().roles` (to show a reviewer's screens);
  the broker enforces permissions, never roles.

## Access: who may open the app and do what

Two things make a person able to work in an app: they can **open** it (a
role on the asset) and they hold the app's **roles or permissions**. No ICS
role implies the latter, not even ownership. Both are set in one call:

```
ics_microapp_access(asset_id)          # the roles, what each permission unlocks, who has what
ics_microapp_access_set(asset_id, user_email="bob@firma.pl", roles=["employee"])
```

- `ics_microapp_access_set` sets **exactly** the given `roles` and
  `permissions` (an omitted list means none): missing ones are granted,
  extra ones revoked. Repeating the call changes nothing, so it is safe
  after a lost response.
- Prefer roles. `permissions=[...]` gives a single extra right beside them
  (one person who also approves, a co-author's `app.publish`).
- For a person it also makes sure they can open the app (`can_open`
  defaults to true when anything is given; ICS adds a `viewer` share). The
  answer says `roles_added`, `roles_removed`, `added`, `removed`,
  `open_change` and the person's resulting `roles`, `permissions`,
  `can_open` and `effective_permissions`.
- Start with yourself: `user_email=<your e-mail>` with the role you need to
  try the app.
- A whole team: `project_id=...` instead of `user_email`; every accepted
  member gets the project's roles on top of their own, the same for a
  project viewer, editor or owner. `members_can_open` says
  whether the app is in that project; otherwise share it with the project
  first.
- Remove a person: `roles=[]`, `permissions=[]`, `can_open=false`. This
  removes the `viewer` share; if they still open the app through another
  role (project membership, editor), the answer says so in `still_opens_via`.
- `app.publish` and `app.control` are platform permissions for co-authors
  and operators; they go in `permissions`.
- The person must have an ICS account. To invite someone new use
  `ics_share_grant_user(email, role="viewer")` first, then set access.

## Links: people without an account

`ics_share_create_link(slug_or_id, mode, app_roles=[...])` makes a
`/s/<token>` link that opens the app itself with exactly these roles
(`app_permissions=[...]` adds single permissions; at least one of the two
is required for this kind).

| mode | who gets in |
|---|---|
| `public` | anyone with the link, **without signing in** |
| `password` | anyone who enters the password |
| `org_sso` | people signed in with an allowed domain |
| `magic_email` | the listed e-mails, through the link in their message |

Each visitor gets an anonymous identity kept for 30 days in that browser,
so `rowScope: "own"` records stay theirs. A member who can already open
the app enters as themselves with their own roles and is not counted
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

## Reading an app

`ics_asset_read(slug_or_id)` returns the app as one Markdown document, as
the caller sees it (their roles, permissions and row scopes; nothing more):

1. **App view**: the app's content rendered by the app itself, records
   filled in (each item with its comments, the queue waiting for approval,
   the reader's own reservations). It comes from the app's document view;
   `app_view` in the answer names it, with an `error` when it could not run.
2. What the app is, its state, roles and every permission with what it
   unlocks.
3. The data model and the raw records of every collection the caller may
   list. Each readable collection shows its first page; `next_cursors` names
   the cursor of the next one.

```
ics_asset_read(app)                                        # app view + overview + first pages
ics_asset_read(app, path="data/comments", cursor="...")    # next page of one collection
ics_asset_read(app, path="handlers/document.mjs")          # a package file (publishers only)
```

A collection you cannot list says which permission it needs. A suspended
app shows its description and model, without data.

## Building an app that reads well

People and agents read an app through its document view, so give every
app one, and keep its content in the database:

- **Document view**: `"document": {"endpoint": "document"}` names a `GET`,
  `read_only` endpoint without path parameters that returns
  `{"markdown": string}`. Render what the app shows: the items and their
  records together (an item with its comments, a request with its state),
  not raw rows. It runs as the reader: `ctx.actor.permissions` and
  `ctx.actor.roles` tell what they may see, so leave out sections they
  cannot read (a reviewer's queue); its capabilities are checked on each
  data call. Page through `ctx.db.list` with `nextCursor`. The template has
  one.
- **Seed data**: content that exists at the start (the items of a document
  turned into an app) goes to `seed/<collection>.json`, a JSON array of
  records with the collection's fields, optionally `id` and `created_at`
  (an imported comment keeps its date). It is inserted once, when a release
  creates the collection, owned by the publisher; `ics_microapp_plan` shows
  `database.seed_rows`. A later release with seed rows for an existing
  collection warns `seed_not_applied`, so plan the collections up front. Do not
  keep such content in `public/` files: the document view, row rules and
  handlers cannot see them.

## Projects

`ics_microapp_plan(..., project_id=...)` creates the app in a project;
`ics_asset_set_meta(app, project_id=...)` moves an existing one (`''` takes
it out), as for any asset. Members of the project can then open it; what
they may do in it still comes from `ics_microapp_access_set` (a project
can hold a role).

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

- Read it whole with `ics_asset_read`: there is no outline, `anchor` or
  rendered HTML (`ics_asset_outline` and `ics_asset_read_rendered` answer
  `microapp_source_restricted` with that hint), and `version=N` without
  `path` is refused (an archived version is only its package).
- `ics_assets_search` finds it by title, summary and tags; its records are
  data, never indexed.
- Relations point at the app as a whole: `target_path`/`target_anchor` and
  `ics_asset_rescan_relations` answer `microapp_not_addressable`.
- A share link to it opens the app in a browser; `ics_share_resolve` does
  not read it. `ics_share_grant_user` only lets a person open it; their
  roles come from `ics_microapp_access_set`.
- Deleting it stops it for everyone, revokes its links and removes the
  roles people hold; its data stays and returns on `ics_asset_undelete`
  (without the roles). An app whose first publication failed never ran and
  goes to the trash by itself.
- A rename or a summary written in ICS stays: the next release updates the
  title and description from the manifest only while nobody changed them.

Comparing releases (publishers): every apply that reached
`package_committed` is a package version. `ics_asset_versions(app)` lists
them, `ics_asset_diff(app, v1, v2)` compares two: `files[]` as for any
asset, plus `app_changes` (`area` role, permission, endpoint, capability,
collection or setting; `change` added, removed or changed; `detail` such as
`+requests.export -requests.read`). `path="handlers/x.mjs"` gives one
file's unified diff. Each version carries its `release_status` (`active`,
`superseded`, `failed`, `candidate`); `is_current` marks the one that runs,
so a failed later package is never taken for the running app. Failed
releases stay in the history and are comparable too.
