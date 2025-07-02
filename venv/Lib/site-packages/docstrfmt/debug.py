"""Debugging utilities for docstrfmt."""

from __future__ import annotations

from typing import Iterator

import docutils.nodes


def _dump_lines(node: docutils.nodes.Node) -> Iterator[tuple[int, str]]:
    """Dump a docutils node to a list of strings."""
    node_type = type(node).__name__
    head = f"- \x1b[34m{node_type}\x1b[m"
    if isinstance(node, docutils.nodes.Text):
        body = repr(node.astext()[:100])
    else:
        body = str({k: v for k, v in node.attributes.items() if v})
    yield 0, f"{head} {body}"
    for c in node.children:
        for n, line in _dump_lines(c):
            yield n + 1, line


def dump_node(node: docutils.nodes.Node) -> str:
    """Dump a docutils node to a string."""
    return "\n".join(["    " * indent + line for indent, line in _dump_lines(node)])
