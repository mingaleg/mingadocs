"""Minimal type stubs for the parts of pycups (``import cups``) this project
uses: connecting to CUPS, listing queues, and submitting a file.

Upstream ships no type information. See ``arnlabels/printing.py``.
"""

class IPPError(Exception):
    args: tuple[int, str]

class Connection:
    def __init__(
        self,
        host: str = ...,
        port: int = ...,
        encryption: int = ...,
    ) -> None: ...
    def getPrinters(self) -> dict[str, dict[str, str | int | bool | list[str]]]: ...
    def printFile(
        self,
        printer: str,
        filename: str,
        title: str,
        options: dict[str, str],
    ) -> int: ...
