# Packaging MakeYourTree Studio

<!-- SPDX-License-Identifier: MIT -->

This directory produces the shippable desktop distribution.

| File | Purpose |
|---|---|
| `makeyourtree.spec` | The PyInstaller spec. **Licence-critical** — read its header before changing a line. |
| `build.py` | Build driver: verifies the spec, runs PyInstaller, then verifies the produced bundle and fails loudly if any licence obligation is unmet. |

Never invoke `pyinstaller` directly for a release. `build.py` is the release path,
because the verification it performs afterwards is the only thing standing between a
packaging mistake and shipping Qt without a valid licence.

---

## Building

Prerequisites: Python 3.12, the project installed with its `studio` extra, and
PyInstaller in the same interpreter.

```
python -m pip install -e ".[studio]"
python -m pip install pyinstaller
```

Then, from the repository root:

```
python -m makeyourtree_studio.packaging.build
```

The bundle is written to `dist/MakeYourTreeStudio/` and scratch files to `build/`.

Useful flags:

| Flag | Effect |
|---|---|
| `--dist DIR` | Write the bundle somewhere else. |
| `--work DIR` | Move PyInstaller's scratch directory. |
| `--no-clean` | Reuse PyInstaller's cache. Faster; not for releases. |
| `--verify-only` | Skip the build and audit an existing bundle. Use this on a downloaded release artefact. |

`build.py` exits non-zero and names every failed check. There is no warn-and-continue
mode, deliberately.

### Windows

