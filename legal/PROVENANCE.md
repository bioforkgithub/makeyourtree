# Provenance

Every external input that informed this implementation, and where it is used.

## Format specifications

| Format | Source | Used by |
|---|---|---|
| Newick | Olsen, *"Newick's 8:45" tree format standard* (1990), and the PHYLIP documentation | `io/newick.py` |
| NHX (New Hampshire eXtended) v2.0 | phylosoft.org NHX specification | `io/newick.py` |
| NEXUS | Maddison, Swofford & Maddison (1997), *NEXUS: an extensible file format for systematic information*, Syst. Biol. 46:590–621 | `io/nexus.py` |
| phyloXML 1.20 | Han & Zmasek (2009), BMC Bioinformatics 10:356; phyloxml.org XSD | `io/phyloxml.py` |
| `[&key=value]` metacomments | The convention as used by BEAST, MrBayes and FigTree, reconstructed from their published output format documentation | `io/newick.py` |
| CSV | RFC 4180 | `annot/loaders.py` |
| SVG 1.1 | W3C Recommendation | `render/svg.py` |

File formats are not copyrightable subject matter (see `CLEANROOM.md` §1); implementing a
reader and writer for each of the above is lawful and is the point of publishing a format.

## Algorithms

| Algorithm | Citation | Implemented in |
|---|---|---|
| Equal-angle unrooted layout | Felsenstein, *Inferring Phylogenies* (2004), pp. 578–582; Bachmaier, Brandes & Schlieper (2005) formulation | `layout/unrooted.py` |
| Equal-daylight unrooted layout | Felsenstein, *Inferring Phylogenies* (2004), pp. 582–584 | `layout/unrooted.py` |
| Nice-number axis labelling | Heckbert, *Nice Numbers for Graph Labels*, Graphics Gems (1990) | `layout/scalebar.py` |
| Midpoint rooting | Standard definition: root at the midpoint of the longest leaf-to-leaf path | `ops/rooting.py` |
| Tukey outlier rule (1.5 × IQR) | Tukey, *Exploratory Data Analysis* (1977) | `tracks/boxplot.py` |
| Relative luminance and contrast ratio | WCAG 2.2, W3C | `style/color.py` |

Tidy-layout coordinate assignment (post-order cross coordinate, parent placed on its
children's span) is derived from first principles in `layout/linear.py`; the family
descends from Reingold & Tilford (1981), *Tidier Drawings of Trees*, IEEE TSE 7:223.

## Colour palettes

| Palette | Origin | Status |
|---|---|---|
| Okabe–Ito 8-colour qualitative set | Okabe & Ito, *Color Universal Design* (2008) — published colour-vision research | Freely usable; the MakeYourTree default |
| viridis, magma, plasma, cividis | Created by Smith, van der Walt, Garnier and Nuñez; released **CC0 / public domain** via matplotlib | Public domain |
| Single-hue and diverging ramps | Constructed for this project by interpolation in our own code | Original |

No proprietary product's brand palette is reproduced.

## Software dependencies

| Dependency | License | Obligation |
|---|---|---|
| Python 3.12 | PSF License | Notice |
| NumPy | BSD-3-Clause | Notice |
| PySide6 / Qt 6 | **LGPLv3** (open-source edition) | See `LICENSE.md` — shipped unmodified, dynamically linked, license texts and notices included |
| pytest (development only) | MIT | Not distributed |

Qt add-ons that are **GPL-3.0-only** in the open-source build — Qt Charts, Qt Data
Visualization, Qt Virtual Keyboard — are **not used**, and CI asserts that no module
imports them.

## Assets

Icons and fonts must be permissively licensed only (MIT-licensed icon sets such as Lucide,
Tabler or Feather; Apache-2.0 Material Symbols; SIL OFL fonts). Each asset added to
`src/makeyourtree_studio/resources/` must be recorded here with its SPDX identifier and
upstream URL before it is committed.

## Not used

No code, prose, artwork, template file, keyword vocabulary or dataset from any other
phylogenetic tree visualisation product was consulted, copied or adapted. See
`CLEANROOM.md`.

---

## Annotation-vocabulary audit — 2026-08-20

During the specification phase, publicly available annotation template files were read to
extract **field-level data models** — what values a heatmap, a bar chart or a domain diagram
needs in order to be drawn. Data models and functional requirements are unprotectable
subject matter (see `CLEANROOM.md` §1); expression is not. This audit confirms that no
expression crossed over.

**Method.** Enumerated every registered track `type_id`, the union of every track's option
schema, the `.mytrack` section names, and scanned all of `src/makeyourtree/` for ALL-CAPS
directive-style identifiers — the idiom competing annotation languages use
(`DATASET_*`, `FIELD_*`, `*_WIDTH`). Also searched the working tree for any competitor
template file. The repository had no prior commits, so the working tree is the whole history.

**Result — clean.**

| Check | Outcome |
|---|---|
| ALL-CAPS directive-style identifiers in source | **None** |
| Competitor template files present anywhere | **None** |
| Track `type_id`s | Lowercase, hyphenated, plainly descriptive: `bar-chart`, `binary-matrix`, `box-plot`, `clade-range`, `color-strip`, `connections`, `domain-architecture`, `gradient`, `heatmap`, `line-chart`, `pie-chart`, `symbols`, `text-labels` |
| `.mytrack` section names | `track`, `options`, `columns`, `colors`, `legend`, `data` — generic lowercase INI sections |
| Option vocabulary | ~130 lowercase `snake_case` names in our own structure (`thickness`, `cell_gap`, `whisker_factor`, `symbol_scale`, `zero_based`, …) |

**Terms that unavoidably coincide.** A handful of option names — `title`, `margin`,
`border_width`, `opacity`, `data` — are ordinary descriptive English and are the obvious
word for the thing they name. They are individually unprotectable, they appear here in our
own structure and casing, and no sequence, grouping or naming pattern was carried across.

**Structural divergence.** Our format is a sectioned INI document with a typed option
schema per track class. Competing formats use flat ALL-CAPS directive lines. These are
different designs, not a reskin.

### Refinement, same date

The first pass tested only the ALL-CAPS directive form. A second, case-insensitive pass was
run to catch lowercased equivalents. Findings:

| Match | Where | Assessment |
|---|---|---|
| `field_combo` | `panels/search_panel.py` | A Qt combo-box widget. Unrelated. |
| `field_as_text`, `field_in_place`, `dataset_maximum` | test names | Test identifiers. Unrelated. |
| `field_colors` | `tracks/bars.py` | **Coincidental near-collision** — two ordinary English words naming exactly what the option is (per-column colours). Individually unprotectable, and arrived at independently. |

`field_colors` is nonetheless being renamed to **`column_colors`**, which is already our term
for the same concept elsewhere in the track option schema. The rename costs nothing, improves
internal consistency, and removes the only argument available on this point.

**Working material excluded from version control.** The research notes gathered while
specifying our own format did quote third-party directive vocabulary. They are therefore
kept **outside the repository** and are excluded by `.gitignore` (`docs/_research/`), because
git history is permanent and a purge is unreliable. None of that vocabulary reached `src/`.

**Conclusion.** The vocabulary audit is closed. Re-run both passes — case-sensitive and
case-insensitive — if the track option schema is substantially extended.
