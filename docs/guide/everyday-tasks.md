# Everyday tasks

Worked examples of what you can ask an assistant connected to ICS. Each one shows a request in
plain words, the tools the assistant typically uses, and what to expect. You never have to name
the tools yourself; they are listed so you can follow what the assistant does and recognise the
calls in your client.

Exact parameters of every tool are in the [tool reference](https://github.com/inprojectspl/ics-mcp/blob/main/README.md#tools).

## Find and read documents

### Find a document and summarize it

> "Find the runbook for API latency and summarize it."

1. `ics_assets_search` with the words from your request. Search covers titles, summaries, tags
   and the text of Markdown, PDF and Word documents. All words must match by default, in any
   order, ignoring case and accents. The results come best first, each with a short summary,
   the document type, the estimated size in tokens and text snippets.
2. Depending on the size, `ics_asset_read` for the whole document, or `ics_asset_outline` first
   and then `ics_asset_read` for the relevant sections (see the next section).

What to expect: a summary and the document's slug (its short identifier, also visible in its ICS
address `/v/<slug>`). If the best hit is marked as superseded, the assistant is told which
document replaces it and should read that one instead.

> [!TIP]
> To find an exact phrase, put it in double quotes in your request ("search for "rate limit
> exceeded""). To cast a wider net, ask for documents that match any of the words.

### Browse and filter your documents

> "List my pinned notes in the Architecture project."
> "Which documents shared with me changed since Monday?"
> "Which documents tagged `draft` are overdue for review?"

`ics_assets_list` filters by metadata without reading any content, which makes it the cheapest
first step. It can filter by kind, project, pinned, shared with you, owned by you, tag, document
type, freshness, and by date of the last content change (`updated_since`) or of any change,
metadata included (`touched_since`). It returns 20 documents per page by default and continues
with the next page when asked. For project ids, the assistant calls `ics_projects_list`.

Freshness tells you whether to trust a document:

| Freshness | Meaning |
|---|---|
| `current` | Nothing indicates the document is out of date. |
| `review_overdue` | Its review date has passed and nobody confirmed it is still current. |
| `superseded` | A newer document replaces it. The response names the successor (`superseded_by`) and the current end of the chain (`latest`). |

### Read a long document efficiently

> "In the incident handbook, what does the section on escalation say?"

Reading a whole long document costs time and the assistant's context. ics-mcp guides the
assistant to a simple rule: if a document is up to about 800 tokens, or most of it is needed, read
it whole; otherwise:

1. `ics_asset_outline` returns the headings without content. Each heading has an anchor and its
   first and last line, so the assistant knows how big every section is.
2. `ics_asset_read` with `anchor` reads just that section.

Other ways to read part of a file:

- A line range (`lines="40-80"`). One call returns at most 2000 lines; a longer file is read in
  several calls. A file over 2000 lines read without a range is refused with `file_too_large`.
- The first N lines (`max_lines`), with a flag that tells whether the file has more.

For a collection, the outline lists its files and the assistant reads each by its path. For an
HTML bundle, `ics_asset_read` with `format="markdown"` converts a page to Markdown (headings,
lists, tables and links kept, scripts and styles dropped), which is several times cheaper than
the raw HTML.

### Open a share link someone sent you

> "What is in this link? https://ics.example.com/s/AbC123..."

`ics_share_resolve` reads a document from a pasted share link (or a bare token) in one call. For a
password link, give the assistant the password. If you already have a role on the document, no
password is needed and the read does not count against the link's view limit. For an HTML bundle
it returns the metadata and the file list; the assistant then reads the files with
`ics_asset_read`.

## Write and update documents

### Create a note

> "Write up today's decision about the CI change as a note in ICS, type decision, and share it
> with the team."

1. `ics_doc_types`, if the assistant needs to know the document types your ICS offers.
2. `ics_asset_create_md` with the title, the content, and optionally a project, tags, document
   type and a 1-3 sentence summary.
3. The response contains the new slug and a share link.

