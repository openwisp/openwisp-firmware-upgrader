"""Handles adding constructs to the reST parser in a way that makes sense for docstrfmt.

Non-standard directives and roles are inserted into the tree unparsed (wrapped in custom
node classes defined here) so we can format them the way they came in without caring
about what they would normally expand to.

"""

from __future__ import annotations

from typing import Any, Iterator, TypeVar

import docutils
import sphinx
from docutils.parsers.rst import directives, roles
from docutils.parsers.rst.directives import body, images, misc, parts, tables
from sphinx.directives import code, other

try:  # pragma: no cover
    from sphinx.directives.admonitions import SeeAlso
except ImportError:  # pragma: no cover
    from sphinx.directives.other import SeeAlso

# Import these only to load their domain subclasses.
from sphinx.domains import c, changeset, cpp, python  # noqa: F401
from sphinx.ext import autodoc, autosummary
from sphinx.roles import generic_docroles, specific_docroles

from .const import ROLE_ALIASES

T = TypeVar("T")


def _add_directive(
    name: str,
    cls: type[docutils.parsers.rst.Directive],
    *,
    raw: bool = True,
    is_injected: bool = False,
) -> None:
    """Add a directive to the parser."""
    # We create a new class inheriting from the given directive class to automatically pick up the
    # argument counts and most of the other attributes that define how the directive is parsed, so
    # parsing can happen as normal. The things we change are:
    #
    # - Relax the option spec so an incorrect name doesn't stop formatting and every option comes
    #   through unchanged.
    # - Override the run method to just stick the directive into the tree.
    # - Add a `raw` attribute to inform formatting later on.
    namespace = {
        "option_spec": autodoc.directive.DummyOptionSpec(),
        "run": lambda self: [directive(directive=self)],
        "raw": raw,
        "has_content": True if is_injected else cls.has_content,
    }
    if is_injected:
        namespace["final_argument_whitespace"] = True
        namespace["optional_arguments"] = 1
    directives.register_directive(
        name, type(f"docstrfmt_{cls.__name__}", (cls,), namespace)
    )


def generic_role(r: str, rawtext: str, text: str, *_: Any, **__: Any) -> Any:
    """Provide a generic role that doesn't do anything."""
    r = ROLE_ALIASES.get(r.lower(), r)
    text = docutils.utils.unescape(text, restore_backslashes=True)
    return [role(rawtext, text=text, role=r)], []


def register() -> None:
    """Register the custom directives and roles."""
    for r in [
        # Standard roles (https://docutils.sourceforge.io/docs/ref/rst/roles.html) that don't have
        # equivalent non-role-based markup.
        "math",
        "pep-reference",
        "rfc-reference",
        "subscript",
        "superscript",
    ]:
        roles.register_canonical_role(r, generic_role)

    roles.register_canonical_role("download", ReferenceRole())
    for domain in _subclasses(sphinx.domains.Domain):
        for name, role_callable in domain.roles.items():
            if isinstance(role_callable, sphinx.util.docutils.ReferenceRole):
                roles.register_canonical_role(name, ReferenceRole())
                roles.register_canonical_role(f"{domain.name}:{name}", ReferenceRole())

        for name, directive_callable in domain.directives.items():
            _add_directive(name, directive_callable)
            _add_directive(f"{domain.name}:{name}", directive_callable)

    for name, _nodeclass in generic_docroles.items():
        roles.register_local_role(name, generic_role)

    for name, _func in specific_docroles.items():
        roles.register_local_role(name, generic_role)

    # docutils directives
    _add_directive("contents", parts.Contents)
    _add_directive("figure", images.Figure, raw=False)
    _add_directive("image", images.Image)
    _add_directive("include", misc.Include)
    _add_directive("list-table", tables.ListTable, raw=False)
    _add_directive("csv-table", tables.CSVTable, raw=False)
    _add_directive("rst-table", tables.RSTTable, raw=False)
    _add_directive("rst-class", misc.Class)
    _add_directive("math", body.MathBlock)
    _add_directive("meta", misc.Meta)
    _add_directive("raw", misc.Raw)

    # sphinx directives
    _add_directive("autosummary", autosummary.Autosummary)
    _add_directive("code-block", code.CodeBlock)
    _add_directive("deprecated", changeset.VersionChange, raw=False)
    _add_directive("highlight", code.Highlight)
    _add_directive("literalinclude", code.LiteralInclude)
    _add_directive("seealso", SeeAlso, raw=False)
    _add_directive("toctree", other.TocTree)
    _add_directive("versionadded", changeset.VersionChange, raw=False)
    _add_directive("versionchanged", changeset.VersionChange, raw=False)

    for d in set(_subclasses(autodoc.Documenter)):
        if d.objtype != "object":
            _add_directive(
                f"auto{d.objtype}", autodoc.directive.AutodocDirective, raw=False
            )

    try:
        import sphinxarg.ext
    except ImportError:
        pass
    else:  # pragma: no cover
        _add_directive("argparse", sphinxarg.ext.ArgParseDirective)


class ReferenceRole(sphinx.util.docutils.ReferenceRole):
    """Role that doesn't do anything."""

    def run(
        self,
    ) -> tuple[list[docutils.nodes.Node], list[docutils.nodes.system_message]]:
        """Run the role."""
        node = ref_role(
            self.rawtext,
            name=self.name,
            has_explicit_title=self.has_explicit_title,
            target=self.target,
            title=self.title,
        )
        return [node], []


class directive(docutils.nodes.Element):  # noqa: N801
    """A directive that doesn't do anything."""


class ref_role(docutils.nodes.Element):  # noqa: N801
    """A role that doesn't do anything."""


class role(docutils.nodes.Element):  # noqa: N801
    """A role that doesn't do anything."""


def _subclasses(cls: type[T]) -> Iterator[type[T]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)
