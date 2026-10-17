"""Server identity surfaced in `initialize` and tool metadata."""

from ics_mcp import __protocol_version__, __version__

SERVER_INFO = {
    "name": "ics-mcp",
    "version": __version__,
    "title": "ICS - Internal Content Sharing",
    "description": (
        "Read, write, share, and organize ICS assets in the logged-in user's "
        "name. Token-efficient list/outline endpoints, async outline rebuilds, "
        "OAuth 2.1 + PKCE + RFC 8707."
    ),
    "websiteUrl": "https://github.com/inprojectspl/ics",
}

INSTRUCTIONS = (
    "Use ICS through these tools as the user's personal CMS. "
    "Start with `ics_help()` or `ics_assets_list()`; work on a task (an OpenProject "
    "work package or a Project Standard node) starts with `ics_task_context`, and "
    "documents related to one document are found with `ics_graph_neighbourhood` "
    "(`ics_help('graph')`). Reading: up to 800 `estimated_tokens`, or when you need most "
    "of it, read the whole document; otherwise `ics_asset_outline` (no `edges`), then "
    "`ics_asset_read(anchor=...)`. "
    "For destructive "
    "operations honour the session mode (`ics_session_set_mode`) and the `confirm` flag. "
    "Multi-file uploads (create_collection, create_html, new_version, html_replace_bundle) "
    "report progress: one step per file and a final one after ICS responds. "
    "PDF and Word/ODF files are uploaded from a local path with "
    "`ics_asset_create_document` and read as Markdown with `ics_asset_read`."
)

PROTOCOL_VERSION = __protocol_version__
