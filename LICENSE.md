# Licensing

MakeYourTree is **free and open-source software, MIT-licensed throughout** — the library,
the command-line interface and the desktop application alike.

| Component | Path | Licence | SPDX identifier |
|---|---|---|---|
| MakeYourTree core — parsers, tree model, layout engine, annotation model, scene graph, SVG renderer, CLI | `src/makeyourtree/` | **MIT** | `MIT` |
| MakeYourTree Studio — the desktop application | `src/makeyourtree_studio/` | **MIT** | `MIT` |

Full text: [`LICENSES/MIT.txt`](LICENSES/MIT.txt).

You may use, copy, modify, merge, publish, distribute, sublicense and sell copies of
MakeYourTree, for any purpose, including commercially. The only conditions are the MIT
licence's own: keep the copyright notice and the permission notice with the software,
and accept that it comes with no warranty.

**Copyright © 2026 Manish Prakash Victor.**

## Why MIT

MakeYourTree exists to be used. A phylogenetics tool earns its keep through adoption,
citation and bug reports, and every condition placed on a reader is friction against all
three. MIT is the shortest licence that lets a laboratory, a course or a commercial
pipeline take the code without consulting a lawyer first, and it keeps the library
embeddable inside projects under any other licence.

There is no end-user licence agreement and nothing withheld. What is in
this repository is the whole of MakeYourTree.

## Meeting the LGPL obligations for Qt

**This section still applies, and it is the one part of MakeYourTree's licensing that needs
care.** Making our own code MIT changes who may use MakeYourTree; it does not change how Qt
must be shipped.

The desktop application links **PySide6/Qt 6**, which The Qt Company distributes under
**LGPL-3.0**. LGPL-3.0 §4 governs distributing a combined work that links an LGPL
library. It applies to anyone conveying a **binary** — us, or you, if you publish a
build of your own. Distributing *source* under MIT carries none of these obligations,
because the recipient links Qt themselves.

| LGPLv3 §4 | Requirement | How a MakeYourTree build satisfies it |
|---|---|---|
| §4(a) | Prominent notice that the Library is used and is LGPL-covered | Stated in `THIRD-PARTY-NOTICES.md` and in the application's **Help ▸ Third-Party Licences** dialog |
| §4(b) | Ship copies of the GPL and LGPL texts | `LICENSES/GPL-3.0.txt` and `LICENSES/LGPL-3.0.txt`, verbatim, included in every distribution |
| §4(c) | Reproduce the Library's copyright notice at runtime | Shown in the About dialog and the licences dialog |
| §4(d)(1) | Use a shared-library mechanism that links against a Qt copy at run time and works with a modified, interface-compatible Qt | **The build is PyInstaller `--onedir`**, which ships Qt as separate dynamically loaded `.dll` / `.so` / `.dylib` files that the user can replace. This is why `--onefile` is not used. |
| §4(e) | Installation Information where required | The relinking instructions in `THIRD-PARTY-NOTICES.md` |

Two further conditions that are easy to breach by accident:

1. **Qt ships unmodified.** If Qt or PySide6 is ever patched, those patches must be
   published under the LGPL. Do not patch them, and do not `strip` or UPX-pack the
   shipped libraries — both produce a modified Qt.
2. **No additional restrictions.** LGPL-3.0 §4 forbids terms that prohibit reverse
   engineering for debugging modifications to the Library. MIT imposes no such term, so
   this condition is now satisfied automatically. It is worth stating because it was
   previously satisfied only by an explicit carve-out in a proprietary EULA — if anyone
   ever wraps MakeYourTree in more restrictive terms again, that carve-out has to come back.

### Qt modules that are forbidden here

Some Qt add-ons are **GPL-3.0-only** in the open-source build:

- Qt Charts
- Qt Data Visualization
- Qt Virtual Keyboard

Importing one would make any distributed binary a GPL-3.0 work, which conflicts with
shipping the rest of MakeYourTree under MIT — recipients would lose the permissive terms
this project deliberately offers. MakeYourTree uses none of them; chart-like output comes
from our own track renderers in `makeyourtree.tracks`. A test in `tests/test_licensing.py`
fails the build if any module imports one, and the PyInstaller spec excludes them.

## Other dependencies

| Dependency | Licence | Obligation when distributing a binary |
|---|---|---|
| Python | PSF-2.0 | Notice only |
| NumPy | BSD-3-Clause | Notice + copyright retention |
| PySide6 / Qt 6 | LGPL-3.0 | As above — the one that needs care |

See [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) for the notices that must
accompany every binary distribution.
