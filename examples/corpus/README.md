# Tree corpus

Trees spanning the range people actually draw, in three dimensions:
**shape**, **scale** and **study type**. Regenerate with
`python tools/make_corpus.py`.

Everything here is **generated from a seed**, and every taxon name is
invented. Nothing is downloaded, because a published phylogeny is
someone's copyrighted work and a collection of them attracts the EU
database right on top of that -- see
`tools/make_corpus.py` from recorded seeds. Generating them
also means every one is reproducible exactly, years later, from the
seed recorded below.

| Tree | Shape | Tips | Format | Study type | Seed | Tracks |
|---|---|---:|---|---|---:|---:|
| `shape-balanced` | balanced | 32 | newick | Shape reference | 1 | 0 |
| `shape-ladder` | ladder | 40 | newick | Shape reference | 2 | 0 |
| `shape-star` | star | 24 | newick | Shape reference | 3 | 0 |
| `shape-unbalanced` | unbalanced | 40 | newick | Shape reference | 4 | 0 |
| `shape-ultrametric` | ultrametric | 30 | newick | Shape reference | 5 | 0 |
| `shape-polytomous` | polytomous | 36 | newick | Shape reference | 6 | 0 |
| `scale-0008` | unbalanced | 8 | newick | Scale reference | 10 | 0 |
| `scale-0060` | unbalanced | 60 | newick | Scale reference | 11 | 0 |
| `scale-0250` | unbalanced | 250 | newick | Scale reference | 12 | 0 |
| `scale-1000` | unbalanced | 1000 | newick | Scale reference | 13 | 0 |
| `scale-5000` | unbalanced | 5000 | newick | Scale reference | 14 | 0 |
| `study-outbreak` | ultrametric | 48 | newick | Outbreak / dated phylogeny | 100 | 2 |
| `study-pangenome` | unbalanced | 36 | newick | Bacterial pangenome | 101 | 2 |
| `study-microbiome` | unbalanced | 45 | newick | Microbiome survey | 102 | 2 |
| `study-gene-family` | unbalanced | 28 | newick | Gene family | 103 | 1 |
| `study-morphology` | polytomous | 22 | newick | Morphological cladogram | 104 | 1 |
| `study-biogeography` | unbalanced | 34 | newick | Biogeography | 105 | 2 |
| `format-nexus` | unbalanced | 18 | nexus | Format reference | 200 | 0 |
| `format-phyloxml` | unbalanced | 18 | phyloxml | Format reference | 200 | 0 |

## Notes

- **`shape-balanced`** — Perfectly bifurcating. The baseline for layout geometry.
- **`shape-ladder`** — A caterpillar. Root-to-tip depth equals the tip count, which is what breaks a recursive traversal.
- **`shape-star`** — One polytomy of degree 24: no internal resolution at all.
- **`shape-unbalanced`** — Random joining with support values, the shape most analyses produce.
- **`shape-ultrametric`** — Every tip equidistant from the root, as a dated analysis gives.
- **`shape-polytomous`** — Mostly resolved with genuine polytomies, as a consensus tree is.
- **`scale-0008`** — 8 tips. Almost every rendering decision changes with size; this is the series for checking that.
- **`scale-0060`** — 60 tips. Almost every rendering decision changes with size; this is the series for checking that.
- **`scale-0250`** — 250 tips. Almost every rendering decision changes with size; this is the series for checking that.
- **`scale-1000`** — 1000 tips. Label rendering has to be turned off around here, and a circular layout starts to pay off.
- **`scale-5000`** — 5000 tips. Label rendering has to be turned off around here, and a circular layout starts to pay off.
- **`study-outbreak`** — A time-scaled tree with lineage assignments and sampling dates: the commonest epidemiological figure.
- **`study-pangenome`** — Gene presence and absence across strains, with a genome-size bar. Unknown is a third state and is drawn as a gap.
- **`study-microbiome`** — Relative abundance across body sites, as a heatmap, with the composition of each taxon beside it.
- **`study-gene-family`** — A protein family with its domain architecture drawn to scale along each sequence.
- **`study-morphology`** — No branch lengths at all, and real polytomies. Must be drawn as a cladogram; a phylogram would imply distances that do not exist.
- **`study-biogeography`** — Regions per tip plus dispersal events drawn as curved links between arbitrary taxa.
- **`format-nexus`** — The same tree written as nexus, so every reader has something to open.
- **`format-phyloxml`** — The same tree written as phyloxml, so every reader has something to open.
