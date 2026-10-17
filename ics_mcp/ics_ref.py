"""Parse and format ICS references,
`ics://asset/<slug>[@v<N>][/file/<path>][#<anchor>]` with every optional part
independent of the others. The same grammar backs the resource templates and
every tool that accepts a reference."""

from __future__ import annotations

import re
from dataclasses import dataclass

SCHEME = "ics://"
_PREFIX = f"{SCHEME}asset/"
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_VERSION_RE = re.compile(r"^[1-9][0-9]*$")
_FILE_SEP = "/file/"


@dataclass(frozen=True, slots=True)
class IcsRef:
    slug: str
    version: int | None = None
    path: str | None = None
    anchor: str | None = None

    def __post_init__(self) -> None:
        validate_slug(self.slug)
        if self.version is not None and (
            isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1
        ):
            raise ValueError(f"version must be a positive integer, got {self.version!r}")
        if self.path is not None:
            validate_path(self.path)
        if self.anchor is not None and not self.anchor:
            raise ValueError("anchor must not be empty")

    def format(self) -> str:
        out = f"{_PREFIX}{self.slug}"
        if self.version is not None:
            out += f"@v{self.version}"
        if self.path is not None:
            out += f"{_FILE_SEP}{self.path}"
        if self.anchor is not None:
            out += f"#{self.anchor}"
        return out


def validate_slug(slug: str) -> str:
    if not slug:
        raise ValueError("slug must not be empty")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}: only letters, digits, '-' and '_' are allowed")
    return slug


def parse_version(raw: str) -> int:
    """`"2"` -> 2. Rejects zero, negatives, signs, leading zeros and non-digits."""
    if not _VERSION_RE.match(raw):
        raise ValueError(f"version must be a positive integer, got {raw!r}")
    return int(raw)


def validate_path(path: str) -> str:
    """A relative file path inside the asset: no traversal, no absolute paths."""
    if not path:
        raise ValueError("file path must not be empty")
    if "\\" in path or "\x00" in path:
        raise ValueError(f"invalid file path {path!r}")
    if path.startswith("/"):
        raise ValueError(f"file path must be relative, got {path!r}")
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            raise ValueError(f"invalid file path {path!r}: empty, '.' or '..' segment")
    return path


def parse_ref(uri: str) -> IcsRef:
    if not uri.startswith(SCHEME):
        raise ValueError(f"not an ICS reference (expected '{SCHEME}' scheme): {uri!r}")
    if not uri.startswith(_PREFIX):
        raise ValueError(f"unsupported ICS reference (expected '{_PREFIX}...'): {uri!r}")
    rest = uri[len(_PREFIX) :]

    anchor: str | None = None
    if "#" in rest:
        rest, anchor = rest.split("#", 1)
        if not anchor:
            raise ValueError(f"empty anchor in {uri!r}")

    path: str | None = None
    head = rest
    if _FILE_SEP in rest:
        head, path = rest.split(_FILE_SEP, 1)
    elif "/" in rest:
        raise ValueError(f"unexpected segment after the slug in {uri!r} (expected '/file/<path>')")

    version: int | None = None
    slug = head
    if "@" in head:
        slug, version_part = head.split("@", 1)
        if not version_part.startswith("v"):
            raise ValueError(f"version must look like '@v<N>' in {uri!r}")
        version = parse_version(version_part[1:])

    return IcsRef(slug=slug, version=version, path=path, anchor=anchor)
