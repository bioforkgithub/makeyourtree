# MakeYourTree — 15-minute tutorial: shooting script

Everything you need to record the video in one or two takes. Narration is written
to be **read aloud as-is**; if a sentence does not sound like you, change it —
sounding natural matters more than matching this text.

**Total running time: 15:00.** Section timings are targets, not rules. If a
section runs long, the two easiest to shorten are §4 (Layouts) and §9 (Command
line).

---

## Before you press record

- [ ] Rebuild so you are demonstrating current code:
      `python -m makeyourtree_studio.packaging.build`
- [ ] **Reset the settings**, or the app opens in whatever layout you last used
      and the video starts on the wrong foot. Delete the settings and confirm it
      opens on Rectangular:
      `python docs/video/reset_demo.py`
- [ ] Close every other window. Turn off notifications.
- [ ] Set the display to **1920×1080** and the app to **full screen**.
- [ ] Increase the OS font scaling to 125% if your screen is large — YouTube
      compresses text badly and viewers on phones will thank you.
- [ ] Have these open in a text editor, ready to show:
      `examples/primates_region.mytrack`
- [ ] Have a terminal open in the repository root, font size at least 16pt.
- [ ] Record at 1080p60 if you can, 1080p30 is fine. OBS Studio is free and does
      this well.
- [ ] Do a 20-second test recording and **listen back** before committing to a
      full take. Bad audio loses more viewers than anything else.

---

## §1 — What this is and why (0:00–1:00)

*On screen: the finished showcase figure,
`examples/gallery/showcase-everything-circular.png`, full screen.*

> Hello. This is MakeYourTree — a free program for drawing and annotating
> phylogenetic trees.
>
> This figure is what we are going to build up to. A tree, with six different
> kinds of data wrapped around it as rings.
>
> Two things make this program different from what you may have used before.
>
> First, it runs entirely on your own computer. There is no website, no account,
> and no upload. It has no networking in it at all — so if your tree is
> unpublished, or your data is sensitive, it never leaves your machine.
>
> Second, it is completely free and open source under the MIT licence. You can
> use it for anything, including commercial work.
>
> In the next fifteen minutes I will show you how to install it, load a tree,
> draw it several ways, add your own data to it, and export a figure fit for a
> journal. Timestamps are in the description, so skip to whatever you need.

*Cut to the application window with a tree loaded — a still, no interaction.*

---

## §2 — Installing (1:00–2:30)

*On screen: terminal.*

> There are two ways to install it, and both work the same on Windows, macOS and
> Linux.

*Type, do not paste — viewers follow typing better:*

```
git clone https://github.com/bioforkgithub/makeyourtree.git
cd makeyourtree
```

> If you use conda, this is the easy route.

```
conda env create -f environment.yml
conda activate makeyourtree
pip install -e . --no-deps
```

> One thing worth knowing: that `--no-deps` at the end matters. Conda has already
> installed everything, and without it pip installs a second copy of the graphics
> library — about six hundred megabytes you do not need.
>
> If you would rather not use conda, use a normal Python environment instead.

*Show, do not run:*

```
python -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\Activate.ps1
pip install -e ".[studio]"
```

> Then check it worked:

```
makeyourtree --version
```

> And start the program:

```
makeyourtree-studio
```

*The window opens.*

> If you are on Linux and it complains about a Qt platform plugin, there is one
> extra line of system libraries to install — it is in INSTALL.md, and the conda
> route avoids it entirely.

---

## §3 — The window (2:30–4:30)

*App open, empty.*

> Let us load a tree. **File, Open Tree** — or Control-O.

*File ▸ Open Tree… → `examples/primates.nwk`. The tree appears.*

> That is sixteen primate species. The file is Newick, which is the commonest
> format, but it also reads NEXUS, phyloXML and NHX, and it works out which one
> you gave it by looking inside the file rather than trusting the extension.

