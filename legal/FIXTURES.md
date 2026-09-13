# Test fixture provenance

Every fixture used by the test suite must appear here with its origin and licence. This
matters commercially: shipping or distributing someone else's curated dataset can infringe
copyright and, in the EU, the *sui generis* database right (Directive 96/9/EC, 15-year
term, protecting substantial investment in obtaining or verifying the contents).

## Rule

A fixture is acceptable if and only if it is one of:

1. **Generated programmatically** by our own code (`tests/factories.py` or an equivalent
   generator in the owning test package). This is the default and covers almost everything.
2. **Hand-authored** by us for this repository — small trees written by hand to exercise a
   specific grammar edge case.
3. **Taken from an openly licensed source**, with the source, licence and retrieval date
   recorded in the table below.

**Never acceptable:** example trees, demo datasets or template files downloaded from any
phylogenetic tree-visualisation product's website or distribution.

**Nor from the literature.** It is tempting to bundle a folder of published trees to show
breadth. Do not. A published phylogeny is the authors' copyrighted work, a curated
collection of them attracts the EU *sui generis* database right on top of that, and many
carry no licence at all. `examples/corpus/` covers the same ground by generating trees of
every relevant shape, scale and study type from recorded seeds -- which is also
reproducible years later, where a downloaded file is only as durable as its URL. If a real
dataset is ever genuinely needed, cite and link it; do not copy it into the repository.

## Current fixtures

| Fixture | Origin | Licence | Notes |
|---|---|---|---|
| `tests/**/fixtures/*.nwk`, `*.nex`, `*.xml`, `*.nhx` | Generated or hand-authored for this repository | Ours (MIT, with the core) | Grammar and malformation coverage |
| `tests/**/fixtures/*.mytrack`, `*.csv`, `*.tsv` | Hand-authored for this repository | Ours (MIT) | Annotation format coverage |
| `examples/*` | Generated programmatically for this repository | Ours (MIT) | Shipped with the product as sample data |
| `examples/corpus/*` | Generated programmatically by `tools/make_corpus.py`, one recorded seed per tree | Ours (MIT) | The shape / scale / study-type corpus. Seeds and shapes are listed in `examples/corpus/README.md` and `corpus.json` |
| `examples/gallery/*` | Rendered by `tools/make_gallery.py` from the two sets above | Ours (MIT) | Figures for the README and the manual |

*(Extend this table whenever a fixture is added. If the table and the tree of files ever
disagree, the table is wrong — fix it.)*

## Synthetic generators

Preferred shapes, since between them they cover the pathological cases:

- **balanced(n)** — the easy case, and the baseline for layout geometry assertions.
- **caterpillar(n)** — maximal depth; the case that breaks recursive implementations.
- **star(n)** — a single polytomy of degree *n*; exercises the parent-rule variants.
- **random_topology(n, seed)** — seeded, therefore reproducible. Always record the seed.
- **with_polytomies()**, **with_negative_lengths()**, **without_lengths()**,
  **ultrametric()** — targeted edge cases.

Seeded generation is required: an unseeded random fixture makes a failure irreproducible
and is worse than no fixture at all.

## If you ever need real biological data

Acceptable sources, each with the licence recorded above before use:

- **Open Tree of Life** — synthesis trees, openly licensed.
- **NCBI Taxonomy** — US Government work, public domain.
- **GTDB** — released under CC-BY.
- **TreeBASE** — check the per-study terms; they vary.

Record the accession, the retrieval date and the licence for anything taken from these.
