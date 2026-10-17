"""ICS reference parser: round-trip of every form and rejection of bad input."""

from __future__ import annotations

import pytest

from ics_mcp.ics_ref import IcsRef, parse_ref, parse_version


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("ics://asset/abc", IcsRef("abc")),
        ("ics://asset/abc@v2", IcsRef("abc", version=2)),
        ("ics://asset/abc/file/notes/intro.md", IcsRef("abc", path="notes/intro.md")),
        (
            "ics://asset/abc@v12/file/notes/intro.md#setup-steps",
            IcsRef("abc", version=12, path="notes/intro.md", anchor="setup-steps"),
        ),
        ("ics://asset/abc#top", IcsRef("abc", anchor="top")),
        ("ics://asset/abc@v3#top", IcsRef("abc", version=3, anchor="top")),
        ("ics://asset/abc/file/index.html", IcsRef("abc", path="index.html")),
    ],
)
def test_round_trip(uri, expected):
    ref = parse_ref(uri)
    assert ref == expected
    assert ref.format() == uri


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "https://asset/abc",
        "ICS://asset/abc",
        "ics://project/abc",
        "ics://asset/",
        "ics://asset/@v2",
        "ics://asset/ab c",
        "ics://asset/abc@v0",
        "ics://asset/abc@v-1",
        "ics://asset/abc@v01",
        "ics://asset/abc@vx",
        "ics://asset/abc@v",
        "ics://asset/abc@2",
        "ics://asset/abc@v1.5",
        "ics://asset/abc/outline",
        "ics://asset/abc/file/",
        "ics://asset/abc/file/../secret.md",
        "ics://asset/abc/file/notes/../../x.md",
        "ics://asset/abc/file/./x.md",
        "ics://asset/abc/file//etc/passwd",
        "ics://asset/abc/file/notes//x.md",
        "ics://asset/abc/file/notes\\x.md",
        "ics://asset/abc#",
    ],
)
def test_invalid_refs_raise(uri):
    with pytest.raises(ValueError):
        parse_ref(uri)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slug": ""},
        {"slug": "abc", "version": 0},
        {"slug": "abc", "version": True},
        {"slug": "abc", "path": ".."},
        {"slug": "abc", "anchor": ""},
    ],
)
def test_invalid_dataclass_raises(kwargs):
    with pytest.raises(ValueError):
        IcsRef(**kwargs)


def test_parse_version():
    assert parse_version("7") == 7
    for bad in ("0", "-3", "+3", "03", "", "3a"):
        with pytest.raises(ValueError):
            parse_version(bad)
