"""Compatibility entry point for older configs. Prefer the `mdb-mcp` command."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mdb_mcp.server import main  # noqa: E402

main()
