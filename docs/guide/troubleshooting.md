# Troubleshooting

When a tool fails, ics-mcp returns a structured error: a stable `code`, a `message`, and often a
`hint` with the fix, the HTTP `status` from ICS, the `field` at fault, or extra `data` (for
example the allowed values). The assistant usually reads the hint and corrects itself. This page
explains the codes you are most likely to see and what you can do about them.

Codes that come from ICS itself are passed through unchanged; the complete list is in the ICS
[API error reference](https://github.com/inprojectspl/ics/blob/main/docs/api-errors.md).

## Signing in

| Code or symptom | What it means | What to do |
|---|---|---|
| `auth_required` (local setup) | No valid sign-in: the tokens were deleted, revoked or expired and could not be renewed, or ics-mcp runs where it cannot open a browser. With the latter, the error carries an `authorization_url`. | On a desktop, call a tool again and finish the sign-in in the browser. If it keeps coming back, delete the keyring entry ([Sign out](getting-started.md#sign-out)) and sign in again. On a machine without a browser, see [Sign in on a machine without a browser](getting-started.md#sign-in-on-a-machine-without-a-browser). |
| `auth_required` (remote server) | Your client sent no token, or ICS rejected it. | Reconnect the connector in your client so it signs in again. |
| `auth_timeout` | The sign-in was not finished in the browser within 5 minutes. | Ask again; a new sign-in starts. |
| `auth_denied` | You chose **Cancel** on the consent page, or ICS refused the request. | Ask again and choose **Allow** if you meant to connect. |
| `state_mismatch` | The browser came back with a different sign-in attempt than the one ics-mcp was waiting for. | Ask again, and finish only the newest sign-in tab. |
| `token_exchange_failed` | ICS refused to issue tokens after the consent; the error's `data` holds the reason ICS gave. | Try again. If it keeps failing, check that `ICS_MCP_RESOURCE_URI` and `ICS_MCP_OAUTH_CLIENT_ID` match the ICS setup. |
| The browser shows `invalid_target` | The `resource` (your `ICS_MCP_RESOURCE_URI`) is missing or not allowed by ICS. | Copy the exact value from your ICS administrator, including the scheme and path. |
| The browser shows `unauthorized_client` | ICS does not know the client ics-mcp signs in as (`ics-mcp-stdio` by default). ICS registers it only when MCP is enabled there. | Ask your ICS administrator to enable MCP (set `ICS_MCP_RESOURCE_URI` on the ICS side). |
| The browser shows a `403` page with "bad host" or "bad origin" after you allow | The sign-in redirect to `127.0.0.1` did not come straight from your browser, usually because a proxy or VPN intercepts local traffic. | Exclude `127.0.0.1` from the proxy or VPN and try again. |
| The browser never opens | ics-mcp could not start a browser. | Check the MCP logs of your client (see [Read the server logs](#read-the-server-logs)); after 5 minutes the tool returns `auth_timeout`. |

> [!NOTE]
> Refresh tokens change on every use, and ICS treats reuse of an old one as a theft attempt: it
> revokes the whole chain of tokens. After that you simply sign in again. You will not see this
> during normal use; it can happen if you copy keyring entries between machines.

## Connecting to ICS

| Code | What it means | What to do |
|---|---|---|
| `ics_unreachable` | ics-mcp could not connect to ICS. | Check `ICS_BASE_URL` (with `https://`), that ICS is up, and your network, VPN, DNS or firewall. |
| `rate_limited` | ICS kept answering "too many requests" after three automatic retries. | Wait a little. For big jobs, ask the assistant to filter on the ICS side and page through results, and to replace many files in one new version instead of one call per file. |
| `server_error`, `ics_error` | ICS failed. Reads are retried automatically on gateway errors; writes are not, because ICS may have applied them. | Check whether the change happened (for example with `ics_asset_versions`) before you ask again. |
| `unexpected_response`, `internal_error` | ICS answered in a shape ics-mcp did not expect, or ics-mcp hit a bug. | Often a version mismatch between ICS and ics-mcp. Update ics-mcp; if it persists, report it with the server log. |

## Confirmations

| Code | What it means | What to do |
|---|---|---|
| `confirm_required` | A gated operation was not confirmed. Either your client cannot show confirmation questions while the mode is `interactive`, or the call passed `confirm=false`. | Agree in the chat; the assistant then repeats the call with `confirm=true`. See [When your client cannot ask](confirmations-and-safety.md#when-your-client-cannot-ask). |
| `confirm_declined` | You declined the question. | Nothing was changed. |
| `yolo_disabled` | The assistant tried to switch the session to `yolo`, which this server does not allow. | Expected unless the operator set `ICS_MCP_ALLOW_YOLO=true`. Confirm single operations instead. |
| A destructive tool returned a preview and nothing changed | The session is in `dry_run`. | Ask the assistant to switch back to `interactive`. |

## Finding and reading

| Code | What it means | What to do |
|---|---|---|
| `asset_not_found`, `not_found` | The document does not exist, was deleted, or you cannot see it. For relations and graph tools it also means you have no graph access (a viewer share or a share link gives none). | Check the slug, for example by searching. Ask the owner for access if needed. |
| `invalid_argument` | An argument is wrong. `field` names it; for a fixed list of values, `data.allowed` lists them. | The assistant usually fixes this itself. |
| `file_too_large` | A file over 2000 lines was read without a line range. | Read it in parts (`lines`) or by section (outline, then `anchor`). |
| `line_range_too_wide` | The requested range is longer than allowed in one call. | Split the range. |
| `anchor_not_found` | The heading anchor does not exist in the current version. The hint lists the known anchors. | Pick one from the hint or from `ics_asset_outline`. |
| `outline_building` | ICS is still building the outline of a new version. | Read the file directly, or try again in a few seconds. |
| `binary_file` | An image, font or other binary file was read as text. | Usually not needed; if it is, read it with `encoding="base64"` (up to 1 MB). |
| `id_required` | `ics_asset_undelete` got a slug. Deleted documents can be restored only by their UUID. | Use the id from an earlier response (for example from `ics_assets_list` with `detail="full"` before the deletion). |

## Writing and uploading

| Code | What it means | What to do |
|---|---|---|
| `payload_too_large` | The upload exceeds the ics-mcp limit (100 MiB by default), or ICS refused its size. | Split the upload. The local limit is `ICS_MCP_MAX_UPLOAD_BYTES`; ICS has its own. |
| `storage_quota_exceeded` | Your storage quota in ICS is used up. | Delete documents or old versions you no longer need, or ask your administrator. |
| `invalid_argument` with "content_path is only available over stdio" or "file_path is only available over stdio" | You are on a [remote server](remote-http.md), which cannot read your disk. | Send the content inline, or upload PDF and Word files in the ICS web app. |
| `invalid_argument` with "file does not exist" or "no read permission" | The local path is wrong or not readable. | Check the path; `~` is expanded to your home directory. |
| `wrong_kind` | The tool does not fit this kind of document, for example replacing a Markdown document with a PDF. The hint names the right tool. | Let the assistant use the tool from the hint. |
| `document_file_required` | `ics_asset_create_document` got a file that is not `.pdf`, `.docx`, `.odt` or `.doc`. | Convert the file first. Spreadsheets and presentations are not supported. |
| `pdf_encrypted`, `office_encrypted` | The file is password protected. | Save an unprotected copy and upload that. |
| `invalid_pdf`, `invalid_office_document` | The file is damaged or not what its extension says. | Re-export or re-save it (for a legacy `.doc`, save it as `.docx`). |
| `pdf_extraction_failed`, `office_conversion_failed` | ICS could not extract the text in time. | Retry once; if it fails again, re-save the file or split it. |
| `pdf_too_large`, `office_too_large` | The file exceeds the ICS cap (50 MB by default; a Word file can also unpack to too much data). | Compress or remove large images, or split the document. |
| `ocr_in_progress`, `ocr_not_needed`, `ocr_not_supported` | An OCR request was refused: a run is active, every page already has text, or the document is not a PDF. | Wait for the active run, or skip OCR. |
| `doc_type_unknown` | The document type key does not exist or is archived. | Ask the assistant to list the types with `ics_doc_types`. |
| `metadata_invalid` | A metadata value is invalid; `field` names it. | Correct that field. |
| `maintainer_unknown` | The maintainer's e-mail is neither yours nor of someone the document is shared with. | Share the document with that person first. |

## Sharing

| Code | What it means | What to do |
|---|---|---|
| `share_forbidden` | You may not create share links for this document. Only its owner or the owner of its project can. | Ask the owner to share it. |
| `share_exists` | That person already has access. | Nothing to do, or revoke and grant again to change the role. |
| `share_with_owner` | You tried to grant access to the document's owner. | Not needed. |
| `weak_password` | The password for a password link is too weak for ICS. | Choose a stronger one. |
| `bad_share_link` | The pasted text is not a share link or a share token. | Paste the whole `https://.../s/<token>` address. |
| `share_password_required`, `share_password_invalid` | The link needs a password, or the password is wrong. ICS limits failed attempts. | Give the assistant the right password. |
| `share_login_required`, `share_access_denied` | The link needs a signed-in member of the organization, or is restricted in another way (for example to specific e-mail addresses). | Open it in the browser, or ask the owner for access. |
| `share_not_found`, `share_revoked`, `share_expired`, `share_spent` | The link does not exist, was revoked (or its document deleted), has expired, or reached its view limit. | Ask the owner for a new link. |

## Relations and tasks

| Code | What it means | What to do |
|---|---|---|
| `relation_exists` | The same relation is already recorded. | Nothing to do. |
| `relation_self` | A document cannot relate to itself. | Check source and target. |
| `relation_cycle` | `supersedes` and `part_of` must not form a loop. | Check the existing relations with `ics_graph_neighbourhood`. |
| `relation_anchor_invalid` | `relates_to` and `contradicts` cannot point at a heading. | Leave out the heading. |
| `relation_target_anchor_not_found`, `relation_target_path_not_found` | The heading or file in the target does not exist; `data` lists the valid ones. | Pick one from the list or leave it out. |
| `relation_limit` | The document has 200 relations. | Remove stale ones first. |
| `relation_not_found` | No such relation, or you cannot see both ends. | Take the id from `ics_asset_relations`. |
| `external_ref_invalid` | The task id is malformed. An OpenProject work package id is a number; a Project Standard node id looks like `n-...` and needs its project. | Correct the task id or add the project. |
| `external_ref_exists`, `external_ref_limit`, `external_ref_not_found` | The link already exists, the document has 100 task links, or the link does not exist (or you cannot edit its document). | See the document's links with `ics_asset_external_refs`. |
| `project_not_found`, `project_role_required` | The project does not exist or you are not a member, or the change needs the owner (or editor) role in the project. | Check `ics_projects_list`, or ask the project owner. |
| `project_external_taken` | This OpenProject or Project Standard project is already mapped to another ICS project. ICS does not say which. | Ask the owner of that ICS project to unmap it. |

## Read the server logs

ics-mcp writes its logs to standard error, never with tokens. Your MCP client shows them: in Claude
Desktop under Settings, Developer, Open MCP Logs. For more detail set `ICS_MCP_LOG_LEVEL=DEBUG` in
the `env` block and restart the client. To try tools by hand, the
[project README](https://github.com/inprojectspl/ics-mcp/blob/main/README.md#troubleshooting) shows how to run ics-mcp in the MCP Inspector.

## Related

- [Getting started](getting-started.md)
- [Confirmations and safety](confirmations-and-safety.md)
- [Remote use over HTTP](remote-http.md)
- [Everyday tasks](everyday-tasks.md)
