# SPDX-License-Identifier: MIT
"""Turn answers into an ordered list of things to do.

The output is deliberately concrete.  A plan that says "consider an appropriate
layout" helps nobody; a plan that says "use a circular fan, because 400 tips do
not fit legibly on a page as a rectangle" and then hands over the exact command
is the difference between advice and help.  So every step that *can* carry a
command carries one, spelled with the user's own file names where they are
known.

Recommendations are stated with their reason attached.  The user is entitled to
disagree -- they know their data -- and cannot judge the advice without knowing
what it rests on.

The functions here are pure: answers and observations in, a :class:`Plan` out.
That is what lets the same engine serve the command line, the desktop wizard and
the tests without any of them re-deriving the logic.
"""

from __future__ import annotations

from typing import Any, Iterable

from .plan import Plan, Step
from .questions import answered_summary, wanted_extras

__all__ = ["build_plan", "recommend_layout", "TRACK_ADVICE"]

#: What each kind of extra data becomes: a track type, and what to put in the
#: annotation file. Keyed by the ``extra_data`` choices in the questionnaire.
TRACK_ADVICE: dict[str, tuple[str, str]] = {
    "category": (
        "color-strip",
        "One column holding the category for each tip, for example the host "
        "species or the sampling region."),
    "value": (
        "bar-chart",
        "One numeric column. Use a gradient track instead if you are short of "
        "width and only need the pattern rather than the magnitudes."),
    "matrix": (
        "heatmap",
        "One column per condition or sample. If the values have a meaningful "
        "zero, such as log fold change, use a diverging colour ramp so the "
        "sign is visible."),
    "presence": (
        "binary-matrix",
        "One column per feature, with 1 for present, 0 for absent and an empty "
        "field for unknown. Do not write unknown as 0: they are different "
        "claims and the track draws them differently."),
    "composition": (
        "pie-chart",
        "One column per component. They need not sum to 1; the track "
        "normalises."),
    "series": (
        "line-chart",
        "One column per time point. Set an explicit value range if you want to "
        "compare tips against each other."),
    "domains": (
        "domain-architecture",
        "A length column, then one column per feature formatted "
        "start|end|shape|colour|label."),
    "links": (
        "connections",
        "One row per relationship, giving two tip names and optionally a "
        "weight, a colour and a label."),
    "highlight": (
        "clade-range",
        "Rows keyed by internal nodes rather than tips, each with a colour and "
        "a label. Set match = all in the [track] section."),
}

#: Presentation extras, and what each one costs or is worth saying about.
#: Separate from TRACK_ADVICE because these are not data: they are decisions
#: about how the same data is presented.
EXTRA_ADVICE: dict[str, tuple[str, str]] = {
    "support": (
        "Show branch support values",
        "Say in the caption what they are. Bootstrap percentages and Bayesian "
        "posterior probabilities look identical on a figure and mean quite "
        "different things, and a reader cannot tell them apart. Consider "
        "hiding values below your threshold rather than printing all of them."),
    "scale_bar": (
        "Show a scale bar",
        "It is what tells a reader whether a branch length is one substitution "
        "per site or one million years. A phylogram without one is decorative."),
    "collapse": (
        "Collapse the clades you are not discussing",
        "Select a clade and press C. The triangle is sized by what it stands "
        "for, so the figure still shows how much was folded away."),
    "guides": (
        "Turn on aligned tips and guide lines",
        "Dotted leaders from each tip across to its label and its data. This "
        "is what makes a wide figure readable across the page."),
    "symbols": (
        "Add node symbols",
        "A symbols track can mark particular nodes, sized or coloured by a "
        "value. Size encodes area rather than radius by default, which is the "
        "correct choice: a radius-linear encoding exaggerates large values by "
        "roughly the square."),
    "legend": (
        "Check every track has a legend",
        "Set show = true in the [legend] section of each annotation file. An "
        "unlabelled colour is decoration, not data."),
    "dark": (
        "Switch to the dark theme",
        "Ctrl+T. The background travels with the figure, so the export is dark "
        "too. Check your journal accepts it -- most want a white background."),
}


