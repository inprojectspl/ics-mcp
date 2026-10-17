"""Check that a JSON key holds a list of the expected length (the CI
mcp-inspector job counts tools, resource templates and prompts). A script
because inline f-strings in YAML clash with flow-mapping syntax.

Usage: python scripts/assert_count.py <path> <key> <expected_count>"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: assert_count.py <json-path> <key> <expected-count>", file=sys.stderr)
        return 2
    path, key, expected_s = sys.argv[1], sys.argv[2], sys.argv[3]
    expected = int(expected_s)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    items = data.get(key)
    if not isinstance(items, list):
        print(f"FAIL: {path} has no list at '{key}' (got {type(items).__name__})", file=sys.stderr)
        return 1
    got = len(items)
    if got != expected:
        print(f"FAIL: expected {expected} {key}, got {got}", file=sys.stderr)
        return 1
    print(f"OK: {got} {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
