# SPDX-License-Identifier: MIT
"""Distribution packaging for MakeYourTree Studio.

Kept inside the installed package rather than in a top-level ``tools/`` directory
so the spec, the build driver and the verification rules travel with the code
they describe. A checkout of the source is always enough to reproduce a shippable
bundle, and the test suite can import the verification logic directly.

``makeyourtree.spec`` is licence-critical — read its header before editing it.

The ``build()`` driver function is deliberately *not* re-exported here: binding it
at package level would shadow the ``build`` submodule, so ``packaging.build``
would resolve to a function rather than the module. Call
``makeyourtree_studio.packaging.build.build`` instead.
"""

from __future__ import annotations

from .build import (
    APP_NAME,
    SPEC_PATH,
    BuildError,
    Check,
    assert_verified,
    verify_bundle,
    verify_spec,
)

__all__ = [
    "APP_NAME",
    "SPEC_PATH",
    "BuildError",
    "Check",
    "assert_verified",
    "verify_bundle",
    "verify_spec",
]
