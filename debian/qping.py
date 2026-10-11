#!/usr/bin/python3
"""QPing launcher for the Debian package.

Delegates to main_entry() so logging, argv handling, and any future
startup hooks are set up in exactly one place.
"""
import sys

sys.path.insert(0, "/usr/lib/python3/dist-packages/qping")

from main import main_entry

if __name__ == "__main__":
    sys.exit(main_entry())
