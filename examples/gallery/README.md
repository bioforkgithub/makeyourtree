# Gallery

Every figure here is produced by `python tools/make_gallery.py` from the
trees in `examples/`. Each exists as **`.svg`** and **`.pdf`** (vector) and
**`.png`** (raster). The PNGs are shown below; click any heading link to
open the vector version.

All data is synthetic — seeded random values and invented taxon names.
Nothing is copied from or derived from any other phylogenetics package;
see [`../../legal/FIXTURES.md`](../../legal/FIXTURES.md).

## Layouts

### [layout-rectangular-phylogram](layout-rectangular-phylogram.svg)

Rectangular phylogram: branch length along x.

![Rectangular phylogram: branch length along x.](layout-rectangular-phylogram.png)

### [layout-rectangular-cladogram](layout-rectangular-cladogram.svg)

Rectangular cladogram: depth along x, tips aligned.

![Rectangular cladogram: depth along x, tips aligned.](layout-rectangular-cladogram.png)

### [layout-slanted](layout-slanted.svg)

Slanted (triangular) layout.

![Slanted (triangular) layout.](layout-slanted.png)

### [layout-circular](layout-circular.svg)

Circular fan, 350 degree arc.

![Circular fan, 350 degree arc.](layout-circular.png)

### [layout-circular-full](layout-circular-full.svg)

Circular fan closed to a full 360 degree circle.

![Circular fan closed to a full 360 degree circle.](layout-circular-full.png)

### [layout-circular-cladogram](layout-circular-cladogram.svg)

Circular cladogram: every tip on the outer radius.

![Circular cladogram: every tip on the outer radius.](layout-circular-cladogram.png)

### [layout-radial](layout-radial.svg)

Radial: angle from tip order, radius from branch length.

![Radial: angle from tip order, radius from branch length.](layout-radial.png)

### [layout-unrooted-equal-angle](layout-unrooted-equal-angle.svg)

Unrooted, Felsenstein equal-angle.

![Unrooted, Felsenstein equal-angle.](layout-unrooted-equal-angle.png)

### [layout-unrooted-equal-daylight](layout-unrooted-equal-daylight.svg)

Unrooted, equal-daylight: subtrees spread to even the gaps.

![Unrooted, equal-daylight: subtrees spread to even the gaps.](layout-unrooted-equal-daylight.png)

## Annotation tracks

### [track-clade-range](track-clade-range.svg)

Clade range: a shaded, labelled band behind a whole subtree.

![Clade range: a shaded, labelled band behind a whole subtree.](track-clade-range.png)

### [track-color-strip](track-color-strip.svg)

Colour strip: one categorical value per tip.

![Colour strip: one categorical value per tip.](track-color-strip.png)

### [track-binary-matrix](track-binary-matrix.svg)

Binary matrix: presence, absence and unknown per gene.

![Binary matrix: presence, absence and unknown per gene.](track-binary-matrix.png)

### [track-gradient](track-gradient.svg)

Gradient: a continuous value as a single colour ramp.

![Gradient: a continuous value as a single colour ramp.](track-gradient.png)

### [track-heatmap](track-heatmap.svg)

Heatmap: a matrix of continuous values, diverging palette.

![Heatmap: a matrix of continuous values, diverging palette.](track-heatmap.png)

### [track-bar-chart](track-bar-chart.svg)

Bar chart with a value axis.

![Bar chart with a value axis.](track-bar-chart.png)

### [track-bar-stacked](track-bar-stacked.svg)

Stacked bar chart: composition per tip.

![Stacked bar chart: composition per tip.](track-bar-stacked.png)

### [track-box-plot](track-box-plot.svg)

Box plot: distribution per tip, computed from raw replicates.

![Box plot: distribution per tip, computed from raw replicates.](track-box-plot.png)

### [track-pie-chart](track-pie-chart.svg)

Pie charts: part-to-whole composition at each tip.

![Pie charts: part-to-whole composition at each tip.](track-pie-chart.png)

