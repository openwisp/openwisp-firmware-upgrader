"""Exceptions for docstrfmt."""

from __future__ import annotations


class DocstrfmtError(Exception):
    """Base exception class for docstrfmt."""


class InvalidRstError(ValueError):
    """An error that occurred while parsing RST."""

    @property
    def error_message(self) -> str:
        """Return a formatted error message."""
        return (
            f"{self.level}: File"
            f' "{self.file}"{f", line {self.line}" if self.line else ""}:\n{self.message}'
        )

    def __init__(self, file: str, level: str, line: int, message: str):
        """Initialize an invalid RST error."""
        self.file = file
        self.level = level

        self.line = line
        self.message = message

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.error_message


class InvalidRstErrors(DocstrfmtError):
    """Container for multiple invalid RST errors."""

    def __init__(self, errors: list[InvalidRstError]):
        """Initialize the error container with a list of errors."""
        self.errors = errors

    def __str__(self) -> str:
        """Return a string representation of the errors."""
        return "\n".join([str(error) for error in self.errors])
