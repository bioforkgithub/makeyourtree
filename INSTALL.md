# Installing MakeYourTree

MakeYourTree runs on **Windows, macOS and Linux** from a single environment definition. The
commands below are the same on all three — the environment resolves the platform
differences, including the Qt system libraries that would otherwise have to be installed by
hand on Linux.

MakeYourTree is not on PyPI yet, so installation is from the source repository. There is no
`pip install makeyourtree`; ignore any package by that name from another author.

**Requirements:** `git`, a conda-family package manager (or Python 3.12+ for the pip
route), and about **1 GB of disk space**. Most of that is Qt: a complete environment
measures 751 MB, of which PySide6 is 641 MB and NumPy 34 MB. No network access is needed at
*runtime* — only to install.

> **What has actually been tested.** The pip route was executed end to end on **Windows 11
> with Python 3.12.10**, giving PySide6 6.11.2 / Qt 6.11.2 and NumPy 2.5.2, with all 2,220
> tests passing. The conda route and the macOS and Linux platforms have **not** been run by
> the author — conda is not installed on the development machine. The commands are standard
> and the conda-forge package names are the usual ones, but please open an issue if
> something does not work. Such a report will be believed rather than doubted.

---

## Install with conda or mamba

This is the recommended route, and it is identical on every operating system.

Substitute `mamba` or `micromamba` for `conda` throughout if you prefer — the arguments are
the same, and mamba resolves considerably faster.

### 1. Install a conda-family package manager