*Point at each region with the cursor as you name it.*

> Three parts to the window. In the middle is the figure. On the left is the tree
> as a list you can expand — clicking a node here selects it in the figure, and
> the other way round. On the right is the Style panel, where the layout controls
> live.
>
> Scroll to zoom. Notice the zoom follows the pointer, so whatever you are
> looking at stays under the cursor. Drag to move around. Control-zero fits the
> whole thing back in the window.

*Demonstrate: zoom in on a clade, pan, Ctrl+0.*

> One thing you will see at the bottom: it says it found something in the file.
> Let us look — Control-D.

*Ctrl+D → the diagnostics dialog.*

> This is not an error. It is telling me the internal labels in my file are
> numbers, so it read them as branch support values, which is almost always
> right. The program reads messy files rather than refusing them, but it tells
> you what it had to decide. Close that.

---

## §4 — Drawing it different ways (4:30–6:00)

> The buttons along the top change the shape. Or press one to five.

*Click each, pausing about two seconds on each.*

> Rectangular — the familiar one, and the right choice most of the time.
>
> Slanted.
>
> Circular — this is the one that lets a big tree fit on a page.
>
> Radial.
>
> And unrooted, which makes no claim at all about which node is the ancestor.

*Back to Rectangular. Click Phylogram, then Cladogram (aligned tips).*

> Separately from the shape, there is this choice: phylogram or cladogram.
>
> In a phylogram, horizontal distance is branch length — it means something. In a
> cladogram it means nothing; only the branching order is being shown.
>
> This matters and it is worth saying in your figure caption, because a reader
> genuinely cannot tell which one they are looking at.

*Back to Phylogram.*

---

## §5 — Changing the tree (6:00–8:00)

> Now let us change the tree itself. Everything here is undoable with Control-Z,
> so experiment freely.

*Press L.*

> **L** ladderizes it — it sorts the branches by size. It costs nothing and makes
> the branching order much easier to follow. I do this to almost every figure.

*Press M.*

> **M** roots it at the midpoint. Where the root sits decides which groups look
> like natural groups, so it is the single choice most likely to change what a
> reader concludes.
>
> Midpoint rooting assumes all the lineages evolve at roughly the same rate. If
> you have an outgroup, use that instead — it is a real hypothesis rather than an
> assumption. That is Control-Shift-R.
>
> Whichever you use, say so in the caption.

*Click an internal node, press C.*

> Select a clade and press **C** to collapse it. The triangle is sized by what is
> inside it, so the figure still shows how much you folded away. Press C again to
> bring it back.

*Ctrl+F.*

> And Control-F searches by name. Useful when your tree has four hundred tips and
> you need the six you care about.

*Ctrl+Z a few times back to a clean ladderized tree.*

---

## §6 — Adding your own data (8:00–10:30)

*Cut to the text editor showing `examples/primates_region.mytrack`.*

> This is where it gets useful. Your tree probably has a spreadsheet next to it,
> and this is how you get the spreadsheet onto the tree.
>
> This is an annotation file. The top says what kind of track it is — here, a
> colour strip. Then the colours for each category. Then the data: one line per
> species, with its region.
>
> You do not have to write these by hand. The program imports CSV and
> tab-separated files straight out of Excel.

*Back to the app. Annotate ▸ Import Annotations (Ctrl+I) → `primates_region.mytrack`.*

> Control-I to import.

*The strip appears.*

> There it is, with a legend.
>
> One thing to watch here, and it is the most common thing that goes wrong: the
> names in your spreadsheet have to match the names in your tree exactly. The
> import shows you how many rows matched before it adds anything, so read that
> number. If it says nought matched, it is almost always underscores versus
> spaces.

*Ctrl+I again → `primates_bodymass.mytrack`.*

> Let us add a second one — a bar chart of body mass.

*Turn on Align Tips.*

> And I will turn on **Align tips**, which lines every row up with its data. Once
> you have tracks, you almost always want this.

