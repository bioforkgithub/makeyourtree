# SPDX-License-Identifier: MIT
"""Turn answers into an ordered list of things to do.

The output is deliberately concrete.  A plan that says "consider an appropriate
layout" helps nobody; a plan that says "use a circular layout, because 400 tips
do not fit on a page as a rectangle" and then says which menu to open and which
item to pick in which drop-down is the difference between advice and help.

Two readers are served at once.  Most people will follow the plan inside the
desktop application, so every step that can be done there says exactly where:
the menu, the panel, the group box, the drop-down and the option in it, spelled
the way the application spells them.  Those names are written in bold and
nothing else is, so a test can check each one against the real interface and
catch the plan drifting from it.  People who prefer a terminal get the
equivalent command as well, spelled with their own file names where known.

The language is kept plain on purpose.  The person reading this may be a
student making their first tree figure, and possibly not reading in their
first language: short sentences, everyday words, and any technical term
explained the first time it appears.

Recommendations are stated with their reason attached.  The user is entitled to
disagree -- they know their data -- and cannot judge the advice without knowing
what it rests on.

The functions here are pure: answers and observations in, a :class:`Plan` out.
That is what lets the same engine serve the command line, the desktop wizard and
the tests without any of them re-deriving the logic.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..tracks import get_track_class
from .plan import Plan, Step
from .questions import answered_summary, wanted_extras

__all__ = ["build_plan", "recommend_layout", "TRACK_ADVICE", "in_app"]

#: What each kind of extra data becomes: a track type, and how to lay out the
#: table for it. Keyed by the ``extra_data`` choices in the questionnaire.
TRACK_ADVICE: dict[str, tuple[str, str]] = {
    "category": (
        "color-strip",
        "Make a table with two columns: the tip name, and the group that tip "
        "belongs to -- for example its host species or where it was sampled. "
        "Each group gets its own colour."),
    "value": (
        "bar-chart",
        "Make a table with two columns: the tip name, and one number. Each tip "
        "gets a bar as long as its number. If space is tight and you only need "
        "to show high against low, choose **Gradient** instead of **Bar chart** "
        "in the **Track type:** drop-down: it shows the number as a shade of "
        "colour."),
    "matrix": (
        "heatmap",
        "Make a table with the tip name first, then one column for each sample "
        "or condition, each holding a number. Every number becomes a coloured "
        "square. If your numbers go below and above zero (a log fold change, "
        "for example), give the scale a clear middle colour so a reader can "
        "see which side of zero each value is on: after importing, set "
        "**color min**, **color mid** and **color max** for the track in the "
        "**Tracks** panel, and keep **use mid** ticked."),
    "presence": (
        "binary-matrix",
        "Make a table with the tip name first, then one column for each "
        "feature (a gene, a resistance, a trait). Write 1 for present and 0 "
        "for absent. If you do not know, leave the cell empty -- do not write "
        "0. \"Absent\" and \"unknown\" are different statements, and the track "
        "draws them differently."),
    "composition": (
        "pie-chart",
        "Make a table with the tip name first, then one column for each part "
        "of the whole. Each tip gets a small pie. The numbers do not have to "
        "add up to 1 or to 100; the program works out the shares."),
    "series": (
        "line-chart",
        "Make a table with the tip name first, then one column for each time "
        "point, in order. Each tip gets a small line chart. To compare tips "
        "fairly, give them all the same scale: after importing, set **value "
        "min** and **value max** for the track in the **Tracks** panel."),
    "domains": (
        "domain-architecture",
        "Make a table with the tip name first, then the length of the protein, "
        "then one column per domain written as start|end|shape|colour|label -- "
        "for example 10|120|rect|#0072B2|Kinase. Because the domains use the | "
        "sign, save the table with commas or tabs between columns, and do not "
        "pick **Pipe** in the **Delimiter:** drop-down."),
    "links": (
        "connections",
        "Make a table with one row per link: the first tip name, the second "
        "tip name, and, if you want them, a weight, a colour and a label. Each "
        "row draws a line between the two tips."),
    "highlight": (
        "clade-range",
        "Make a table with one row per group you want to highlight. The first "
        "column is the name of the node where the group starts (an internal "
        "node name from your tree file), then a colour and a label. When you "
        "import it, tick **Also match internal node names**, because these rows "
        "name inner nodes rather than tips."),
}

#: Presentation extras: a title, what the extra is for in plain words, and
#: where to find it in the application. Separate from TRACK_ADVICE because
#: these are not data: they are decisions about how the same data is shown.
EXTRA_ADVICE: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "support": (
        "Show branch support values",
        "A support value says how sure the analysis is about a branch. Say in "
        "the figure caption which kind yours are: bootstrap percentages and "
        "Bayesian posterior probabilities look the same on a figure but mean "
        "different things. It is often clearer to hide the weak ones than to "
        "print them all.",
        ("Open the **Style** panel on the right of the window. If you cannot "
         "see it, choose **View > Style Panel** (Alt+2).",
         "Go to the **Support** group and tick **Show support values**.",
         "In **Threshold**, type the smallest value you want to show, for "
         "example 70. Anything lower is hidden. Leave it at **no floor** to "
         "show every value.",
         "In the **Position** drop-down, choose where the values go: **Above "
         "the branch**, **Below the branch**, or **As a sized marker** (a dot "
         "that is bigger when support is higher).",
         "**Format** sets how numbers are written. {:.0f} gives whole numbers "
         "(95); {:.2f} gives two decimals (0.95).")),
    "scale_bar": (
        "Show a scale bar",
        "The scale bar tells the reader how long one unit of branch length is "
        "-- for example 0.1 changes per site, or one million years. Without "
        "it, a reader cannot read the branch lengths at all.",
        ("Open the **Style** panel (**View > Style Panel**, Alt+2).",
         "In the **Support** group, tick **Show scale bar**.")),
    "collapse": (
        "Fold away the groups you are not discussing",
        "Each folded group is drawn as a triangle. The triangle's size shows "
        "how many tips are inside, so the reader can still see how much was "
        "folded away.",
        ("In the tree, click the node where the group starts (the point where "
         "its branches split). Double-click it to select the whole group.",
         "Choose **Tree > Collapse / Expand** (shortcut: C). Do the same again "
         "to unfold it.",
         "**Tree > Expand All** (Shift+C) unfolds every group at once.")),
    "guides": (
        "Line up the tips and add guide lines",
        "All tip names move into one straight column, and a dotted line joins "
        "the end of each branch to its name and its data. This makes a wide "
        "figure easy to follow across the page.",
        ("Choose **View > Align Tips** (shortcut: A).",
         "Or open the **Style** panel and, in the **Layout** group, tick "
         "**Align tips** and **Guide lines**.")),
    "symbols": (
        "Mark particular nodes with symbols",
        "A symbols track puts a small shape on the nodes you choose. Its size "
        "or colour can show a number. By default the area of the shape follows "
        "the number, not its width. That is the honest choice: if the width "
        "followed the number, big values would look far bigger than they are.",
        ("Make a table with two columns: the node or tip name, and the value.",
         "Choose **Annotate > Import Annotations...** (Ctrl+I) and pick your "
         "file.",
         "In the **Track type:** drop-down, choose **Symbols**.",
         "If some rows name inner nodes, tick **Also match internal node "
         "names**. Then click **Check matches**, and **Import**.")),
    "legend": (
        "Give every track a legend",
        "A colour with no legend is decoration, not data: the reader cannot "
        "tell what it means.",
        ("When you import each table, type a clear name in **Title:**. That "
         "name becomes the legend heading.",
         "When you export (**File > Export Figure...**), leave **Include "
         "legend** ticked.",
         "If you write .mytrack files by hand, put show = true in the [legend] "
         "section of each one.")),
    "dark": (
        "Use a dark background",
        "Good for slides. The dark background goes into the exported file too, "
        "so check your journal first: most want white.",
        ("Choose **View > Dark Theme** (Ctrl+T).",
         "Or open the **Style** panel, go to the **Theme** group, and choose "
         "**Dark** in the **Preset** drop-down.",
         "To work in dark but export on white, choose **White** in the "
         "**Background:** drop-down when you export.")),
}


#: Destination to (format, extra render flags, prose).
_DESTINATION: dict[str, tuple[str, str, str]] = {
    "paper": ("pdf", "--page column",
              "A PDF is a vector file: it stays sharp at any size, and "
              "journals accept it. Make it as wide as one column of the "
              "journal page -- often about 85 mm, but check the journal's "
              "author guidelines."),
    "thesis": ("pdf", "--width 160mm",
               "A PDF is a vector file: it stays sharp at any size. Make it as "
               "wide as the text on your thesis page, about 160 mm."),
    "talk": ("png", "--dpi 150 --width 250mm",
             "A PNG image is right for slides. Screens do not need print "
             "quality, and a smaller file keeps the slides fast."),
    "poster": ("png", "--dpi 300 --width 400mm",
               "A large, sharp PNG image for printing. If your printer takes "
               "PDF, which most do, a PDF is even sharper."),
    "explore": ("svg", "",
                "An SVG file for a quick look. Nothing here is final."),
}

#: The export dialog's names for each format and background choice.
_FORMAT_LABEL = {"pdf": "PDF (vector)", "png": "PNG (raster)",
                 "svg": "SVG (vector)"}

#: Layout mode -> (View menu item, its shortcut, Style panel **Mode** item).
_MODE_UI = {
    "rectangular": ("Rectangular", "1", "Rectangular"),
    "circular": ("Circular", "3", "Circular"),
    "unrooted": ("Unrooted", "5", "Unrooted"),
}

#: Branch mode -> (View menu item, its shortcut, Style panel **Branches** item).
_BRANCH_UI = {
    "phylogram": ("Phylogram", "Ctrl+1", "Phylogram"),
    "cladogram-aligned": ("Cladogram (aligned tips)", "Ctrl+2",
                          "Cladogram Aligned"),
}


def in_app(*lines: str) -> str:
    """A numbered "how to do it in MakeYourTree" block for a step's detail.

    Kept as one helper so every step presents its instructions the same way,
    and so the heading a reader learns to look for never changes wording.
    """
    body = "\n".join(f"{index}. {line}" for index, line in enumerate(lines, 1))
    return f"**How to do it in MakeYourTree:**\n\n{body}"


def _track_name(type_id: str) -> str:
    """The name the application shows for a track type.

    Read from the registry rather than repeated here, so a renamed track type
    cannot leave the plan telling people to pick an item that no longer exists.
    """
    try:
        return get_track_class(type_id).display_name or type_id
    except KeyError:
        return type_id.replace("-", " ").capitalize()


def recommend_layout(answers: dict[str, Any],
                     measured: Iterable[str] = ()) -> tuple[str, str]:
    """A layout mode and the reason for it.

    The reason matters more than the choice. The user can overrule a
    recommendation they disagree with only if they can see what it was based on
    -- and that includes being told when a choice came from measuring a figure
    they uploaded rather than from something they said. Claiming "you asked for
    this" when they did not is the fastest way to lose their trust in the rest.
    """
    shape = answers.get("shape")
    if shape in {"rectangular", "circular", "unrooted"}:
        if "shape" in set(measured):
            return shape, ("Measured from the figure you gave, not chosen by "
                           "you. Change it if it does not suit your data.")
        return shape, "You asked for this shape."
    if answers.get("rooting") == "unrooted":
        return ("unrooted",
                "You asked to show the tree without a root, so the drawing "
                "must not suggest which branch is the oldest.")

    size = answers.get("tip_count")
    if size == "thousands":
        return ("circular",
                "With more than a thousand tips, a rectangle becomes a very "
                "tall, thin strip. A circle uses the page much better and "
                "keeps the whole tree on one page.")
    if size == "hundreds":
        extras = answers.get("extra_data") or []
        many = len([e for e in extras if e != "none"]) >= 2
        if many:
            return ("circular",
                    "A few hundred tips plus several kinds of data: in a "
                    "circle, each kind of data becomes a ring around the "
                    "tree, which takes far less room than columns beside a "
                    "tall rectangle.")
        return ("rectangular",
                "A few hundred tips still fit well in a rectangle, and a "
                "rectangle is easier to read than a circle.")
    return ("rectangular",
            "For a small tree a rectangle is the clearest choice, and it is "
            "what most readers expect.")


def _branch_mode(answers: dict[str, Any]) -> tuple[str, str]:
    """A branch mode and the reason, never crediting the user with an answer.

    An unanswered question must not be reported back as "your branch lengths
    are meaningful": that puts words in the user's mouth, the same trust
    failure :func:`recommend_layout` guards against.
    """
    meaning = answers.get("branch_meaning")
    if meaning in {"meaningless", "absent"}:
        return ("cladogram-aligned",
                "Your branch lengths carry no real information, so do not "
                "draw them to scale. Show only the order of branching, with "
                "all the tips lined up (this is called a cladogram).")
    if meaning == "unsure":
        return ("phylogram",
                "For now this assumes your branch lengths mean something and "
                "draws them to scale (a phylogram). If the check earlier in "
                "the plan shows they do not, switch to a cladogram instead.")
    if meaning in {"substitutions", "time"}:
        return ("phylogram",
                "Your branch lengths mean something, so draw them to scale "
                "(this is called a phylogram).")
    return ("phylogram",
            "You did not say what your branch lengths mean, so this assumes "
            "they mean something and draws them to scale (a phylogram). If "
            "they do not, switch to a cladogram instead.")


def _layout_clicks(mode: str, branch_mode: str) -> str:
    view_item, key, combo_item = _MODE_UI[mode]
    branch_item, branch_key, branch_combo = _BRANCH_UI[branch_mode]
    lines = [
        f"Choose **View > {view_item}** (shortcut: {key}). Or open the "
        f"**Style** panel (**View > Style Panel**, Alt+2) and, in the "
        f"**Layout** group, choose **{combo_item}** in the **Mode** drop-down.",
        f"Choose **View > {branch_item}** ({branch_key}). Or, in the same "
        f"**Layout** group, choose **{branch_combo}** in the **Branches** "
        f"drop-down.",
    ]
    if mode == "circular":
        lines.append(
            "Fine-tune the circle in the **Circular** group of the **Style** "
            "panel. **Arc** is how much of the circle is used (360 is a full "
            "circle; 180 is a half circle). **Start angle** turns the whole "
            "tree. **Inner radius** leaves an empty hole in the middle. The "
            "**Direction** drop-down chooses **Clockwise** or "
            "**Anticlockwise**. Tick **Rotate labels with the radius** so each "
            "name points outwards along its branch.")
    elif mode == "unrooted":
        lines.append(
            "Fine-tune it in the **Unrooted** group of the **Style** panel. "
            "The **Method** drop-down offers **Equal Angle** (quick) and "
            "**Equal Daylight** (spreads the branches out more evenly). With "
            "**Equal Daylight**, a higher **Daylight passes** number gives a "
            "tidier drawing but takes longer.")
    else:
        lines.append(
            "In the **Layout** group, **Width** makes the tree wider or "
            "narrower and **Row spacing** sets the gap between tips.")
    lines.append(
        "To make the tree look tidier, choose **Tree > Ladderize Descending** "
        "(Shift+L). It puts the biggest groups first, so the tree forms a "
        "neat staircase. This changes only the drawing, not the tree itself.")
    return in_app(*lines)


def _import_clicks(track_name: str) -> str:
    return in_app(
        "Save your table as a CSV file (.csv) or a tab-separated text file "
        "(.tsv or .txt). In Excel, use File > Save As and choose \"CSV\". A "
        ".mytrack file works too.",
        "Choose **Annotate > Import Annotations...** (Ctrl+I).",
        "Next to **File:**, click **Browse...** and pick your table.",
        f"In the **Track type:** drop-down, choose **{track_name}**.",
        "Leave the **Delimiter:** drop-down on **Detect automatically**. If "
        "the **Preview:** looks wrong (everything squashed into one column), "
        "pick the sign your file uses between columns: **Comma**, **Tab**, "
        "**Semicolon** or **Pipe**.",
        "In the **Key column:** drop-down, choose the column that holds the "
        "tip names.",
        "In the **Value columns:** list, tick the columns you want to show "
        "and untick the rest.",
        "Type a short, clear name in **Title:**. It becomes the heading of "
        "the legend.",
        "Click **Check matches** and read the **Match report:** (see the next "
        "step). When it looks right, click **Import**.")


def build_plan(answers: dict[str, Any], *,
               observations: Iterable[str] = (),
               measured: Iterable[str] = (),
               tree_file: str = "your-tree.nwk",
               output_stem: str = "figure",
               title: str | None = None) -> Plan:
    """Assemble the steps implied by *answers*.

    *tree_file* and *output_stem* are woven into the commands so they can be
    pasted straight into a terminal. When the caller does not know the real file
    name, the placeholder is obvious enough to be replaced without confusion.
    """
    answers = dict(answers or {})
    extras = [e for e in (answers.get("extra_data") or []) if e != "none"]
    steps: list[Step] = []

    def add(step_id: str, title_: str, detail: str = "", command: str = "",
            optional: bool = False) -> None:
        steps.append(Step(id=step_id, title=title_, detail=detail,
                          command=command, optional=optional))

    # -------------------------------------------------- 1. know what you have
    inspect_detail = (
        "Before you decide anything, check three things: how many tips your "
        "tree has (the tips are the names at the ends of the branches), "
        "whether it already has a root, and whether it has branch lengths and "
        "support values.")
    if answers.get("tip_count") == "unknown":
        inspect_detail += (
            " You said you did not know how many tips there are. Point 3 below "
            "tells you. Until you know, the plan treats the tree as small.")
    add("inspect",
        "Find out what is in your tree file",
        inspect_detail + "\n\n" + in_app(
            "Choose **File > Open Tree...** (Ctrl+O) and open your tree file.",
            "Choose **View > Inspector Panel** (Alt+4) to show the "
            "**Inspector**.",
            "Click the root of the tree (the node where it all starts). In "
            "the **Inspector**, **Descendant leaves** is the number of tips.",
            "Click the end of any branch. If **Branch length** and "
            "**Support** are empty, your file does not have them.",
            "Choose **Help > Diagnostics...** (Ctrl+D) to see anything odd the "
            "program noticed while reading your file."),
        f"makeyourtree info {tree_file}")

    if answers.get("branch_meaning") == "unsure":
        add("check-lengths",
            "Decide whether your branch lengths mean anything",
            "Branch length is the length of each line in the tree. If the tree "
            "came from a tree-building program (IQ-TREE, RAxML, MrBayes, "
            "BEAST and so on), the lengths usually mean something -- often "
            "\"changes per site\", or time -- and are worth drawing to scale. "
            "If every branch has the same length, or they are all 1, they mean "
            "nothing, and you should show only the order of branching (a "
            "cladogram).\n\n" + in_app(
                "Click the ends of a few different branches and compare their "
                "**Branch length** in the **Inspector**.",
                "If they are all the same, choose **View > Cladogram (aligned "
                "tips)** (Ctrl+2).",
                "If they differ, keep **View > Phylogram** (Ctrl+1)."))

    # -------------------------------------------------------- 2. root the tree
    rooting = answers.get("rooting")
    if rooting == "outgroup":
        add("root",
            "Root the tree on your outgroup",
            "An outgroup is one or more species that you know sit outside the "
            "group you are studying. Rooting on it is the safest choice, "
            "because it rests on real knowledge rather than on a guess about "
            "how fast things evolved.\n\n" + in_app(
                "Choose **View > Search Panel** (Ctrl+F) and type the "
                "outgroup's name in the **Find nodes...** box.",
                "Click **Select all matches**. If the outgroup has several "
                "members, you can instead click the first one in the tree and "
                "Shift+click each of the others.",
                "Choose **Tree > Root on Outgroup** (Ctrl+Shift+R).",
                "If it went wrong, **Edit > Undo** (Ctrl+Z) puts it back.")
            + "\n\nIn the terminal command below, replace OUTGROUP with the "
              "name. For several names, separate them with commas.",
            f"makeyourtree reroot {tree_file} rooted.nwk --outgroup OUTGROUP")
    elif rooting == "midpoint":
        add("root",
            "Root the tree at its midpoint",
            "The program puts the root halfway along the longest path between "
            "any two tips. This works well when all the lineages evolved at "
            "roughly the same speed, and less well when some evolved much "
            "faster. Say in the figure caption that you used midpoint "
            "rooting.\n\n" + in_app(
                "Choose **Tree > Midpoint Root** (shortcut: M).",
                "If it went wrong, **Edit > Undo** (Ctrl+Z) puts it back."),
            f"makeyourtree reroot {tree_file} rooted.nwk --midpoint")
    elif rooting == "unsure":
        add("root",
            "Decide where the root goes",
            "Where the root sits decides which groups look like true family "
            "groups, so it can change what a reader concludes. If you have "
            "any outgroup (species you know sit outside your group), use it. "
            "If not, midpoint rooting is fine as long as you say so in the "
            "caption.\n\n" + in_app(
                "If you have an outgroup: select it (click it in the tree, or "
                "find it with **View > Search Panel**), then choose **Tree > "
                "Root on Outgroup** (Ctrl+Shift+R).",
                "If you do not: choose **Tree > Midpoint Root** (shortcut: M)."),
            f"makeyourtree reroot {tree_file} rooted.nwk --midpoint",
            optional=True)

    rooted_file = "rooted.nwk" if rooting in {"outgroup", "midpoint", "unsure"} else tree_file

    # ------------------------------------------------------ 3. annotation data
    for extra in extras:
        track_type, guidance = TRACK_ADVICE.get(extra, ("color-strip", ""))
        name = _track_name(track_type)
        add(f"data-{extra}",
            f"Prepare and import your data as a \"{name}\" track",
            guidance + "\n\nThe tip names in your table must be spelt exactly "
                       "as they are in the tree file. Names that do not match "
                       "are the most common problem at this stage.\n\n"
            + _import_clicks(name))

    if extras:
        add("check-match",
            "Check that your table matches the tree",
            "After you click **Check matches**, the **Match report:** says how "
            "many rows found their tip. If many did not, compare one name in "
            "your table with the same name in the tree. The usual causes are "
            "an underscore in one and a space in the other "
            "(Homo_sapiens against Homo sapiens), an extra space at the end of "
            "a name, or an ID number added to the front of it. Fix the table "
            "and import it again.")

    # ----------------------------------------------------------- 4. the figure
    mode, why_mode = recommend_layout(answers, measured)
    branch_mode, why_branch = _branch_mode(answers)
    add("layout",
        f"Use the {_MODE_UI[mode][0]} layout",
        f"{why_mode}\n\n{why_branch}\n\n{_layout_clicks(mode, branch_mode)}")

    if answers.get("label_tips") == "none":
        add("labels",
            "Hide the tip names",
            "With this many tips the names are too small to read, and they "
            "only make the figure look crowded. You can add back a few "
            "important ones by hand later.\n\n" + in_app(
                "Open the **Style** panel (**View > Style Panel**, Alt+2).",
                "In the **Labels** group, untick **Show tip labels**."))
    elif answers.get("label_tips") == "some":
        title_, detail, clicks = EXTRA_ADVICE["collapse"]
        add("labels", title_, detail + "\n\n" + in_app(*clicks))

    chosen_extras = wanted_extras(answers)
    for extra in chosen_extras:
        if extra == "guides" and extras:
            continue  # the align step below already covers it
        if extra == "collapse" and answers.get("label_tips") == "some":
            continue  # the labels step above already covers it
        title_, detail, clicks = EXTRA_ADVICE[extra]
        add(f"extra-{extra}", title_, detail + "\n\n" + in_app(*clicks))

    if len(chosen_extras) >= 5:
        add("extra-restraint",
            "Decide which of those to keep",
            "You picked most of the extras. That is a good way to see what the "
            "program can do, but a finished figure rarely needs them all: each "
            "one pulls the reader's eye away from the tree. Export once with "
            "everything, then take out whatever is not carrying an argument "
            "you are actually making.",
            optional=True)

    if extras:
        add("align",
            "Line up the tips with the data",
            "With data tracks, lining up the tips puts every tip level with "
            "its row of data. Without it, the tips end at different places "
            "and leave a jagged gap before the tracks. The gap is correct (the "
            "tips really are at different distances from the root), but "
            "readers often think it is a mistake.\n\n" + in_app(
                "Choose **View > Align Tips** (shortcut: A).",
                "Or open the **Style** panel and, in the **Layout** group, "
                "tick **Align tips**. Tick **Guide lines** as well to draw a "
                "dotted line from each branch to its name."))

    if answers.get("colour_safe") == "yes":
        add("colours",
            "Use colours that everyone can tell apart",
            "About 1 in 12 men cannot tell red from green, so avoid colour "
            "scales that run from red to green. MakeYourTree has colour sets "
            "(palettes) designed to be readable by everyone.\n\n" + in_app(
                "Choose **Annotate > Manage Tracks** (Ctrl+Shift+M) to open "
                "the **Tracks** panel, and click your track in the list.",
                "For a **Colour strip**, **Binary matrix** or **Symbols** "
                "track: click in the **palette** box, type okabe-ito and press "
                "Enter. Other safe names are tol-bright (6 colours) and "
                "tol-muted (9 colours). Empty means the default.",
                "For a **Heatmap** or **Gradient** track: click the colour "
                "buttons **color min**, **color mid** and **color max** and "
                "set them to #440154 (dark purple), #21918C (teal) and "
                "#FDE725 (yellow). This is the \"viridis\" scale, which "
                "everyone can read.",
                "If your numbers go below and above zero, use #2166AC (blue) "
                "for **color min**, #F7F7F7 (almost white) for **color mid** "
                "and #B2182B (red) for **color max**, and keep **use mid** "
                "ticked so zero sits in the middle."))

    # ------------------------------------------------------------- 5. export
    goal = answers.get("goal", "explore")
    fmt, flags, why_export = _DESTINATION.get(goal, _DESTINATION["explore"])
    track_flags = " ".join(f"--track {extra}.mytrack" for extra in extras)
    command = " ".join(filter(None, [
        "makeyourtree render", rooted_file, f"{output_stem}.{fmt}",
        f"--mode {mode}", f"--branch-mode {branch_mode}",
        "--align-tips" if extras else "",
        flags, track_flags,
    ]))
    export_clicks = [
        "Choose **File > Export Figure...** (Ctrl+E).",
        f"In the **Format:** drop-down, choose **{_FORMAT_LABEL[fmt]}**.",
        "Next to **File:**, click **Browse...** and choose where to save it "
        "and its name.",
        "**Size:** sets the width and height. Keep **Lock aspect ratio** "
        "ticked so the tree is not stretched. **Scale:** makes everything "
        "bigger or smaller together, and the **Output:** line shows the final "
        "size.",
    ]
    if fmt == "png":
        dpi = "300" if goal == "poster" else "150"
        export_clicks.append(
            f"In the **Scale:** row, set the box that ends in \"dpi\" to "
            f"{dpi}. A higher number gives a sharper but larger file.")
    export_clicks += [
        "In the **Background:** drop-down, choose **White** for a journal or "
        "a printed page, **Transparent** to place the figure on a coloured "
        "slide, or **Theme background** to keep what you see on screen.",
        "Leave **Include legend** ticked, then click **Export**.",
    ]
    add("render", f"Export the figure as {fmt.upper()}",
        why_export + "\n\n" + in_app(*export_clicks), command)

    if goal != "explore":
        add("caption",
            "Write the caption",
            "The picture alone cannot tell the reader these things, so write "
            "them in the caption: how the tree was rooted; what the branch "
            "lengths mean (or that it is a cladogram and they mean nothing); "
            "what kind of support values are shown -- bootstrap and posterior "
            "probability look the same but mean different things; and what "
            "each colour stands for.")

    add("save-project",
        "Save the project",
        "A MakeYourTree project (.mytree) keeps the tree, the layout, the "
        "colours and every track together. Months later you can reopen it and "
        "fix the figure instead of building it again from the start.\n\n"
        + in_app(
            "Choose **File > Save As...** (Ctrl+Shift+S).",
            "In the file-type list at the bottom of the save window, choose "
            "\"MakeYourTree project\", and check "
            "that the file name ends in .mytree. This matters: if the name "
            "still ends in .nwk, only the bare tree is saved and your tracks "
            "and settings are left out.",
            "Next time, open it with **File > Open Project...** "
            "(Ctrl+Shift+O)."),
        optional=True)

    plan = Plan(title=title or f"{output_stem}: a MakeYourTree plan",
                steps=steps,
                answers=answers,
                observations=list(observations) + answered_summary(answers))
    return plan