[Miniforge](https://github.com/conda-forge/miniforge) is the usual recommendation: it is
small and defaults to the conda-forge channel, which is where `pyside6` comes from.
Anaconda and Miniconda work too, but see the note in step 3.

### 2. Get the source

```bash
git clone https://github.com/bioforkgithub/makeyourtree.git
cd makeyourtree
```

### 3. Create the environment

```bash
conda env create -f environment.yml
conda activate makeyourtree
```

This installs Python 3.12, NumPy and PySide6 — and, on Linux, the Qt system libraries as
ordinary conda packages, so there is nothing to `apt install`.

> On **Anaconda or Miniconda**, the `defaults` channel takes priority and does not carry
> `pyside6`. If the solve fails, prefer conda-forge and retry:
> ```bash
> conda config --add channels conda-forge
> conda config --set channel_priority strict
> ```

### 4. Install MakeYourTree

```bash
pip install -e . --no-deps
```

**`--no-deps` is not optional bookkeeping.** Conda has already installed everything
MakeYourTree needs. A plain `pip install -e .` would resolve those same requirements again from
PyPI and install a *second* copy of Qt into an environment that already has one — 641 MB
wasted, and two Qt builds present where which one loads depends on import order.

### 5. Check it worked

```bash
makeyourtree --version
makeyourtree info examples/primates.nwk
```

### 6. Run it

```bash
makeyourtree-studio
```

### Everyday use

```bash
conda activate makeyourtree         # each new shell
conda deactivate                # when finished
conda env remove -n makeyourtree    # remove it entirely
```

To run the test suite or build a bundle, uncomment the development block at the end of
[`environment.yml`](environment.yml) and apply it:

```bash
conda env update -f environment.yml --prune
```

---

## Install with pip and venv

Use this if you would rather not install conda. It needs **Python 3.12 or newer** already
present, and on Linux it needs the Qt system libraries installed by hand — see
[Linux: Qt system libraries](#linux-qt-system-libraries) below.

```bash
git clone https://github.com/bioforkgithub/makeyourtree.git
cd makeyourtree
python -m venv .venv
```

Activate it. This single line is the only command in this document that differs by
platform:

| Platform | Command |
|---|---|
| Linux, macOS | `source .venv/bin/activate` |
| Windows, PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows, `cmd.exe` | `.venv\Scripts\activate.bat` |

Then install, check and run — note that here pip *does* resolve dependencies, so there is
no `--no-deps`:

```bash
pip install -e ".[studio]"
makeyourtree --version
makeyourtree info examples/primates.nwk
makeyourtree-studio
```

---

## Installing the library only, without the desktop application

The `makeyourtree` library and its command-line interface import **no GUI toolkit**, so they
install without Qt. This is the right choice for a server, a container, a CI job or an
analysis pipeline — it avoids the 641 MB PySide6 brings, and on Linux it needs none of the
system libraries below.

With pip, drop the `[studio]` extra; with conda, delete the `pyside6` line from
`environment.yml` before creating the environment:

```bash
pip install -e "."
```

You then have the `makeyourtree` command and the Python API, but not `makeyourtree-studio`. NumPy
is the only dependency.

```bash
makeyourtree info tree.nwk
makeyourtree convert tree.nex tree.xml
makeyourtree render tree.nwk figure.svg --mode circular --track hosts.mytrack
makeyourtree render tree.nwk figure.png --dpi 600 --width 180mm
makeyourtree reroot tree.nwk rooted.nwk --midpoint
makeyourtree guide                       # answer questions, get a plan
makeyourtree plan figure.myplan          # resume that plan later
```

`render` writes SVG, PDF or PNG; `--dpi` and physical sizes such as `--width
180mm` apply to it. PNG and PDF need the `studio` extra, which supplies the
rasteriser.

---

## Running the tests

Optional, but the fastest way to confirm a working installation:

```bash
pip install -e ".[studio,dev]"     # or the conda development block
python -m pytest
```

Expect **2220 passed** in roughly 35 seconds. The suite runs headlessly and needs no
display.

---

## Building a standalone bundle

To produce a self-contained directory that runs without Python installed:

```bash
pip install pyinstaller
python -m makeyourtree_studio.packaging.build
```

The result is `dist/MakeYourTreeStudio/`. The build driver verifies the bundle against thirteen
checks — licence texts present, Qt shipped as separate replaceable shared libraries, no
GPL-3.0-only Qt add-on pulled in — and refuses to certify one that fails.

Two things to know. PyInstaller **cannot cross-build**: each platform's bundle must be
produced on that platform. And this has so far only been built and launched on **Windows**;
macOS and Linux bundles are unproven, not broken — nobody has made one yet.

If you distribute a bundle, the licence texts must travel with it. That is an LGPL-3.0
obligation binding whoever conveys the binary, and it applies to you as much as to us. See
[`LICENSE.md`](LICENSE.md).

---

## Platform notes

Two things genuinely differ by operating system. Both affect the **pip route only** — the
conda environment handles the first, and largely avoids the second.

### Linux: Qt system libraries

The PySide6 *wheel* bundles Qt itself, but Qt still loads a few system libraries — above
all its `xcb` platform plugin. Without them the application exits with
`qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`.

```bash
# Debian / Ubuntu
sudo apt install libgl1 libegl1 libglib2.0-0 libfontconfig1 libdbus-1-3 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
  libxcb-xinerama0

# Fedora
sudo dnf install mesa-libGL mesa-libEGL fontconfig dbus-libs \
  libxkbcommon-x11 xcb-util-cursor xcb-util-image xcb-util-keysyms \
  xcb-util-renderutil xcb-util-wm

# Arch
sudo pacman -S libgl libxkbcommon-x11 xcb-util-cursor xcb-util-image \
  xcb-util-keysyms xcb-util-renderutil xcb-util-wm fontconfig
```

`libxcb-cursor0` is required by Qt 6.5 and later specifically, and is the one most often
missing on otherwise complete systems. On Debian and Ubuntu, `python3.12-venv` is also a
separate package — without it, `python -m venv` fails complaining about `ensurepip`.

### Windows: clone to a short path

PySide6 ships files whose names exceed Windows' 260-character `MAX_PATH` limit. Installing
into a `.venv` inside a deeply nested directory fails with
`OSError: [WinError 206] The filename or extension is too long`, and it rolls back
*partially* — which is confusing, because the test suite still passes (its `conftest.py`
adds `src/` to `sys.path`) while `makeyourtree` itself is missing.

Clone somewhere short such as `C:\dev\makeyourtree`, or enable long paths first:

```powershell
git config --system core.longpaths true
```

together with the `LongPathsEnabled` registry setting. The conda route mostly sidesteps
this, because the environment lives under the conda installation rather than inside the
clone.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Could not load the Qt platform plugin "xcb"` (Linux) | Missing Qt system libraries — see [above](#linux-qt-system-libraries). To see exactly which, run `QT_DEBUG_PLUGINS=1 makeyourtree-studio`. |
| `OSError: [WinError 206] ... too long` (Windows) | Path too deep for `MAX_PATH`. Remove `.venv`, re-clone to a short path, install again. |
| `ModuleNotFoundError: No module named 'makeyourtree'` but `pytest` passes (Windows) | The same `MAX_PATH` failure, partially rolled back. `pytest` succeeds because `conftest.py` adds `src/` to `sys.path`, masking the missing install. |
| `cannot be loaded because running scripts is disabled` (Windows) | PowerShell execution policy. Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| `ensurepip is not available` (Linux) | Install `python3.12-venv` on Debian/Ubuntu. |
| Environment fails to solve, `pyside6` not found | You are on the `defaults` channel. Prefer conda-forge — see step 3. |
| Qt appears twice, or the app is enormous | A `pip install -e .` without `--no-deps` inside a conda environment. Remove the environment and redo step 4. |
| `makeyourtree-studio` opens nothing over SSH | No display. Use X11 forwarding (`ssh -X`), or use the CLI, which needs no display. |
| `pip install` picks the wrong Python | Call the interpreter directly: `python3.12 -m pip install -e ".[studio]"`. Confirm with `python -c "import sys; print(sys.executable)"`. |
| Text renders as boxes in exported figures | Usually a missing font rather than a MakeYourTree bug. Install a standard font family and re-export. |

If none of these fit, open an issue with your platform, your Python version, and the full
error output.
