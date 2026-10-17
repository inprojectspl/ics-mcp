# Document graph

ICS records typed relations between assets ("this design was derived from
those goals"). Each edge is stored once, in its canonical direction; the
other end sees it under the inverse label.

## Relation types

| `relation_type` | A -> B | B sees | Use it when |
|---|---|---|---|
| `derived_from` | A was made from B | `basis_for` | a design from goals, a spec from the design; a new version of B flags A `basis_changed` |
| `supersedes` | A replaces B | `superseded_by` | spec v3 replaces v2; B becomes `superseded` |
| `depends_on` | A needs B to be valid | `required_by` | an annex on a contract |
| `part_of` | A is a part of B | `has_part` | a chapter of a manual |
| `references` | A mentions B | `referenced_by` | a weak mention; links in content create it |
| `relates_to` | symmetric | `relates_to` | nothing more specific fits; add a `note` |
| `duplicates` | A duplicates B | `duplicated_by` | the same file uploaded twice |
| `contradicts` | symmetric | `contradicts` | two documents disagree |

Pick the most specific type. `supersedes` and `part_of` must not form a
cycle (`relation_cycle`); symmetric types cannot point at a heading
(`relation_anchor_invalid`).

## Compact shape

| Part | Shape |
|---|---|
| `nodes` | keyed by slug: `title`, `doc_type`, `summary` (200 chars), `estimated_tokens`, `depth` (root 0); only when it says something: `freshness` (not `current`), `kind` (not `md_single`), `superseded_by` (slug), `expandable: false` (a leaf) |
| `edges` | `[from, type, to]` in the stored direction (for a symmetric type the order means nothing) |
| 4th edge element | only what is set: `id` (in `ics_asset_relations`), `source_path`, `target_path`, `target_anchor`, `note`, `changed` (`[recorded target version, current one]`) |
| `detail="full"` | the verbose ICS shape with ids and timestamps |

## Links in the content

ICS finds links to other ICS documents in the content of every new version
(Markdown, PDF and Word/ODF text, HTML pages) and records each as a
`references` edge (`/v/<slug>`, `/s/<token>`, `ics://asset/...`,
`[[ics:<slug>]]`), whoever wrote it. You see an edge only when you can
open both of its ends, so a link to a document you cannot open never shows.
`references` is a weak type: `ics_graph_neighbourhood` leaves it out by
default and says so in `skipped` (`{"references": 2}`) and the hint; follow
the links with `types=["references"]`.

A document stored before ICS extracted links has none of these edges until
its next version. `ics_asset_rescan_relations(slug_or_id)` looks again
without a new version (needs editor). Rescanning does not reveal links to
documents you cannot open; if they still do not show, they are not yours.

A `references` edge taken from a link in the text is left out when another
relation joins the same two documents.

## Recipes

- Surroundings: `ics_graph_neighbourhood(slug_or_id)`. Defaults: strong
  types (`derived_from`, `depends_on`, `supersedes`, `part_of`,
  `contradicts`), both directions, depth 1 (max 3), 20 nodes (max 200).
  Weak types only through `types`; `skipped` counts what was left out.
- What it builds on: `direction="out"`; what builds on it: `"in"`. Root of
  a `derived_from` chain: `types=["derived_from"], direction="out", depth=3`.
- Current version of a superseded document: `latest` in `ics_asset_meta`,
  `ics_assets_list` or `ics_asset_read`, one call. The whole chain:
  `types=["supersedes"], depth=3`; depth 1 is only the next step.
- Edge ids (to update or remove one): `ics_asset_relations(slug_or_id,
  types?, direction?)`.
- A heading an edge points at: `ics_asset_read(slug_or_id=<to>,
  anchor=<target_anchor>)`, or `slug_or_id="ics://asset/<to>#<anchor>"`.
- A changed target (`changed`): `ics_asset_diff` between the two versions;
  if the source still holds, `ics_relation_update(relation_id,
  refresh_target_version=true)`.
- Record an edge: `ics_relation_add(source, target, relation_type,
  target_path?, target_anchor?, note?)`. It follows the confirm gate
  (`dry_run` previews it by title), needs editor on `source`; the same edge
  twice is `relation_exists`; it returns the compact `edge` with its `id`.
  Remove: `ics_relation_remove(relation_id)`, destructive; its preview
  names both ends.

## Deciding how far to go

- Decide from `summary`, `doc_type`, `freshness` and `estimated_tokens`
  before opening anything. Reading rule: up to 800 `estimated_tokens`, or
  when you need most of it, read the whole document; otherwise
  `ics_asset_outline` (no `edges`), then `ics_asset_read(anchor=...)`.
- Skip `superseded` nodes unless you need the history. `expandable: false`
  is a leaf for you: do not ask for its neighbourhood.
- Prefer a small `depth` and specific `types`, then walk on from the node
  that looks relevant. A `truncated` response names the types with counts,
  `direction` and a far node to walk on from: narrow, do not go deeper.
- Graphs are independent: no root, no required project graph. Do not
  invent relations to connect everything.

## Visibility and limits

You see only edges whose other end you can read; hidden edges are never
counted. No graph access is `asset_not_found`, as for a missing asset; a
direct viewer share or a share link gives none. Up to 200 relations per
asset, notes up to 500 characters.