> [!NOTE]
> ICS creates a share link for every new document, by default an `org_sso` link that anyone
> signed in to your organization's ICS can open if they have the link. The creation tools also
> accept `public` for this first link; that goes through the same confirmation as any public link.
> See [Share a document](#share-a-document) for the link modes.

Long content does not have to pass through the conversation. Over stdio, tools that take content
also accept a local file path (`content_path`), and ics-mcp reads the file from your disk. This
keeps large files out of the assistant's context.

### Create a collection of notes

> "Put these five Markdown files from `~/notes/architecture` into one ICS collection."

`ics_asset_create_collection` creates a multi-file vault whose notes link to each other with
`[[wikilinks]]`. You can name the start file; without it ICS picks the shallowest `README.md` or
`index.md`, and if there is none, the first file alphabetically. The tool reports progress, one
step per file.

To add a file later, the assistant uses `ics_asset_add_file` (or `ics_asset_create_empty_file`
for a placeholder); to move or rename a file, `ics_asset_move_file`; to delete one,
`ics_asset_delete_file`.

### Update one section of a document

> "In the onboarding guide, replace the VPN section with these new instructions."

1. `ics_asset_outline` to locate the heading.
2. `ics_asset_read` with that anchor, to see the current text.
3. `ics_asset_update_content` with the full new content of the file.

`ics_asset_update_content` replaces the whole file, not just a section, so the assistant has to
send the complete text with your change applied. It creates a new version, so the previous text
stays in the history. Because it overwrites content, it goes through the
[confirmation gate](confirmations-and-safety.md).

For a collection, the assistant names the file with `path`. To change many files of a collection
at once, it should use `ics_asset_new_version`, which replaces the whole file set in one version
instead of creating one version per file.

### Publish an HTML dashboard or report

> "Upload the dashboard in `~/build/q2-dashboard` to ICS and give me a link for the team."

1. `ics_asset_create_html` with the entry page (usually `index.html`) and every file of the
   bundle.
2. `ics_asset_html_security_review` to check the scan result: `clean`, `warn` or `critical`, with
   details of what was found.
3. `ics_share_create_link` for a link.

ICS scans every bundle. A document with a `critical` finding cannot be shared until an
administrator approves it. To change a bundle later, the assistant uploads the complete new file
set with `ics_asset_html_replace_bundle`; editing single files of a bundle is not possible.

### Organize: rename, tag, pin, describe

| Request | Tool |
|---|---|
| "Rename it to Q3 Plan" | `ics_asset_rename` (the slug and the links stay the same) |
| "Tag it `architecture` and `draft`" | `ics_asset_set_tags` (replaces the whole tag list, at most 20 tags) |
| "Pin it" / "Unpin it" | `ics_asset_pin` |
| "Set the summary, make Anna the maintainer, review it in three months" | `ics_asset_set_meta` |

`ics_asset_set_meta` changes metadata without creating a new version: summary, document type,
maintainer, review date, language and type-specific properties. The maintainer must be you or
someone the document is already shared with; otherwise it fails with `maintainer_unknown`, and
the fix is to share the document with that person first. Setting a document type without a
review date schedules the review using the type's default interval.

### Delete and restore

> "Delete the old draft of the release notes."

`ics_asset_delete` is a soft delete and asks for confirmation. `ics_asset_undelete` restores the
document, but it needs the document's UUID (a slug does not resolve for deleted documents), and
share links are not restored. If you may want a document back, ask the assistant to note its id
before deleting it.

## Versions and diffs

> "What changed in adr-007 since last week?"
> "Show me version 3 of the deployment checklist."
> "Undo the last change to the pricing page."

| Request | Tool |
|---|---|
| History: who changed what, and when | `ics_asset_versions` (number, size, date, author) |
| What changed between two versions | `ics_asset_diff` without a path: the list of added, removed and changed files with line counts |
| The exact changes in one file | `ics_asset_diff` with a path: a unified diff |
| Read an old version without changing anything | `ics_asset_read` with `version` |
| The file list of an old version | `ics_asset_list_files` with `version` |
| Make an old version current again | `ics_asset_restore_version` |

Restoring does not delete anything: it creates a new version with the old content, so history
stays intact. It goes through the confirmation gate.

In the ICS web app the same comparison is available as **Compare versions** in a document's menu,
so you can check the assistant's summary of a diff yourself.

## Share a document

> "Share the Q3 plan with an SSO link that expires on Friday."
> "Give Marta editor access to the onboarding guide."
> "Revoke the public link of the old pricing page."

A share link (`ics_share_create_link`) is for many people, or for pasting somewhere. Pick the
mode by who should open it:

| Mode | Who can open the link | Extra input |
|---|---|---|
| `org_sso` | Anyone signed in to your organization's ICS. | None |
| `password` | Anyone with the link and the password. | `password` |
| `public` | Anyone with the link, also signed out. | None. Asks for confirmation. |
| `magic_email` | Only the listed e-mail addresses; opening the link sends a sign-in link to the address. | `allowed_emails` |

Every mode accepts an expiry date (`expires_at`) and a maximum number of views (`max_views`).

A per-user grant (`ics_share_grant_user`) gives one person the `viewer` or `editor` role, so the
document appears in their ICS permanently, without a link. If no ICS account exists for that
e-mail address, ICS creates an invited account and sends the person an invitation e-mail to set a
password, so check the address before you confirm the request.

`ics_shares_list` shows the links and grants of a document, and `ics_share_revoke` revokes one:
with the link id it disables the link for everyone, with a user id it removes that person's
access. Revoking is permanent and goes through the confirmation gate.

> [!WARNING]
> Only a `public` link asks for confirmation, whether it is created on its own or together with a
> new document. Other links and per-user grants are created right away. Ask the assistant to show you what it is about to share if in doubt.

Who may share: ICS lets you create share links and per-user grants for documents you own, or for
documents in projects you own. Otherwise a new link fails with `share_forbidden`, and a per-user
grant or `ics_shares_list` fails with `asset_not_found`.

## PDFs and Word documents

### Upload a PDF or a Word document

> "Upload `~/Downloads/contract-2026.pdf` to ICS in the Legal project."

`ics_asset_create_document` uploads a local file. A `.pdf` becomes a `pdf_doc`; a `.docx`,
`.odt` or `.doc` becomes an `office_doc`. ICS extracts or converts the text, so the document can
then be read and searched like Markdown. The title defaults to the file name.

Good to know:

- This works only when ics-mcp runs on your computer (stdio), because it reads the file from your
  disk. On a [remote server](remote-http.md), upload the file in the ICS web app.
- Password-protected files are refused (`pdf_encrypted`, `office_encrypted`). Save an unprotected
  copy first.
- ICS scans the file: PDFs for JavaScript, launch actions, embedded files and XFA forms, Word and
  ODF files for macros and remote templates. A `critical` result blocks sharing until an
  administrator approves the document.
- Spreadsheets and presentations are not supported.
- ics-mcp refuses files over its upload limit (100 MiB by default); ICS has its own per-file cap,
  50 MB by default.

To replace the file with a new one, the assistant uses `ics_asset_replace_document`, which creates
a new version (for a Word document the format may change, for example from `.doc` to `.docx`).

### Read a PDF or a Word document

> "What are the termination terms in the contract PDF?"

`ics_asset_read` returns a PDF as Markdown: the title, then one `## Page N` section per page. The
outline gives the line of each page and the PDF's bookmarks, so the assistant can go straight to
the right page. A Word or ODF document reads as Markdown converted from its headings, paragraphs,
lists, tables and footnotes. Images are not read; each one appears as an `[image]` marker. A
legacy `.doc` keeps only paragraphs and table rows.

### Scanned PDFs and OCR

> "Can you read the scanned invoice I uploaded yesterday?"

Pages without a text layer (scans) get their text from OCR, which ICS runs in the background
after the upload. Until it finishes, such a page reads as "_No text layer on this page (scanned
image?)._", and the response tells the assistant the OCR state.

