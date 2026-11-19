"""Set the manifest version exactly. Used by release.yml for pre-releases.

Usage: scripts/set_version.py X.Y.Z[bN]
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bump_version import write_version

if __name__ == "__main__":
    write_version(sys.argv[1])
