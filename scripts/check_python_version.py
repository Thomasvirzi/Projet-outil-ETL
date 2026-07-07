#!/usr/bin/env python3
from __future__ import annotations

import sys


MIN_VERSION = (3, 12)
MAX_VERSION = (3, 13)


def main() -> None:
    version = sys.version_info
    if version < MIN_VERSION or version >= MAX_VERSION:
        current = f"{version.major}.{version.minor}.{version.micro}"
        minimum = ".".join(str(part) for part in MIN_VERSION)
        maximum = ".".join(str(part) for part in MAX_VERSION)
        raise SystemExit(
            "Unsupported Python version for this project: "
            f"{current}.\n"
            f"Please use Python >= {minimum} and < {maximum}, preferably Python 3.12.\n"
            "dbt and some dependencies are not currently compatible with Python 3.14."
        )


if __name__ == "__main__":
    main()