- `ics_asset_ocr` shows the state: `not_requested`, `queued`, `running` (with page progress),
  `done` or `failed`.
- `ics_asset_ocr` with `request=True` queues OCR, retries a failed run, or replaces a text layer
  that the scanner saved in the file (ICS does not check the quality of such a layer, and the
  assistant is told so).
- Pages read by OCR start with "_Text recognized by OCR._". Recognition errors are possible, so
  check numbers and names that matter.
- A long scan takes minutes. Ask again later instead of asking the assistant to wait.

Your ICS administrator may have turned OCR off; the assistant is told when that is the case.

## The relation graph

ICS records typed relations between documents, such as "this design was derived from those
goals". The assistant uses them to find the documents around the one you are working on.

> "What is this spec based on, and has anything it depends on changed?"
> "Is there a newer version of this policy?"
> "Record that the new API spec supersedes the old one."

| Request | Tool |
|---|---|
| What is around this document | `ics_graph_neighbourhood` (strong relation types, both directions, one step by default, up to 3 steps) |
| Which documents it links to in its text | `ics_graph_neighbourhood` or `ics_asset_relations` for the `references` type |
| The relations of one document, with ids | `ics_asset_relations` |
| Record how two documents relate | `ics_relation_add` (asks for confirmation; needs editor on the source document) |
| Change the note of a relation, or mark a changed target as checked | `ics_relation_update` |
| Remove a wrong relation | `ics_relation_remove` (asks for confirmation) |
| Pick up links in a document stored before ICS extracted them | `ics_asset_rescan_relations` (needs editor) |