#: Destination to (format, extra render flags, prose).
_DESTINATION: dict[str, tuple[str, str, str]] = {
    "paper": ("pdf", "--page column",
              "Vector PDF at single-column width. Journals accept vector and "
              "it stays sharp at any size; check the guidelines for the "
              "column width they actually want."),
    "thesis": ("pdf", "--width 160mm",
               "Vector PDF sized to a typical thesis text width."),
    "talk": ("png", "--dpi 150 --width 250mm",
             "PNG at screen resolution. Slides do not need print DPI, and a "
             "smaller file loads faster."),
    "poster": ("png", "--dpi 300 --width 400mm",
               "Large, high-resolution PNG. Use PDF instead if your printer "
               "accepts vector, which most do."),
    "explore": ("svg", "",
                "SVG for a quick look. Nothing here is final."),
}


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
            return shape, ("Measured from the figure you provided, not chosen "
                           "by you. Change it if your data wants otherwise.")
        return shape, "You asked for this shape."
    if answers.get("rooting") == "unrooted":
        return ("unrooted",
                "You asked to show the tree unrooted, so the layout must make "
                "no claim about which node is ancestral.")

    size = answers.get("tip_count")
    if size == "thousands":
        return ("circular",
                "With more than a thousand tips, a rectangle becomes a very "
                "tall strip. A circular fan uses both dimensions and keeps the "
                "figure on one page.")
    if size == "hundreds":
        extras = answers.get("extra_data") or []
        many = len([e for e in extras if e != "none"]) >= 2
        if many:
            return ("circular",
                    "A few hundred tips with several data tracks: a circular "
                    "layout turns the tracks into rings, which is far more "
                    "compact than stacking them beside a tall rectangle.")
        return ("rectangular",
                "A few hundred tips still read well as a rectangle, and a "
                "rectangle is easier for a reader to follow than a fan.")
    return ("rectangular",
            "For a small tree a rectangle is the clearest choice, and it is "
            "what most readers expect.")


