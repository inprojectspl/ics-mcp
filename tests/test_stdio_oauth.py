"""Stdio OAuth flow: PKCE, DNS rebinding guard, callback handler, token
exchange. The interactive `login()` path is exercised end-to-end with a
mock `webbrowser.open` that hits the loopback callback directly,
simulating an OAuth provider redirect.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from ics_mcp.auth import stdio_oauth as oauth
from ics_mcp.auth.token_store import TokenStore
from ics_mcp.errors import ICSError

# ============================================================
#  Pure helpers
# ============================================================


def test_b64u_nopad_strips_padding():
    assert oauth._b64u_nopad(b"abc") == "YWJj"
    assert "=" not in oauth._b64u_nopad(b"abcd")
    assert "=" not in oauth._b64u_nopad(b"\x00\x01")


def test_gen_pkce_produces_s256_pair():
    verifier, challenge = oauth._gen_pkce()
    assert 43 <= len(verifier) <= 128
    assert 43 <= len(challenge) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected


def test_gen_pkce_is_random_each_call():
    pairs = {oauth._gen_pkce() for _ in range(20)}
    assert len(pairs) == 20


def test_pick_free_port_returns_loopback_bound_port():
    port = oauth._pick_free_port()
    assert 1024 < port < 65536


def test_is_headless_true_when_ci_set_and_no_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setenv("CI", "true")
    assert oauth._is_headless() is True


def test_is_headless_false_when_display_present(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setenv("CI", "true")
    assert oauth._is_headless() is False


def test_is_headless_false_when_ci_unset(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ICS_MCP_FORCE_HEADLESS", raising=False)
    assert oauth._is_headless() is False


def test_build_authorize_url_includes_all_mandatory_params(settings):
    url = oauth._build_authorize_url(
        settings,
        redirect_uri="http://127.0.0.1:5555/callback",
        state="state-abc",
        code_challenge="challenge-xyz",
    )
    # Every parameter required by OAuth 2.1 and RFC 8707 is present.
    for needle in [
        "response_type=code",
        "client_id=ics-mcp-stdio",
        "redirect_uri=http",
        "scope=ics",
        "code_challenge=challenge-xyz",
        "code_challenge_method=S256",
        "resource=",
        "state=state-abc",
    ]:
        assert needle in url, f"missing {needle!r}"


# ============================================================
#  Loopback callback handler (DNS rebinding + state + code paths)
# ============================================================


async def _send_request(
    port: int, path: str, *, host: str = "127.0.0.1", origin: str = ""
) -> tuple[int, str]:
    """Bare TCP client that bypasses httpx URL normalization so we can
    exercise the Host/Origin guards with bad values."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    request = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if origin:
        request += f"Origin: {origin}\r\n"
    request += "\r\n"
    writer.write(request.encode())
    await writer.drain()
    status_line = (await reader.readline()).decode("ascii", "replace")
    status_code = int(status_line.split()[1])
    body = (await reader.read(4096)).decode("ascii", "replace")
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return status_code, body


@pytest.mark.asyncio
async def test_loopback_accepts_valid_callback_extracts_code():
    port = oauth._pick_free_port()
    expected_state = "state-xyz"
    task = asyncio.create_task(oauth._run_loopback(port, expected_state))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(port, f"/callback?code=abc123&state={expected_state}")
    result = await asyncio.wait_for(task, timeout=2)
    assert status == 200
    assert result.code == "abc123"
    assert result.state == expected_state


@pytest.mark.asyncio
async def test_loopback_rejects_bad_host_header_403():
    """DNS rebinding guard: a Host other than 127.0.0.1 must 403."""
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "state-x"))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(
        port, "/callback?code=abc&state=state-x", host="evil.example.com"
    )
    # Cancel the still-running task: bad host returns 403 without
    # setting `server_done`.
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert status == 403


@pytest.mark.asyncio
async def test_loopback_rejects_foreign_origin_403():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "state-x"))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(
        port,
        "/callback?code=abc&state=state-x",
        origin="https://evil.example",
    )
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert status == 403


@pytest.mark.asyncio
async def test_loopback_state_mismatch_raises_csrf_error():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "expected-state"))
    await asyncio.sleep(0.05)
    await _send_request(port, "/callback?code=abc&state=wrong-state")
    with pytest.raises(ICSError) as exc:
        await asyncio.wait_for(task, timeout=2)
    assert exc.value.code == "state_mismatch"


@pytest.mark.asyncio
async def test_loopback_error_in_query_string_surfaces():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    await _send_request(
        port,
        "/callback?error=access_denied&error_description=user%20said%20no&state=s",
    )
    with pytest.raises(ICSError) as exc:
        await asyncio.wait_for(task, timeout=2)
    assert exc.value.code == "auth_denied"
    assert "user said no" in exc.value.message


@pytest.mark.asyncio
async def test_loopback_missing_code_raises():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    await _send_request(port, "/callback?state=s")
    with pytest.raises(ICSError) as exc:
        await asyncio.wait_for(task, timeout=2)
    assert exc.value.code == "auth_no_code"


@pytest.mark.asyncio
async def test_loopback_rejects_non_callback_path():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(port, "/")
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert status == 404


# ============================================================
#  Full login() flow with mocked browser
# ============================================================


@pytest.fixture
def store(tmp_path) -> TokenStore:
    s = TokenStore(service=f"stdio-test-{tmp_path.name}", fallback_path=tmp_path / "creds")
    yield s
    s.delete()


