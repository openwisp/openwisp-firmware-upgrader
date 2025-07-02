"""Utility functions for docstrfmt."""

from __future__ import annotations

import pickle
import sys
import tempfile
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from docutils.parsers.rst.states import ParserError
from docutils.utils import roman
from platformdirs import user_cache_path

if TYPE_CHECKING:  # pragma: no cover
    import click


def get_code_line(current_file: Path, code: str, strict: bool = False) -> int:
    """Get the line number of the code in the file."""
    with (
        nullcontext(sys.stdin)
        if current_file.name == "-"
        else current_file.open(encoding="utf-8")
    ) as f:
        source = f.read()
    lines = source.splitlines()
    code_lines = code.splitlines()
    multiple = len([line for line in lines if code_lines[0] in line]) > 1
    for line_number, line in enumerate(lines, 1):  # noqa: RET503
        if line.endswith(code_lines[0]) if strict else code_lines[0] in line:
            if multiple:
                current_offset = 0
                for offset, sub_line in enumerate(code_lines):
                    current_offset = offset
                    if not (
                        lines[line_number - 1 + offset].endswith(sub_line)
                        if strict
                        else sub_line in lines[line_number - 1 + offset]
                    ):
                        break
                else:
                    return line_number + current_offset
            else:
                return line_number


# Modified from docutils.parsers.rst.states.Body
def make_enumerator(ordinal: int, sequence: str, fmt: tuple[str, str]) -> str:
    """Construct and return the next enumerated list item marker, and an auto-enumerator ("#" instead of the regular enumerator).

    Return ``None`` for invalid (out of range) ordinals.

    """
    if sequence == "#":  # pragma: no cover
        enumerator = "#"
    elif sequence == "arabic":
        enumerator = str(ordinal)
    else:
        if sequence.endswith("alpha"):
            if ordinal > 26:  # pragma: no cover
                return None
            enumerator = chr(ordinal + ord("a") - 1)
        elif sequence.endswith("roman"):
            try:
                enumerator = roman.toRoman(ordinal)
            except roman.RomanError:  # pragma: no cover
                return None
        else:  # pragma: no cover
            msg = f'unknown enumerator sequence: "{sequence}"'
            raise ParserError(msg)
        if sequence.startswith("lower"):
            enumerator = enumerator.lower()
        elif sequence.startswith("upper"):
            enumerator = enumerator.upper()
        else:  # pragma: no cover
            msg = f'unknown enumerator sequence: "{sequence}"'
            raise ParserError(msg)
    return fmt[0] + enumerator + fmt[1]


class FileCache:
    """A class to manage the cache of files."""

    @staticmethod
    def _get_file_info(file):  # noqa: ANN001,ANN205
        file_info = file.stat()
        return file_info.st_mtime, file_info.st_size

    def __init__(self, context: click.Context, ignore_cache: bool = False):
        """Initialize the cache."""
        from . import __version__

        self.cache_dir = user_cache_path("docstrfmt", version=__version__)
        self.context = context
        self.cache = self._read_cache()
        self.ignore_cache = ignore_cache

    def _get_cache_filename(self):
        docstring_trailing_line = str(self.context.params["docstring_trailing_line"])
        line_length = str(self.context.params["line_length"])
        mode = self.context.params["mode"].get_cache_key()
        include_txt = str(self.context.params["include_txt"])
        return (
            self.cache_dir
            / f"cache.{f'{docstring_trailing_line}_{line_length}_{mode}_{include_txt}'}.pickle"
        )

    def _read_cache(self):
        """Read the cache file."""
        cache_file = self._get_cache_filename()
        if not cache_file.exists():
            return {}
        with cache_file.open("rb") as f:
            try:
                return pickle.load(f)  # noqa: S301
            except (pickle.UnpicklingError, ValueError):  # pragma: no cover
                return {}

    def gen_todo_list(self, files: list[str]) -> tuple[set[Path], set[Path]]:
        """Generate the list of files to process."""
        todo, done = set(), set()
        for file in (Path(f).resolve() for f in files):
            if self.cache.get(file) != self._get_file_info(file) or self.ignore_cache:
                todo.add(file)
            else:  # pragma: no cover
                done.add(file)
        return todo, done

    def write_cache(self, files: list[Path]) -> None:
        """Update the cache file."""
        cache_file = self._get_cache_filename()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            new_cache = {
                **self.cache,
                **{file.resolve(): self._get_file_info(file) for file in files},
            }
            with tempfile.NamedTemporaryFile(
                dir=str(cache_file.parent), delete=False
            ) as f:
                pickle.dump(new_cache, f, protocol=4)
            Path(f.name).replace(cache_file)
        except OSError:  # pragma: no cover
            pass


class LineResolver:
    """A class to resolve the line number of a code block in a file."""

    def __init__(self, file: Path, source: str):
        """Initialize the class."""
        self.file = file
        self.source = source
        self._results = defaultdict(list)
        self._searches = set()

    def offset(self, code: str) -> int:
        """Get the line number of the code in the file."""
        if code not in self._searches:
            if code not in self.source:  # pragma: no cover should be impossible
                msg = f"Code not found in {self.file}"
                raise ValueError(msg)
            self._searches.add(code)
            split = self.source.split(code)
            for i, _block in enumerate(split[:-1]):
                self._results[code].append(code.join(split[: i + 1]).count("\n") + 1)
        if not self._results[code]:  # pragma: no cover should be impossible
            msg = f"Code not found in {self.file}"
            raise ValueError(msg)
        return self._results[code].pop(0)


class plural:  # noqa: N801
    """A class to format a number with a singular or plural form."""

    def __format__(self, format_spec: str) -> str:
        """Format the number with a singular or plural form."""
        v = self.value
        singular_form, _, plural_form = format_spec.partition("|")
        plural_form = plural_form or f"{singular_form}s"
        if abs(v) != 1:
            return f"{v:,} {plural_form}"
        return f"{v:,} {singular_form}"

    def __init__(self, value: int):
        """Initialize the class with a number."""
        self.value: int = value
