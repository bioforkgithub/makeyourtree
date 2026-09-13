# YouTube listing

Everything to paste into the upload form. The repository URL is already filled in;
add the video's own URL to the paper and README once the upload is public.

---

## Title

Pick one. The first is the safest; the others trade reach for specificity.

1. `MakeYourTree: draw and annotate phylogenetic trees offline — full tutorial`
2. `Make publication-ready phylogenetic tree figures without uploading your data`
3. `Free offline alternative for annotating phylogenetic trees (full walkthrough)`

Keep it under about 60 characters if you can, or YouTube truncates it in search
results. Option 1 is 71 — shorten to
`MakeYourTree: annotate phylogenetic trees offline` if that matters to you.

**Avoid** naming another tool in the title. It invites an unflattering
comparison in the comments, and the video stands on its own.

---

## Description

Paste from the line below, down to the end of the tags.

```
MakeYourTree is a free, open-source program for drawing and annotating
phylogenetic trees. It runs entirely on your own computer — no website, no
account, no upload — so unpublished trees and sensitive data never leave your
machine.

This tutorial covers everything from installing it to exporting a
publication-ready figure.

WHAT IT DOES
• Reads Newick, NHX, NEXUS and phyloXML
• Rectangular, slanted, circular, radial and unrooted layouts
• 13 annotation track types — colour strips, heatmaps, bar charts, box plots,
  pie charts, presence/absence matrices, protein domains, and more — all of
  which can be combined on one figure
• Rerooting, ladderizing, collapsing, pruning; everything undoable
• Exports vector SVG and PDF, and PNG at any resolution
• A guided mode that asks what you need and writes you a step-by-step plan
• A command line and Python API, so figures can be regenerated from a script

CHAPTERS
0:00 What this is and why
1:00 Installing it
2:30 The window, and loading a tree
4:30 Layouts: rectangular, circular, unrooted
6:00 Rooting, ladderizing and collapsing
8:00 Adding your own data
10:30 Combining several tracks
12:00 Exporting for a journal
13:00 If you don't know what figure you want
14:30 Command line, and where to get it

DOWNLOAD AND SOURCE CODE
https://github.com/bioforkgithub/makeyourtree

DOCUMENTATION
A 60-page manual (PDF) and a gallery of 49 example figures are in the
repository: https://github.com/bioforkgithub/makeyourtree

LICENCE
MIT — free for any use, including commercial use.

CITING IT
If it helps with something you publish, citation details will be added to the
repository page once the paper describing it is out.

Questions and bug reports are welcome on the repository's issue tracker.
```

---

## Tags

```
phylogenetics, phylogenetic tree, bioinformatics, tree visualization,
tree visualisation, newick, nexus, phyloxml, open source, free software,
scientific figures, data visualization, python, molecular evolution,
computational biology, offline software, research software
```

---

## Thumbnail

Use `examples/gallery/showcase-everything-circular.png` — the six-ring circular
figure. It is colourful, unmistakably a phylogenetic tree, and reads at
thumbnail size.

Add three or four words of large text in a corner. Suggestions:

- `TREE FIGURES — OFFLINE`
- `NO UPLOAD NEEDED`
- `FREE & OPEN SOURCE`

Keep any text out of the bottom-right corner, where the duration badge sits.

---

## After you upload

- [ ] Copy the video URL.
- [ ] Put it in `README.md` under **Gallery and manual** (there is a marked
      placeholder).
- [ ] Rebuild the manual so its copy of the link is current:
      `python docs/manual/build.py`
- [ ] Pin a comment with the repository link — people look there first.

**Do not** put the URL in the paper before the video is public and the link
resolves. A dead link in a published paper cannot be fixed.

---

## Accessibility

YouTube's automatic captions handle clear speech reasonably, but they will
mangle "phylogenetic", "Newick", "phyloXML" and "cladogram" every time. Upload a
corrected transcript — the narration in `TUTORIAL-SCRIPT.md` is most of one
already, so this costs very little and makes the video usable to people who
cannot hear it and searchable by anyone.