@pytest.mark.asyncio
async def test_login_headless_raises_with_authorization_url(settings, store, monkeypatch):
    """Headless context, no browser to open. Should return a structured
    error containing the URL so the user can paste it manually elsewhere."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(ICSError) as exc:
        await oauth.login(settings, store)
    assert exc.value.code == "auth_required"
    assert "authorization_url" in (exc.value.data or {})
    url = exc.value.data["authorization_url"]
    assert "response_type=code" in url
    assert "code_challenge_method=S256" in url
    assert "resource=" in url


@pytest.mark.asyncio
async def test_loopback_rejects_host_that_only_starts_with_loopback():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(
        port, "/callback?code=abc&state=s", host="127.0.0.1.evil.example"
    )
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert status == 403


@pytest.mark.asyncio
async def test_loopback_escapes_error_description():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    _, body = await _send_request(
        port,
        "/callback?error=x&error_description=%3Cscript%3Ealert(1)%3C%2Fscript%3E&state=s",
    )
    with pytest.raises(ICSError):
        await asyncio.wait_for(task, timeout=2)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


@pytest.mark.asyncio
async def test_stray_request_does_not_end_the_flow():
    port = oauth._pick_free_port()
    task = asyncio.create_task(oauth._run_loopback(port, "s"))
    await asyncio.sleep(0.05)
    status, _ = await _send_request(port, "/favicon.ico")
    assert status == 404
    assert not task.done()
    await _send_request(port, "/callback?code=abc&state=s")
    result = await asyncio.wait_for(task, timeout=2)
    assert result.code == "abc"


def _browser_that_approves(sent: list, *, code: str = "auth-code", state: str | None = None):
    """Stand-in for `webbrowser.open`: acts as the provider redirecting
    back to the loopback callback advertised in the authorize URL."""

    def _open(url: str) -> bool:
        query = parse_qs(urlsplit(url).query)
        callback = urlsplit(query["redirect_uri"][0])
        cb_state = state if state is not None else query["state"][0]
        sent.append(query)

        async def _redirect() -> None:
            await asyncio.sleep(0.05)
            await _send_request(callback.port, f"/callback?code={code}&state={cb_state}")

        sent.append(asyncio.get_running_loop().create_task(_redirect()))
        return True

    return _open


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr(oauth, "_is_headless", lambda: False)


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_login_exchanges_code_with_pkce_and_stores_pair(
    settings, store, interactive, monkeypatch, respx_mock
):
    sent: list = []
    monkeypatch.setattr(oauth.webbrowser, "open", _browser_that_approves(sent))
    token = respx_mock.post(settings.token_url).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
        )
    )

    pair = await oauth.login(settings, store)

    authorize = sent[0]
    form = parse_qs(token.calls[0].request.content.decode())
    verifier = form["code_verifier"][0]
    challenge = oauth._b64u_nopad(hashlib.sha256(verifier.encode()).digest())
    assert authorize["code_challenge"] == [challenge]
    assert form["code"] == ["auth-code"]
    assert form["grant_type"] == ["authorization_code"]
    assert form["redirect_uri"] == authorize["redirect_uri"]
    assert form["resource"] == [settings.mcp_resource_uri]
    assert pair.access_token == "acc"
    assert pair.resource == settings.mcp_resource_uri
    assert store.load_fresh() == pair


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_login_rejects_callback_with_foreign_state(
    settings, store, interactive, monkeypatch, respx_mock
):
    sent: list = []
    monkeypatch.setattr(oauth.webbrowser, "open", _browser_that_approves(sent, state="forged"))
    token = respx_mock.post(settings.token_url)
    with pytest.raises(ICSError) as exc:
        await oauth.login(settings, store)
    assert exc.value.code == "state_mismatch"
    assert token.call_count == 0
    assert store.load_fresh() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(502, text="bad gateway"),
    ],
)
@respx.mock(assert_all_called=True)
async def test_login_token_exchange_failure_stores_nothing(
    settings, store, interactive, monkeypatch, respx_mock, response
):
    sent: list = []
    monkeypatch.setattr(oauth.webbrowser, "open", _browser_that_approves(sent))
    respx_mock.post(settings.token_url).mock(return_value=response)
    with pytest.raises(ICSError) as exc:
        await oauth.login(settings, store)
    assert exc.value.code == "token_exchange_failed"
    assert exc.value.status == response.status_code
    assert store.load_fresh() is None


@pytest.mark.asyncio
async def test_login_times_out_with_authorization_url(settings, store, interactive, monkeypatch):
    def _broken_browser(url: str) -> bool:
        raise RuntimeError("no browser")

    monkeypatch.setattr(oauth.webbrowser, "open", _broken_browser)
    monkeypatch.setattr(oauth, "_FLOW_TIMEOUT_S", 0.1)
    with pytest.raises(ICSError) as exc:
        await oauth.login(settings, store)
    assert exc.value.code == "auth_timeout"
    assert exc.value.data["authorization_url"].startswith(settings.authorize_url)


def test_callback_page_confirms_or_explains_and_escapes() -> None:
    from ics_mcp.auth.callback_page import callback_page

    ok = callback_page()
    assert "Signed in to ICS" in ok
    assert 'class="card ok"' in ok
    bad = callback_page("access_denied", "<script>alert(1)</script>")
    assert "Sign-in failed" in bad
    assert "access_denied" in bad
    assert "<script>" not in bad
    assert "&lt;script&gt;" in bad
