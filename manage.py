#!/usr/bin/env python
"""Repo-root shim so you can run `./manage.py ...` from anywhere in the tree.

Delegates to the real management script in src/mingadocs/.
"""
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src" / "mingadocs"


def main() -> None:
    sys.path.insert(0, str(SRC))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
