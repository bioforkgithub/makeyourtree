# Third-party notices

MakeYourTree incorporates the components below. MakeYourTree's own code is MIT-licensed; each
component listed here is governed by its own licence, which prevails over MakeYourTree's MIT
terms for that component.

**This file must accompany every binary distribution of MakeYourTree Studio**, and its
contents must be reachable at runtime from **Help ▸ Third-Party Licences**. That is a
licence obligation, not a courtesy — see LGPL-3.0 §4(a) and §4(c). It applies to anyone
who redistributes a build, not only to us.

---

## Qt 6 and Qt for Python (PySide6)

- **Copyright** © The Qt Company Ltd. and other contributors.
- **Licence: GNU Lesser General Public License, version 3 (LGPL-3.0-only).**
- Full texts: [`LICENSES/LGPL-3.0.txt`](LICENSES/LGPL-3.0.txt) and
  [`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt). LGPL-3.0 is drafted as GPL-3.0 plus
  additional permissions, so **both** texts are required.
- Home: <https://www.qt.io/> · <https://doc.qt.io/qtforpython-6/licenses.html>

**Qt is distributed unmodified.** No patches have been applied to Qt or to PySide6.

### Your right to replace Qt (LGPL-3.0 §4(d)(1))

MakeYourTree Studio links Qt dynamically. The Qt libraries ship as **separate shared library
files** inside the distribution, not statically linked and not embedded in the executable.
You may replace them with your own interface-compatible build of Qt, and the application is
intended to run against such a build.

To do so:

1. Locate the Qt shared libraries in the installation directory. On Windows these are the
   `Qt6*.dll` files and the `PySide6/plugins/` directory; on Linux, `libQt6*.so.6`; on
   macOS, the `Qt*.framework` bundles.
2. Build or obtain a Qt 6 release that is binary-compatible with the version recorded in
   **Help ▸ About** (Qt guarantees binary compatibility across patch releases within a
   minor series).
3. Replace the corresponding files, keeping the file names and directory layout.
4. Launch the application. It will load your Qt build.

Source code for the exact Qt version distributed with this build is available from
<https://download.qt.io/> and from The Qt Company under the terms of the LGPL.

If you need the corresponding source for the specific build shipped to you, contact
[SUPPORT EMAIL] and it will be provided at no more than the cost of distribution.

### Modules deliberately not used

The following Qt add-ons are **GPL-3.0-only** in the open-source edition and are **not**
linked by MakeYourTree Studio: **Qt Charts**, **Qt Data Visualization**, **Qt Virtual
Keyboard**. `tests/test_licensing.py` fails the build if any module imports them.

---

## Python

- **Copyright** © 2001–present Python Software Foundation. All rights reserved.
- **Licence:** PSF License Agreement (`PSF-2.0`), a permissive licence.
- Home: <https://www.python.org/> · Licence: <https://docs.python.org/3/license.html>

---

## NumPy

- **Copyright** © 2005–present NumPy Developers. All rights reserved.
- **Licence:** BSD 3-Clause (`BSD-3-Clause`).
- Home: <https://numpy.org/>

> Redistribution and use in source and binary forms, with or without modification, are
> permitted provided that the following conditions are met: redistributions of source code
> must retain the above copyright notice, this list of conditions and the following
> disclaimer; redistributions in binary form must reproduce them in the documentation
> and/or other materials provided with the distribution; neither the name of the copyright
> holder nor the names of its contributors may be used to endorse or promote products
> derived from this software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
> EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED. See the full text distributed with NumPy.

---

## MakeYourTree core

- **Copyright** © 2026 Manish Prakash Victor (trading as Inventufortuitum).
- **Licence:** MIT (`MIT`) — see [`LICENSES/MIT.txt`](LICENSES/MIT.txt).

The whole of MakeYourTree — the `makeyourtree` package (parsers, tree model, layout engine,
annotation model, scene graph, SVG renderer and CLI) and the `makeyourtree_studio` desktop
application alike — is open source under MIT. You may use, modify and redistribute it
under MIT terms.

---

## Colour palettes

- **viridis, magma, plasma, cividis** — created by Stéfan van der Walt, Nathaniel Smith,
  Eric Firing and Jamie Nuñez; released into the **public domain (CC0)**.
- **Okabe–Ito qualitative palette** — from Okabe & Ito, *Color Universal Design* (2008),
  published colour-vision research; freely usable.

Remaining ramps were constructed for this project and are original.

---

## Icons and fonts

[Record every icon set and font shipped in `src/makeyourtree_studio/resources/` here, with its
SPDX identifier, copyright holder and upstream URL, **before it is committed**.]

Permitted sources: MIT-licensed icon sets (Lucide, Tabler, Feather), Apache-2.0 Material
Symbols, and SIL OFL fonts. **SIL OFL note:** OFL fonts may be bundled and sold with an
application, but a Reserved Font Name may not be used for a modified version — do not
rename or subset-and-rename an OFL font without checking its RFN clause.

---

## Attribution note

MakeYourTree is released as open source by choice, not by obligation: no component listed
here would have required it. The MIT and BSD components require notice retention only.
LGPL-3.0 applies to Qt itself, and the conditions for distributing an application
alongside it are set out in [`LICENSE.md`](LICENSE.md) and satisfied by this
distribution.
