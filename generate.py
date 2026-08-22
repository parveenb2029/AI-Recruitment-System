"""SUPERSEDED — this script has moved to tools/legacy/generate.py

This file is an inert stub. The original generator is preserved, unmodified,
at tools/legacy/generate.py.

Why it was retired
------------------
generate.py rewrites the ENTIRE project tree from a hardcoded path
(C:\\AI-Recruitment-System). It was how the original 136 documents were
produced. Now that those documents are hand-maintained, running it would
overwrite every edit with regenerated boilerplate.

As of the initial commit the documentation is the source of truth and this
generator is not.

Safe to delete this stub once the repository has been committed.
See CLAUDE.md -> "Hard rules".
"""

import sys

sys.exit(
    "\n"
    "generate.py is SUPERSEDED and must not be run.\n"
    "\n"
    "It overwrites the entire project tree from a hardcoded path, destroying\n"
    "hand-edited documentation. The original is preserved unmodified at\n"
    "    tools/legacy/generate.py\n"
    "\n"
    "See CLAUDE.md -> 'Hard rules'.\n"
)