Relation types:

| Type | Meaning (A to B) |
|---|---|
| `derived_from` | A was made from B. A new version of B flags A as "basis changed". |
| `supersedes` | A replaces B. B becomes `superseded`. |
| `depends_on` | A is not valid without B. |
| `part_of` | A is a part of B. |
| `references` | A mentions B. ICS creates these from links in the content. |
| `relates_to` | A loose relation, in both directions. |
| `duplicates` | A duplicates B. |
| `contradicts` | A and B disagree, in both directions. |

Links in the content to other ICS documents (an ICS address, a share link, or an
`ics://asset/...` reference) become `references` relations automatically. Because they are weak,
`ics_graph_neighbourhood` leaves them out unless asked and reports how many it skipped.

You only ever see relations whose both ends you can open. Reading relations needs more than a
viewer share or a share link: you need to own the document, be a member of its project, or have
editor access.

## Start work on a task

If your team links ICS documents to OpenProject work packages or Project Standard tasks, the
assistant can gather everything a task needs in one call.

> "I'm starting work package 4711 in project webshop. What should I read first?"

`ics_task_context` returns a map of documents for the task, nearest first: documents marked as
required, documents linked to the task and then to its parent tasks, the project's key documents
when little is linked, and related documents from the relation graph. Each entry has a summary,
freshness and size, and says why it is in the list. It is a map, not content: the assistant then
opens only what it needs.

Tips for good results:

- Mention the project. With the project (the OpenProject identifier or an ICS project slug) the
  project's key documents are included; without it they are skipped, and the response says so.
- Mention the parent tasks if you know them, so documents linked to them are included too.
- The response is sized to a budget (1800 tokens by default, 200 to 4000). If it was cut, the
  assistant is told what budget the whole list needs.
- Watch the warnings: a superseded document, a changed basis (a document the task relies on has a
  newer version), two documents that contradict each other, or no documents linked to the task at
  all (often a wrong work package number).

To build up the links:

| Request | Tool |
|---|---|
| "Link the API spec to 4711 as required reading" | `ics_task_link` with role `context` and `required` |
| "This report is the result of 4711" | `ics_task_link` with role `deliverable` |
| "Which tasks use this document?" | `ics_asset_external_refs` |
| "Remove that link" | `ics_task_unlink` (asks for confirmation) |
| "Which key documents does the project have?" | `ics_project_links` |
| "Set the charter and the glossary as key documents" | `ics_project_links_set` (project owner only; asks for confirmation) |

A task link grants nobody access. Everyone sees only the linked documents they could open anyway.

To see the same list in ICS, open the project's **Agent context** tab, enter the task and choose
**Show the pack**. It shows the documents in the order an agent reads them, with "Why it is in
the pack" for each.

## Ready-made workflows (prompts)

Some MCP clients show the prompts a server offers, for example as slash commands. ics-mcp offers
three:

| Prompt | What it does |
|---|---|
| `share_with_team` | Checks the document title, creates a share link and suggests how to send it; with a password hint, reminds you to send the password separately. |
| `summarize_collection` | Reads the outline of a collection, picks the most important files, reads them and writes a summary per file plus an overall one. |
| `migrate_to_collection` | Turns a single Markdown document into a collection. Share links do not carry over, so it reminds you to recreate them. |

## Related

- [Overview](overview.md)
- [Confirmations and safety](confirmations-and-safety.md)
- [Remote use over HTTP](remote-http.md)
- [Troubleshooting](troubleshooting.md)