> There are thirteen kinds of track: colour strips, heatmaps, bar charts, box
> plots, pie charts, presence-absence matrices, protein domains, and more. They
> all work the same way.

---

## §7 — Combining everything (10:30–12:00)

*File ▸ Open Tree → `examples/corpus/study-pangenome.nwk`, then import both of
its `.mytrack` files.*

> Here is a bigger example — thirty-six bacterial strains, with resistance genes
> and genome sizes.

*Click Circular.*

> And here is the part I like most. I switch to circular, and every track becomes
> a ring. I changed nothing about the data. Not one setting on any track.
>
> That is because tracks are not written for a particular shape. They are written
> in terms of "which row" and "how far out", and the program works out where that
> lands. So a heatmap becomes a ring for free.

*Show `examples/gallery/showcase-everything-circular.png` full screen.*

> That is what lets you stack six different kinds of data on one tree, like this
> — and it is the figure I showed you at the start.

---

## §8 — Getting the figure out (12:00–13:00)

*Ctrl+E → export dialog.*

> Control-E exports. Three formats.
>
> **SVG** and **PDF** are vector — they stay sharp at any size, and this is what
> a journal wants. **PNG** is pixels, for slides.
>
> If you pick PNG you set the resolution here. Three hundred DPI is what most
> journals ask for. Notice it tells you the exact pixel size you are going to
> get, before you save, so you are not guessing.
>
> One useful detail: the same figure exported as SVG and as PDF comes out the
> same physical size, so you can swap them in your manuscript without anything
> moving.

*Export a PDF. Then File ▸ Save.*

> And save the project with Control-S. That keeps the tree, the layout and all
> your tracks together, so in six months when a reviewer asks for a change you
> open one file instead of rebuilding it.

---

## §9 — If you do not know what you want (13:00–14:30)

*Press F1.*

> Last thing, and this is for anyone who has a tree and is not sure what the
> figure should even look like. Press **F1**.

*The guide opens. Answer three or four questions on camera.*

> It asks about your data and about where the figure is going. Notice it does not
> ask you about the software — it asks how many tips you have and whether your
> branch lengths mean anything, which are questions you can actually answer.

*Reach the plan.*

> And it writes you a plan. Numbered steps, with the actual commands, using your
> own file names. Every recommendation tells you why, so you can disagree with
> it.
>
> Save it, and you can close the program and come back next week — it remembers
> which steps you finished.

*Click "Read a published figure...", choose a PDF from the gallery.*

> There is also this. If you have seen a figure in a paper and you want something
> like it, hand it over and it will measure it — whether it is circular, whether
> it has colour bands, how many colours.
>
> To be clear about what that is: it measures the picture, it does not recognise
> it. It shows you what it measured and how confident it is, and where it cannot
> tell, it asks you instead of guessing.

---

## §10 — Wrap up (14:30–15:00)

*Terminal.*

> Everything I have shown you also works from the command line, which is what you
> want if you are producing figures from a pipeline.

```
makeyourtree render tree.nwk figure.pdf --mode circular --track data.mytrack
```

> The link to the code is in the description. It is free, it is open source, and
> there is a sixty-page manual you can download.
>
> If you use it in a paper, there is a citation on the repository page.
>
> Thanks for watching.

*End card: repository URL and the project name, 5 seconds.*

---

## Retakes worth planning for

Sections most likely to need a second take, in order:

1. **§6 import** — the file dialog is fiddly on camera. Have the folder already
   open at the right location.
2. **§9 guide** — clicking through questions while talking is harder than it
   looks. Decide your answers in advance.
3. **§4 layouts** — easy to click too fast. Count two seconds on each.

## If you are short of time

A 6-minute cut that still works: §1, §3, §6, §7, §8. Skip installation,
tree editing, the guide and the command line. Most viewers want to see the
annotation and the export.
