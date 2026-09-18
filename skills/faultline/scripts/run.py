#!/usr/bin/env python3
"""Portable entry point: no installation or third-party packages needed."""
import sys

# Installed skills can be read-only plugin-cache entries.
sys.dont_write_bytecode = True

from faultline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
