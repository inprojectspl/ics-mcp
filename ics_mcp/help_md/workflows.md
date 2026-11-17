# Workflows

> **Convention**: `create_*` tools return a `slug` field (and `id`) in the
> response; use it as `slug_or_id` in later calls.
> Example response: `{"id": "...", "slug": "abc123xyz", "title": "..."}`.

## Create a note and share it with the team

```
resp = ics_asset_create_md(title="Decision: CI change", content="# ...\n\n- ...")
# resp.slug = e.g. "abc123xyz"
share = ics_share_create_link(slug_or_id=resp.slug, mode="org_sso")
# share.url = the full link to paste into Slack
```

## Update a section of an existing file

```
ics_asset_outline(slug_or_id="abc123")       # locate the heading
ics_asset_read(slug_or_id="abc123", anchor="scope")
ics_asset_update_content(slug_or_id="abc123", content="...new content of the whole file...")
```

## Generate an HTML dashboard and link it

```
resp = ics_asset_create_html(
    title="Dashboard Q2",
    entry_path="index.html",
    files=[
        # Prefer content_path when the files are on disk (> a few KB):
        {path:"index.html", content_path:"/tmp/dashboard/index.html"},
        {path:"style.css",  content_path:"/tmp/dashboard/style.css"},
    ],
)
ics_asset_html_security_review(slug_or_id=resp.slug)  # check the status
ics_share_create_link(slug_or_id=resp.slug, mode="public")
```

## Publish with a durable receipt

Persist `publication={id, order_id, role}` before calling `ics_asset_create_html`
(inside `payload`) or a whole-version replacement tool. A keyed replacement
also requires the caller's `expected_version`. The server never invents a key.
Initial Markdown/document creation and per-file edits do not accept publication.

Success includes `publication_receipt` and its confirmed `version`; a historical
receipt does not claim to be the asset's latest version. A backend `201` alone
does not prove the receipt exists. `publication_unconfirmed` means the write may
already have happened on a backend that ignored the identity.

On timeout or gateway error, preserve the returned `data.publication` and
`data.project_id`, then call `ics_publication_get` with those original values.
The outcome is **unknown** until a matching receipt is read. A missing receipt
is inconclusive: never create a new key merely because an acknowledgement was
lost, and do not blindly repeat the mutation. Gateway failures never trigger an
automatic POST retry. Replaying the same payload/key, when appropriate, is an
explicit caller action; a changed payload is `publication_conflict`.

## Build a micro-application and hand it to people

```
ics_microapp_contract()                                  # overview, then sections
ics_microapp_contract(section="template")                # a working package to adapt
ics_microapp_plan(files=[...])                           # -> plan_id, release_digest, expected_generation
ics_microapp_apply(plan_id, digest=release_digest, expected_generation=0)
ics_microapp_status(operation_id=...)                    # until terminal; app_url
ics_microapp_access(asset_id)                            # the app's roles, what each permission unlocks
ics_microapp_access_set(asset_id, user_email="me@...", roles=["manager"])        # yourself first
ics_microapp_access_set(asset_id, user_email="bob@...", roles=["employee"])
ics_microapp_access_set(asset_id, project_id="...", roles=["employee"])          # a whole team
ics_share_create_link(slug_or_id=asset_id, mode="public", app_roles=["voter"])   # no account needed
```

## Organize a set of notes into a project

```
ics_projects_list()                          # find the target project
ics_project_create(name="Architecture")      # or make a new one: returns its id
ics_asset_create_collection(
    title="Vault: Architecture",
    project_id="<uuid>",
    files=[{path:"intro.md", content:"..."}, ...],
    tags=["architecture", "draft"],
)
```

## Agent in batch mode (yolo)

```
ics_session_set_mode(mode="yolo")            # no confirmation prompts
ics_assets_search(q="legacy")                # find
ics_asset_delete(slug_or_id="...")           # does not ask
```

**Traffic limit**: ICS may throttle requests. The client auto-retries with
`Retry-After` on 429, so short bursts go through on their own. For long
loops paginate `ics_assets_list(cursor=...)` instead of pushing one at a time,
and batch destructive operations (`ics_asset_new_version(files=[...])`
instead of N separate `ics_asset_update_content`). Full info: `ics_help("auth")`.

## Audit changes before running them (dry_run)

```
ics_session_set_mode(mode="dry_run")
ics_asset_delete(slug_or_id="...")           # returns a preview, deletes nothing
```
