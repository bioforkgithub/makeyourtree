# SPDX-License-Identifier: MIT
"""Stage-by-stage timings on synthetic trees — the numbers in Table 1 of the paper.

Each of the four stages is timed separately rather than end to end, because the
interesting question is not "how long does a figure take" but "which stage grows
with the tree". Parsing, layout, composition and serialisation have different
costs and different fixes, and a single total would hide that.

Trees are generated here rather than loaded from a corpus so the benchmark is
self-contained and reproducible from a fixed seed, and so no third-party example
dataset is needed. Two shapes are used:

* **random binary**, built by repeatedly joining two random subtrees, which gives
  a balanced-ish tree of the kind most analyses produce; and
* **caterpillar**, maximally unbalanced, whose root-to-tip path length equals its
  node count. That shape is the reason every traversal in MakeYourTree is iterative:
  CPython's recursion limit is 1000, so a recursive implementation fails on a
  caterpillar of a few thousand nodes. Serially sampled sequence data produces
  this shape in practice, so it is not a contrived case.

Run with::

    python tools/benchmark.py
    python tools/benchmark.py --sizes 100 1000 --no-caterpillar
"""

from __future__ import annotations

import argparse
import gc
import random
import statistics
import sys
import time
from typing import Callable, Sequence, TypeVar

from makeyourtree.doc import Document
from makeyourtree.io import read_newick
from makeyourtree.layout import LayoutMode, LayoutParams, compute_layout
from makeyourtree.render import render_svg
from makeyourtree.scene import compose

__all__ = ["random_newick", "caterpillar_newick", "main"]

#: Fixed so the reported table is reproducible, not merely repeatable in shape.
SEED = 20260904

DEFAULT_SIZES: tuple[int, ...] = (100, 1000, 5000, 20000, 100000)

T = TypeVar("T")


def random_newick(n: int, rng: random.Random) -> str:
    """A random binary tree with *n* tips, as a Newick string.

    Built by repeated joining of two randomly chosen subtrees, which is cheap and
    produces topologies without the systematic imbalance a sequential-insertion
    scheme would introduce. Assembled as text rather than as a tree so that the
    parser is measured on genuine input.
    """
    parts = [f"T{i}:{rng.uniform(0.01, 1.0):.4f}" for i in range(n)]
    while len(parts) > 1:
        a = parts.pop(rng.randrange(len(parts)))
        b = parts.pop(rng.randrange(len(parts)))
        parts.append(f"({a},{b}):{rng.uniform(0.01, 1.0):.4f}")
    return parts[0] + ";"


def caterpillar_newick(n: int) -> str:
    """A maximally unbalanced tree of *n* tips: depth equals tip count."""
    text = "T0:0.1"
    for i in range(1, n):
        text = f"({text},T{i}:0.1):0.1"
    return text + ";"


def _timed(fn: Callable[[], T]) -> tuple[float, T]:
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def _once(n: int, rng: random.Random) -> tuple[float, float, float, float, int, float]:
    """One timed pass over a fresh random tree of *n* tips."""
    newick = random_newick(n, rng)
    t_parse, tree = _timed(lambda: read_newick(newick))
    doc = Document(tree=tree, params=LayoutParams(mode=LayoutMode.RECTANGULAR))
    t_layout, _ = _timed(lambda: compute_layout(tree, doc.params))
    t_compose, scene = _timed(lambda: compose(doc))
    t_svg, svg = _timed(lambda: render_svg(scene))
    # Batches, not nodes: composition groups same-styled primitives, so this
    # count staying flat as n grows is the property that keeps repainting cheap.
    return (t_parse, t_layout, t_compose, t_svg, scene.count(), len(svg) / 1e6)


def _row(n: int, rng: random.Random, repeat: int = 1, spread: bool = False) -> str:
    """One table row: the median of *repeat* passes.

    The median rather than the mean because a single scheduling hiccup on a
    desktop machine moves a mean and does not move a median, and because a
    figure quoted in a paper should describe the typical run rather than the
    luckiest or the unluckiest one.
    """
    runs = []
    for _ in range(max(1, repeat)):
        # Each pass builds a fresh tree of its own; without collecting between
        # them the later passes pay for the earlier ones' garbage and the
        # median drifts upward with the repeat count rather than settling.
        gc.collect()
        runs.append(_once(n, rng))
    med = [statistics.median(r[i] for r in runs) for i in range(4)]
    batches = runs[0][4]
    megabytes = statistics.median(r[5] for r in runs)
    line = (f"{n:>7} {med[0]:9.3f} {med[1]:9.3f} {med[2]:10.3f} "
            f"{med[3]:8.3f} {batches:>8} {megabytes:8.2f}")
    if spread and len(runs) > 1:
        total = [sum(r[:4]) for r in runs]
        line += f"   [total {min(total):.3f}-{max(total):.3f} s over {len(runs)}]"
    return line


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="makeyourtree-benchmark",
        description="Time parsing, layout, composition and SVG output by tree size.",
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES),
                        help="tip counts to measure")
    parser.add_argument("--caterpillar", type=int, default=50000,
                        help="tip count for the deep-tree check (0 to skip)")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="time each size N times and report the median, "
                             "with the range of total times alongside")
    args = parser.parse_args(argv)

    rng = random.Random(SEED)
    print(f"CPython {sys.version.split()[0]} on {sys.platform}; seed {SEED}")
    print(f"{'tips':>7} {'parse s':>9} {'layout s':>9} {'compose s':>10} "
          f"{'svg s':>8} {'batches':>8} {'svg MB':>8}")
    if args.repeat > 1:
        print(f"(median of {args.repeat} runs per size)")
    for n in args.sizes:
        print(_row(n, rng, args.repeat, spread=True))

    if args.caterpillar:
        n = args.caterpillar
        t_parse, tree = _timed(lambda: read_newick(caterpillar_newick(n)))
        params = LayoutParams(mode=LayoutMode.RECTANGULAR)
        t_layout, _ = _timed(lambda: compute_layout(tree, params))
        print(f"\ncaterpillar, depth {n}: parse {t_parse:.3f} s, "
              f"layout {t_layout:.3f} s "
              f"(CPython recursion limit is {sys.getrecursionlimit()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
