"""Constants for docstrfmt."""

# pragma: no cover

DEFAULT_EXCLUDE = [
    "**/.direnv/",
    "**/.direnv/",
    "**/.eggs/",
    "**/.git/",
    "**/.hg/",
    "**/.mypy_cache/",
    "**/.nox/",
    "**/.tox/",
    "**/.venv/",
    "**/.svn/",
    "**/_build",
    "**/buck-out",
    "**/build",
    "**/dist",
]
SECTION_CHARS = "=-~+.'\"`^_*:#"
ROLE_ALIASES = {
    "pep": "PEP",
    "pep-reference": "PEP",
    "rfc": "RFC",
    "rfc-reference": "RFC",
    "subscript": "sub",
    "superscript": "sup",
}
