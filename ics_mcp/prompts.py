"""Reusable workflows exposed as MCP prompts: scripted starters, the work itself
happens in tools."""

from __future__ import annotations

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="share_with_team",
        title="Share a file with the team",
        description="Creates a share link (org_sso or password) and explains how to send it out.",
    )
    def share_with_team(
        asset_slug: str,
        mode: str = "org_sso",
        password_hint: str | None = None,
    ) -> str:
        steps = [
            f"1. Call `ics_asset_meta(slug_or_id='{asset_slug}')` to verify the title.",
            f"2. Call `ics_share_create_link(slug_or_id='{asset_slug}', mode='{mode}'"
            + (", password='...'" if mode == "password" else "")
            + ")`. It returns the full URL.",
            "3. Paste the URL into a Slack/email message with a short note on what it contains.",
        ]
        if password_hint:
            steps.append(f"4. Send the password over a separate channel (e.g. {password_hint}).")
        return "\n".join(steps)

    @mcp.prompt(
        name="summarize_collection",
        title="Summarize a collection",
        description="Fetches the outline, reads selected files and writes a summary.",
    )
    def summarize_collection(slug: str, max_files: int = 5) -> str:
        return (
            f"Step 1: `ics_asset_outline(slug_or_id='{slug}')` → pick the "
            f"{max_files} most important files (entry_path + top-level "
            "wikilinks).\n"
            "Step 2: For each of them call `ics_asset_read(slug_or_id, path, "
            "lines='1-200')`.\n"
            "Step 3: Write the summary in the user's language, 3 bullet points per file, "
            "then 1 synthesis of the whole."
        )

    @mcp.prompt(
        name="migrate_to_collection",
        title="Convert md_single → md_collection",
        description="Workflow for moving md_single content into a new collection.",
    )
    def migrate_to_collection(
        source_slug: str,
        new_title: str,
        first_filename: str = "index.md",
    ) -> str:
        return (
            f"1. `ics_asset_read(slug_or_id='{source_slug}')` → keep the content.\n"
            f"2. `ics_asset_create_collection(title='{new_title}', files=[{{path:"
            f" '{first_filename}', content: <content>}}])`.\n"
            f"3. (Optional) `ics_asset_delete(slug_or_id='{source_slug}')` after"
            " verification.\n"
            "4. Return the new slug to the user. Shares of the source do not carry over"
            " automatically: check `ics_shares_list` on the old slug and"
            " recreate the mode on the new one (`share_mode` in step 2 or"
            " `ics_share_create_link`)."
        )
