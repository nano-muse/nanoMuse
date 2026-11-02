"""A console's own encoding, in both directions: what we print, and what we read back.

A Chinese Windows console is code page 936, and the check mark a report is made of is not in
GBK: ``nanomuse doctor > report.txt`` died with ``UnicodeEncodeError: 'gbk' codec can't
encode character '\\u2713'`` before printing a line, and the desktop shell reads the same
output through a pipe, which takes the locale's encoding. The three bridge programs print
what a phone or a page answered, Chinese among it, into the shell tool, which read it as
UTF-8: on that console the model was handed replacement characters. The frozen runtime the
desktop app carries does not read ``PYTHONUTF8`` or ``PYTHONUNBUFFERED`` either.

The other direction has the same cause: a program started on that console answers in 936, so
``cmd /c chcp`` reached the model as a row of replacement characters and a ``dir`` of a Chinese
folder was unreadable. :func:`decode_output` reads a child's bytes as UTF-8 when they are
UTF-8, and in the console's code page when they are not.

The standard library only: ``nanomuse-device`` and its two neighbours import this and must
stay cheap on a phone.
"""

from __future__ import annotations

import codecs
import contextlib
import locale
import sys


def utf8_console() -> None:
    """UTF-8 on stdout and stderr, line-buffered; a no-op where they already are."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def console_encoding() -> str:
    """The code page a program started from this process writes its output in.

    Asked of the console itself, because the locale is not always the answer: a console can
    be switched to another code page with ``chcp`` while the locale stays where it was. With
    no console at all (the desktop app's frozen runtime, a service) there is nothing to ask,
    and the locale's encoding is the closest thing to it.
    """
    codepage = _console_code_page()
    if codepage:
        return f"cp{codepage}"
    return locale.getpreferredencoding(False) or "utf-8"


def _console_code_page() -> int | None:
    """The console's output code page, where the platform has a console API to ask.

    No ``sys.platform`` test: the type checker folds one and calls everything after it
    unreachable, which fails the other platforms' builds. The attribute simply is not there
    where there is no console to ask, and that is what the suppression covers.
    """
    codepage = 0
    with contextlib.suppress(Exception):
        import ctypes

        codepage = int(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
    return codepage or None


_BOMS = (
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
    # Notepad's "UTF-8 with a mark" is still UTF-8, but the mark is not part of the text
    (codecs.BOM_UTF8, "utf-8"),
)


def decode_output(data: bytes | str) -> str:
    """A program's output as text: UTF-8 if it is UTF-8, else the console's code page.

    UTF-8 first and strictly, so a modern tool that names its encoding stays readable on a
    console whose code page says otherwise; only bytes that are not UTF-8 at all are read in
    that code page. A byte-order mark decides first of all, and is not part of the text:
    ``wsl.exe`` answers its own ``-l -q`` in UTF-16, and a file written by Notepad or by
    ``reg export`` starts with one of the other two. Bytes that fit neither are replaced
    rather than raised, because a command's output is a report and never worth a traceback.
    Text that arrives as text is passed through as it is: a caller that decoded it its own
    way (a test's stand-in for a command, a library that already read the pipe) has spoken.
    """
    if isinstance(data, str):
        return data
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data[len(bom) :].decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    encoding = console_encoding()
    if encoding.replace("-", "").lower() in {"utf8", "utf8mb4"}:
        return data.decode("utf-8", errors="replace")
    try:
        return data.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


__all__ = ["console_encoding", "decode_output", "utf8_console"]