def _branch_mode(answers: dict[str, Any]) -> tuple[str, str]:
    meaning = answers.get("branch_meaning")
    if meaning in {"meaningless", "absent"}:
        return ("cladogram-aligned",
                "Your branch lengths do not carry information, so drawing them "
                "to scale would imply a precision you do not have.")
    if meaning == "unsure":
        return ("phylogram",
                "Assuming they are meaningful. The step above tells you how to "
                "check; switch to a cladogram if they are not.")
    return ("phylogram", "Your branch lengths are meaningful, so draw them to "
                         "scale.")


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
    add("inspect",
        "Look at what is actually in your tree file",
        "Before deciding anything, find out how many tips there are, whether "
        "the tree is rooted, and whether it carries branch lengths and support "
        "values. This also reports anything the parser had to interpret.",
        f"makeyourtree info {tree_file}")

    if answers.get("tip_count") == "unknown":
        steps[-1].detail += (
            " You said you did not know the size; the 'leaves' line answers "
            "that, and the layout advice below assumes it is small until you "
            "know otherwise.")

    if answers.get("branch_meaning") == "unsure":
        add("check-lengths",
            "Decide whether your branch lengths mean anything",
            "The 'branch lengths' and 'max root-to-tip' lines from the previous "
            "step tell you whether they exist and what scale they are on. If "
            "they came from a tree builder they are usually substitutions per "
            "site. If they are all equal, or all 1, they carry no information "
            "and you want a cladogram.")

    # -------------------------------------------------------- 2. root the tree
    rooting = answers.get("rooting")
    if rooting == "outgroup":
        add("root",
            "Root the tree on your outgroup",
            "Replace OUTGROUP with the taxon name, or several separated by "
            "commas. Outgroup rooting is preferable to midpoint because it "
            "states a hypothesis rather than assuming equal rates.",
            f"makeyourtree reroot {tree_file} rooted.nwk --outgroup OUTGROUP")
    elif rooting == "midpoint":
        add("root",
            "Root the tree at its midpoint",
            "Midpoint rooting assumes roughly constant rates across the tree. "
            "It is a reasonable default with no outgroup and a poor one when "
            "rates vary between lineages -- say which you used in the caption.",
            f"makeyourtree reroot {tree_file} rooted.nwk --midpoint")
    elif rooting == "unsure":
        add("root",
            "Decide where the root goes",
            "This is the choice most likely to change what a reader concludes, "
            "because it decides which groups appear monophyletic. If you have "
            "any outgroup, use it. If not, midpoint rooting is defensible as "
            "long as you say so.",
            f"makeyourtree reroot {tree_file} rooted.nwk --midpoint",
            optional=True)

    rooted_file = "rooted.nwk" if rooting in {"outgroup", "midpoint", "unsure"} else tree_file

    # ------------------------------------------------------ 3. annotation data
    for extra in extras:
        track_type, guidance = TRACK_ADVICE.get(extra, ("color-strip", ""))
        add(f"data-{extra}",
            f"Prepare the {track_type.replace('-', ' ')} data",
            guidance + " Save it as a .mytrack file, or keep it as a "
                       "spreadsheet and import it with Annotate > Import "
                       "Annotations, which shows how many rows matched before "
                       "anything is added.\n\n"
                       "The keys in the first column must match your tip names "
                       "exactly. Mismatched names are the single most common "
                       "problem at this stage.")

    if extras:
        add("check-match",
            "Check that your annotation matches the tree",
            "Import the file and read the match report before going further. "
            "Underscores against spaces, trailing whitespace and accession "
            "prefixes are the usual causes of rows that match nothing.")

    # ----------------------------------------------------------- 4. the figure
    mode, why_mode = recommend_layout(answers, measured)
    branch_mode, why_branch = _branch_mode(answers)
    add("layout",
        f"Use a {mode} layout",
        f"{why_mode}\n\n{why_branch}")

    if answers.get("label_tips") == "none":
        add("labels",
            "Turn the tip labels off",
            "At this size individual names cannot be read, and leaving them on "
            "makes the figure look busy without adding information. Label a "
            "handful by hand afterwards if specific tips matter.")
    elif answers.get("label_tips") == "some":
        add("labels",
            "Collapse the clades you are not discussing",
            "Select a clade and press C to collapse it. A collapsed clade is "
            "drawn as a triangle sized by what it stands for, so the figure "
            "still shows how much was folded away.")

    chosen_extras = wanted_extras(answers)
    for extra in chosen_extras:
        if extra == "guides" and extras:
            continue  # the align step below already covers it
        title_, detail = EXTRA_ADVICE[extra]
        add(f"extra-{extra}", title_, detail)

    if len(chosen_extras) >= 5:
        add("extra-restraint",
            "Decide which of those to keep",
            "You asked for most of the extras at once, which is a good way to "
            "see what the tool can do and a poor way to finish a figure. Every "
            "one of them competes for the reader's attention with the tree "
            "itself. Render it with all of them, then take out whatever is not "
            "carrying an argument you are actually making.",
            optional=True)

    if extras:
        add("align",
            "Align the tips",
            "With annotation tracks attached, aligning the tips makes each row "
            "line up with its track cells. Without it, a circular phylogram "
            "leaves a ragged gap -- which is correct, because tips sit at "
            "different distances from the root, but it reads as a mistake.")

    if answers.get("colour_safe") == "yes":
        add("colours",
            "Use a colour-vision-safe palette",
            "The built-in Paul Tol and Okabe-Ito palettes are designed for "
            "this, as is viridis for continuous data. Avoid a red-to-green "
            "ramp: it is the one that fails most often, and about 1 in 12 men "
            "cannot read it.")

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
    add("render", f"Render the figure as {fmt.upper()}", why_export, command)

    if goal != "explore":
        add("caption",
            "Write the caption",
            "State how the tree was rooted, what the branch lengths mean (or "
            "that the figure is a cladogram and they do not), what any support "
            "values are -- bootstrap and posterior probability look identical "
            "and mean different things -- and what each colour encodes. A "
            "reader cannot recover any of this from the picture.")

    add("save-project",
        "Save the project",
        "A .mytree project keeps the tree, the layout, the theme and every "
        "track together, so the figure can be regenerated or corrected months "
        "later without rebuilding it from parts.",
        optional=True)

    plan = Plan(title=title or f"{output_stem}: a MakeYourTree plan",
                steps=steps,
                answers=answers,
                observations=list(observations) + answered_summary(answers))
    return plan