### [track-domain-architecture](track-domain-architecture.svg)

Domain architecture: features drawn to scale along each protein.

![Domain architecture: features drawn to scale along each protein.](track-domain-architecture.png)

### [track-text-labels](track-text-labels.svg)

External text labels, independent of the tip names.

![External text labels, independent of the tip names.](track-text-labels.png)

### [track-symbols](track-symbols.svg)

Symbols sized by value: area encodes magnitude, not radius.

![Symbols sized by value: area encodes magnitude, not radius.](track-symbols.png)

### [track-line-chart](track-line-chart.svg)

Line chart: a small multiple series per tip.

![Line chart: a small multiple series per tip.](track-line-chart.png)

### [track-connections](track-connections.svg)

Connections: curved links between arbitrary nodes, drawn under the branches.

![Connections: curved links between arbitrary nodes, drawn under the branches.](track-connections.png)

## Combined figures

### [combined-rectangular](combined-rectangular.svg)

Three stacked tracks in a rectangular layout.

![Three stacked tracks in a rectangular layout.](combined-rectangular.png)

### [combined-circular](combined-circular.svg)

The identical tracks in a circular layout. No track code differs between this figure and the previous one.

![The identical tracks in a circular layout. No track code differs between this figure and the previous one.](combined-circular.png)

## Features

### [feature-align-tips](feature-align-tips.svg)

Tips aligned to a common edge with guide lines.

![Tips aligned to a common edge with guide lines.](feature-align-tips.png)

### [feature-collapsed-clade](feature-collapsed-clade.svg)

A collapsed clade, drawn as a triangle sized by the subtree.

![A collapsed clade, drawn as a triangle sized by the subtree.](feature-collapsed-clade.png)

### [feature-dark-theme](feature-dark-theme.svg)

The dark theme. The scene carries its own background, so an export matches the screen.

![The dark theme. The scene carries its own background, so an export matches the screen.](feature-dark-theme.png)

### [feature-midpoint-rooted](feature-midpoint-rooted.svg)

The same tree after midpoint rooting. Patristic distances are preserved exactly.

![The same tree after midpoint rooting. Patristic distances are preserved exactly.](feature-midpoint-rooted.png)

### [feature-large-tree](feature-large-tree.svg)

A 24-tip tree with a full annotation stack, circular.

![A 24-tip tree with a full annotation stack, circular.](feature-large-tree.png)

## Everything at once

### [showcase-everything-rectangular](showcase-everything-rectangular.svg)

Six track types on one tree at once: clade ranges, a colour strip, a binary matrix, a heatmap, a bar chart and sized symbols, with aligned tips and guide lines.

![Six track types on one tree at once: clade ranges, a colour strip, a binary matrix, a heatmap, a bar chart and sized symbols, with aligned tips and guide lines.](showcase-everything-rectangular.png)

### [showcase-everything-circular](showcase-everything-circular.svg)

The same six tracks wrapped into rings. Nothing in any track changed; only the layout mode did.

![The same six tracks wrapped into rings. Nothing in any track changed; only the layout mode did.](showcase-everything-circular.png)

## The corpus

### [corpus-shape-balanced](corpus-shape-balanced.svg)

Shape reference — Perfectly bifurcating. The baseline for layout geometry.

![Shape reference — Perfectly bifurcating. The baseline for layout geometry.](corpus-shape-balanced.png)

### [corpus-shape-ladder](corpus-shape-ladder.svg)

Shape reference — A caterpillar. Root-to-tip depth equals the tip count, which is what breaks a recursive traversal.

![Shape reference — A caterpillar. Root-to-tip depth equals the tip count, which is what breaks a recursive traversal.](corpus-shape-ladder.png)

### [corpus-shape-star](corpus-shape-star.svg)

Shape reference — One polytomy of degree 24: no internal resolution at all.

![Shape reference — One polytomy of degree 24: no internal resolution at all.](corpus-shape-star.png)

### [corpus-shape-unbalanced](corpus-shape-unbalanced.svg)