Build on the oldest Windows version you intend to support; the PyInstaller bootloader
and the Visual C++ runtime are not forward-portable. The result is
`dist\MakeYourTreeStudio\MakeYourTreeStudio.exe` with `Qt6*.dll` beside it (inside `_internal\`
on PyInstaller 6).

### macOS

Build on macOS; cross-building is not supported by PyInstaller. The spec adds a
`BUNDLE` step on Darwin, producing `dist/MakeYourTreeStudio.app` alongside the collected
directory. The `.app` is itself a directory tree — the Qt frameworks sit in
`Contents/Frameworks` as separate, replaceable files, so the LGPL guarantee below still
holds.

Build separately for `arm64` and `x86_64` on matching hardware, or set
`target_arch='universal2'` in the spec if a universal PySide6 wheel is available.

### Linux

Build inside the oldest glibc you support (a `manylinux`-style container is the usual
approach); glibc symbol versions are backward- but not forward-compatible. The result is
`dist/MakeYourTreeStudio/MakeYourTreeStudio` with `libQt6*.so.6` beside it.

Do not run `strip` over the output. See below.

---

## Why `--onedir`, never `--onefile`

Qt is used under **LGPL-3.0**. LGPL-3.0 §4 permits distributing a proprietary
application that links an LGPL library, but only if the listed conditions are met. The
one that dictates our packaging is **§4(d)(1)**: we must use a shared-library mechanism
such that the application

> will operate properly with a modified version of the Library that is
> interface-compatible with the Linked Version.

A `--onedir` build satisfies this. Qt ships as separate, dynamically loaded
`.dll` / `.so` / `.dylib` files that the user can overwrite with their own build.

A `--onefile` build does not. It packs those libraries inside the executable and
extracts them to a temporary directory at launch, so there is nothing the user can
replace. Switching to `--onefile` would leave us distributing Qt with **no valid
licence** — copyright infringement, not a packaging preference.

If single-file distribution ever becomes a hard requirement, the only lawful routes are
§4(d)(0) (ship relinkable object code plus the complete corresponding Qt source, which
is painful to maintain) or a **commercial Qt licence** from The Qt Company, which
removes the LGPL obligations entirely.

`build.py` refuses to certify a bundle that has stopped being onedir, and
`tests/studio_packaging/` fails the test suite if the spec is edited toward `--onefile`.

## The LGPL-3.0 §4 conditions this bundle satisfies

| §4 | Requirement | How the bundle meets it |
|---|---|---|
| (a) | Prominent notice that the Library is used and covered by the LGPL | `THIRD-PARTY-NOTICES.md` is bundled and shown by **Help ▸ Third-Party Licences** |
| (b) | Ship copies of the GPL and LGPL texts | `LICENSES/GPL-3.0.txt` and `LICENSES/LGPL-3.0.txt` are bundled verbatim |
| (c) | Reproduce the Library's copyright notice at runtime | Shown in **Help ▸ About** and in the licences dialog |
| (d)(1) | Shared-library mechanism that works with a replaced, interface-compatible Library | `--onedir`: Qt ships as separate shared libraries; see the replacement instructions below |
| (e) | Installation Information where required | The relinking instructions in `THIRD-PARTY-NOTICES.md` and below |

Two further rules the spec enforces:

- **`strip=False` and `upx=False` everywhere.** Stripping or UPX-packing a Qt shared
  library produces a *modified* Qt, and modifications to an LGPL library must themselves
  be published under the LGPL. Qt ships byte-for-byte as the wheel provided it.
- **`excludes` lists Qt Charts, Qt Data Visualization and Qt Virtual Keyboard.** Those
  add-ons are GPL-3.0-only in the open-source Qt edition; linking one would relicense
  the entire product under GPL-3.0 and void the commercial EULA. The spec also filters
  them out of the collected binaries, and `build.py` scans the finished bundle for them.

## How a user replaces Qt

This must keep working. It is the condition our right to ship Qt rests on.

1. Note the exact Qt version in **Help ▸ About**.
2. Obtain or build a Qt 6 release binary-compatible with it. Qt guarantees binary
   compatibility across patch releases within a minor series, so any 6.11.x build works
   against a 6.11.y application.
3. Replace the files in the installation directory, keeping names and layout:
   - Windows — `_internal\Qt6*.dll` and `_internal\PySide6\plugins\`
   - Linux — `_internal/libQt6*.so.6` and `_internal/PySide6/Qt/plugins/`
   - macOS — the `Qt*.framework` bundles under `Contents/Frameworks`
4. Launch. The application loads the replaced libraries.

Corresponding source for the exact Qt build shipped is available from
<https://download.qt.io/> and, on request, from us at no more than the cost of
distribution.

---

## Code signing

Unsigned builds trip SmartScreen on Windows and Gatekeeper on macOS. Signing is a
release-engineering task, not a packaging one, and is not yet wired into `build.py`.

**[TODO] Windows Authenticode.** Requires an OV or EV code-signing certificate; EV
certificates are held on a hardware token or in an HSM, which rules out unattended CI
signing without a cloud signing service. Sign the launcher *and* every shipped `.dll`,
after `build.py` has verified the bundle and before packaging the installer — signing
mutates files and would invalidate any hash taken earlier.

```
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f makeyourtree-codesign.pfx /p %MAKEYOURTREE_CERT_PASSWORD% ^
  dist\MakeYourTreeStudio\MakeYourTreeStudio.exe
signtool verify /pa /v dist\MakeYourTreeStudio\MakeYourTreeStudio.exe
```

Note: signing Qt's DLLs adds our signature to an LGPL library. That is a signature, not
a modification of the code, and does not create a derivative work — but do not take the
opportunity to patch anything while you are in there.

**[TODO] macOS signing and notarisation.** Requires a paid Apple Developer account and a
"Developer ID Application" certificate. Sign inside-out (nested frameworks first), with
the hardened runtime, then notarise and staple.

```
codesign --force --deep --options runtime --timestamp \
  --sign "Developer ID Application: <TEAM NAME> (<TEAM ID>)" \
  dist/MakeYourTreeStudio.app
codesign --verify --deep --strict --verbose=2 dist/MakeYourTreeStudio.app

ditto -c -k --keepParent dist/MakeYourTreeStudio.app MakeYourTreeStudio.zip
xcrun notarytool submit MakeYourTreeStudio.zip \
  --apple-id "<APPLE ID>" --team-id "<TEAM ID>" \
  --password "<APP SPECIFIC PASSWORD>" --wait
xcrun stapler staple dist/MakeYourTreeStudio.app
spctl --assess --type execute --verbose dist/MakeYourTreeStudio.app
```

`--deep` is deprecated by Apple; a release script should walk `Contents/Frameworks` and
sign each framework explicitly instead.

**[TODO] Linux.** No signing requirement. If an AppImage or Flatpak is produced, sign
the artefact with a detached GPG signature and publish the public key.

**[TODO] Installers.** Windows: MSI or an Inno Setup / WiX installer, signed with the
same certificate. macOS: a signed and notarised `.dmg`. Both must preserve the onedir
layout — an installer that repacks Qt into a single archive without extracting it to a
replaceable location reintroduces the `--onefile` problem.
