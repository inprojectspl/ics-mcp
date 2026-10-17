"""Page the browser shows when the OAuth redirect lands on the local callback.

It follows the look of the ICS sign-in screens (palette of ICS's
`frontend/src/styles/theme.css`, the ICS mark, one card on the canvas), all
inline: the loopback server has nothing else to serve. The error and its
description come from the query string, so both are escaped.
"""

from __future__ import annotations

from html import escape

# Small-size ICS mark (ICS `frontend/public/favicon.svg`).
_MARK = (
    '<svg width="28" height="28" viewBox="0 0 16 16" fill="none" aria-hidden="true"><g fill="#ff5500">'
    '<path d="m3 3 6 4 4-4M9 7 4 12M9 7l3 6" fill="none" stroke="#ff5500" stroke-width="1.25" '
    'stroke-linecap="round"/><circle cx="3" cy="3" r="1.75"/><circle cx="9" cy="7" r="2.25"/>'
    '<circle cx="13" cy="3" r="1.5"/><circle cx="4" cy="12" r="1.75"/><circle cx="12" cy="13" r="1.75"/>'
    "</g></svg>"
)
_ICON_OK = '<path d="M20 6 9 17l-5-5"/>'
_ICON_ERROR = '<path d="M12 8v5M12 16.5v.01"/>'

_CSS = """
:root{--canvas:#f5f7fa;--surface:#fff;--border:#dce3ec;--ink:#182332;--soft:#4b5b70;--mute:#64748b;
--ok:#147d59;--ok-soft:#e6f4ee;--bad:#b42332;--bad-soft:#fcebed;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--canvas:#101419;--surface:#181f28;--border:#323f51;
--ink:#f4f7fb;--soft:#b7c3d2;--mute:#a8b5c4;--ok:#5ad6a0;--ok-soft:#173a2e;--bad:#ff8b93;--bad-soft:#45222a}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
padding:48px 16px;background:var(--canvas);color:var(--ink);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif}
.brand{display:flex;align-items:center;gap:8px;margin-bottom:32px;font-weight:600;letter-spacing:.04em}
.card{width:100%;max-width:400px;background:var(--surface);border:1px solid var(--border);border-radius:14px;
padding:32px;text-align:center;box-shadow:0 1px 2px rgb(16 24 36/.06)}
.icon{display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:999px;
margin-bottom:16px}
.ok .icon{background:var(--ok-soft);color:var(--ok)}
.bad .icon{background:var(--bad-soft);color:var(--bad)}
h1{margin:0 0 6px;font-size:20px;line-height:1.35;font-weight:600}
p{margin:0;color:var(--soft)}
code{display:block;margin-top:16px;padding:8px 12px;border-radius:10px;border:1px solid var(--border);
font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mute);overflow-wrap:anywhere}
"""


def callback_page(error: str | None = None, description: str | None = None) -> str:
    """HTML for the browser tab: success, or the error the server sent back."""
    if error:
        state, icon, title = "bad", _ICON_ERROR, "Sign-in failed"
        body = "Return to your MCP client and sign in again."
        detail = f"<code>{escape(error)}{': ' + escape(description) if description else ''}</code>"
    else:
        state, icon, title = "ok", _ICON_OK, "Signed in to ICS"
        body = "You can close this tab and go back to your MCP client."
        detail = ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>ICS MCP: {title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="brand">{_MARK}<span>ICS</span></div>
<main class="card {state}">
  <span class="icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon}</svg></span>
  <h1>{title}</h1>
  <p>{body}</p>
  {detail}
</main>
</body>
</html>"""