Shape reference — Random joining with support values, the shape most analyses produce.

![Shape reference — Random joining with support values, the shape most analyses produce.](corpus-shape-unbalanced.png)

### [corpus-shape-ultrametric](corpus-shape-ultrametric.svg)

Shape reference — Every tip equidistant from the root, as a dated analysis gives.

![Shape reference — Every tip equidistant from the root, as a dated analysis gives.](corpus-shape-ultrametric.png)

### [corpus-shape-polytomous](corpus-shape-polytomous.svg)

Shape reference — Mostly resolved with genuine polytomies, as a consensus tree is.

![Shape reference — Mostly resolved with genuine polytomies, as a consensus tree is.](corpus-shape-polytomous.png)

### [corpus-scale-0008](corpus-scale-0008.svg)

Scale reference — 8 tips. Almost every rendering decision changes with size; this is the series for checking that.

![Scale reference — 8 tips. Almost every rendering decision changes with size; this is the series for checking that.](corpus-scale-0008.png)

### [corpus-scale-0060](corpus-scale-0060.svg)

Scale reference — 60 tips. Almost every rendering decision changes with size; this is the series for checking that.

![Scale reference — 60 tips. Almost every rendering decision changes with size; this is the series for checking that.](corpus-scale-0060.png)

### [corpus-scale-0250](corpus-scale-0250.svg)

Scale reference — 250 tips. Almost every rendering decision changes with size; this is the series for checking that.

![Scale reference — 250 tips. Almost every rendering decision changes with size; this is the series for checking that.](corpus-scale-0250.png)

### [corpus-study-outbreak](corpus-study-outbreak.svg)

Outbreak / dated phylogeny — A time-scaled tree with lineage assignments and sampling dates: the commonest epidemiological figure.

![Outbreak / dated phylogeny — A time-scaled tree with lineage assignments and sampling dates: the commonest epidemiological figure.](corpus-study-outbreak.png)

### [corpus-study-pangenome](corpus-study-pangenome.svg)

Bacterial pangenome — Gene presence and absence across strains, with a genome-size bar. Unknown is a third state and is drawn as a gap.

![Bacterial pangenome — Gene presence and absence across strains, with a genome-size bar. Unknown is a third state and is drawn as a gap.](corpus-study-pangenome.png)

### [corpus-study-microbiome](corpus-study-microbiome.svg)

Microbiome survey — Relative abundance across body sites, as a heatmap, with the composition of each taxon beside it.

![Microbiome survey — Relative abundance across body sites, as a heatmap, with the composition of each taxon beside it.](corpus-study-microbiome.png)

### [corpus-study-gene-family](corpus-study-gene-family.svg)

Gene family — A protein family with its domain architecture drawn to scale along each sequence.

![Gene family — A protein family with its domain architecture drawn to scale along each sequence.](corpus-study-gene-family.png)

### [corpus-study-morphology](corpus-study-morphology.svg)

Morphological cladogram — No branch lengths at all, and real polytomies. Must be drawn as a cladogram; a phylogram would imply distances that do not exist.

![Morphological cladogram — No branch lengths at all, and real polytomies. Must be drawn as a cladogram; a phylogram would imply distances that do not exist.](corpus-study-morphology.png)

### [corpus-study-biogeography](corpus-study-biogeography.svg)

Biogeography — Regions per tip plus dispersal events drawn as curved links between arbitrary taxa.

![Biogeography — Regions per tip plus dispersal events drawn as curved links between arbitrary taxa.](corpus-study-biogeography.png)

### [corpus-format-nexus](corpus-format-nexus.svg)

Format reference — The same tree written as nexus, so every reader has something to open.

![Format reference — The same tree written as nexus, so every reader has something to open.](corpus-format-nexus.png)

### [corpus-format-phyloxml](corpus-format-phyloxml.svg)

Format reference — The same tree written as phyloxml, so every reader has something to open.

![Format reference — The same tree written as phyloxml, so every reader has something to open.](corpus-format-phyloxml.png)
