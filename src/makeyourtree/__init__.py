# SPDX-License-Identifier: MIT
"""MakeYourTree -- phylogenetic tree visualisation and annotation.

An independent, clean-room implementation.  Not affiliated with, endorsed by,
or derived from any other phylogenetics package.
"""

__version__ = "0.1.0"
__all__ = ["Tree", "Node", "load_tree", "save_tree", "compute_layout",
           "Document", "__version__"]


def __getattr__(name):
    # Lazy re-exports so `import makeyourtree` stays fast and free of cycles.
    if name in ("Tree", "Node"):
        from . import core
        return getattr(core, name)
    if name in ("load_tree", "save_tree"):
        from . import io
        return getattr(io, name)
    if name == "compute_layout":
        from .layout import compute_layout
        return compute_layout
    if name == "Document":
        from .doc import Document
        return Document
    raise AttributeError(f"module 'makeyourtree' has no attribute {name!r}")
