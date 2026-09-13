# Clean-room record

MakeYourTree is an **independent implementation**. It is not affiliated with, endorsed by, or
derived from any other phylogenetics package. No code, markup, styling, help text, icon,
template file or example dataset from any other tree-visualisation product has been read,
copied, adapted, decompiled or reproduced in this repository.

This document records how that was ensured, so the claim is auditable rather than merely
asserted.

## 1. What the law actually protects

Reimplementation is lawful; copying expression is not. The distinction matters and it is
settled:

- **Functionality and file formats are not copyrightable.** *SAS Institute Inc. v. World
  Programming Ltd.*, 64 F.4th 1319 (Fed. Cir. 2023) rejected a claim to input formats
  under abstraction–filtration–comparison. CJEU Case C-406/10 *SAS Institute v. World
  Programming* holds expressly that "neither the functionality of a computer program nor
  the programming language and the format of data files … constitute a form of expression".
- **Statutory basis:** 17 U.S.C. §102(b) (ideas, procedures, methods of operation);
  Art. 1(2) of EU Directive 2009/24/EC.
- **Command sets and interfaces are methods of operation.** *Lotus Development Corp. v.
  Borland Int'l*, 49 F.3d 807 (1st Cir. 1995), aff'd by an equally divided Court.
- **Interoperability copying is favoured.** *Google LLC v. Oracle America*, 593 U.S. 1
  (2021); *Sega Enterprises v. Accolade*, 977 F.2d 1510 (9th Cir. 1992).

What is protected, and what we therefore avoid entirely: source code, help and
documentation prose, icons and other artwork, logos and product names, bundled example
datasets (copyright, plus the EU *sui generis* database right, Directive 96/9/EC), and the
distinctive visual skin of a user interface.

Clean-room design is a defence to **copyright only**. It is no defence to patents
(independent invention is irrelevant) and none to trademark.

## 2. Specification inputs

MakeYourTree was built from published specifications and from first-principles derivation.
Permitted inputs, all recorded in `PROVENANCE.md`:

1. Published open format specifications: Newick (Olsen, *Newick's 8:45*), NHX v2.0,
   NEXUS (Maddison, Swofford & Maddison 1997, *Syst. Biol.* 46:590), phyloXML 1.20 and its
   XSD, RFC 4180, W3C SVG 1.1, ISO/IEC 15948 (PNG), ISO 32000 (PDF).
2. Peer-reviewed literature on tree layout, cited in the module that implements each
   algorithm — notably Felsenstein's equal-angle and equal-daylight methods
   (*Inferring Phylogenies*, 2004, pp. 582–584) and Heckbert's nice-number axis labelling
   (*Graphics Gems*, 1990).
3. Textbook and first-principles derivation of the remaining geometry.
4. Open-source tools under known licenses, consulted for **format semantics only**.

## 3. Excluded inputs

Categorically excluded, with no exceptions:

- Any other product's served JavaScript, CSS, HTML or compiled binaries — not viewed, not
  saved, not beautified, not debugged.
- Any other product's help pages, tooltips, version history or error strings — not copied,
  not paraphrased, not structurally imitated.
- Any other product's downloadable annotation template files or their keyword vocabulary.
- Any other product's bundled example trees or demo datasets.
- Screenshots or screen recordings of another product's UI, in the repository, in issues,
  in design tools, or in prompts to a language model.
- Decompilation, deobfuscation or bundle unpacking of anything.

## 4. Divergence by design

Where a functional constraint forces similarity, that constraint is named in the relevant
module docstring. Where there is a free choice, MakeYourTree chooses differently:

- **Name.** *MakeYourTree* (clade + cadence) is a coined mark. It was screened against
  existing phylogenetics software and deliberately avoids the crowded families —
  `Phylo*`, `Dendro*`, `Tree*`, `Arbor*`, `*scope` — and evokes no existing product.
- **Annotation format.** `.mytrack` is our own sectioned INI-style design with our own
  keyword vocabulary, specified in `src/makeyourtree/annot/table.py`. It is not a
  reimplementation of anyone's directive language.
- **Project format.** `.mytree` is our own ZIP container.
- **Architecture.** The band-space projector, the two-phase `measure`/`draw` track
  protocol, the flat-array `LayoutFrame` and the shared `Scene` display list are our own
  design decisions, made for testability and for 100k-leaf performance.
- **Visual identity.** Our own palette (Okabe–Ito default), typography, panel arrangement
  and iconography, using only permissively licensed assets.

## 5. Fixtures

Every test fixture is either generated programmatically by the test suite or taken from an
openly licensed source recorded in `FIXTURES.md`. No fixture was downloaded from any
tree-visualisation product's website.

## 6. Attribution

Prior art in this field is cited in `README.md` as scholarly good practice. Citing prior
art is evidence of good faith; it is not an admission of copying.

---

## 7. Indian law — the position is, if anything, stronger

Indian copyright law bears directly on the clean-room posture, and it supports this
implementation on two independent grounds.

**7.1 Ideas, methods and functionality are not protected.**
The Copyright Act, 1957 protects a computer programme as a literary work
(§2(o), §2(ffc)), but protection extends to expression, not to the idea, method or
functional behaviour expressed. India follows the idea/expression dichotomy, and Indian
courts have applied it to software.

**7.2 Interoperability is expressly permitted — by statute, not merely by case law.**
This is a notable advantage over jurisdictions where the point rests on judicial
interpretation. Section 52(1) lists acts that are **not** infringement, including:

- **§52(1)(ab)** — "the doing of any act necessary to obtain information essential for
  operating inter-operability of an independently created computer programme with other
  programmes by a lawful possessor of a computer programme";
- **§52(1)(ac)** — "the observation, study or test of functioning of the computer programme
  in order to determine the ideas and principles which underline any elements of the
  programme while performing such acts necessary for the functions for which the computer
  programme was supplied".

Reading a **published file-format specification** and implementing a reader for it does not
even reach these provisions — it never touches protected expression in the first place. The
provisions matter because they show the Indian legislature deliberately carved out
interoperability and functional study, which is precisely the activity MakeYourTree engages in.

Note the statutory wording "by a lawful possessor". MakeYourTree relies on published
specifications and primary literature rather than on possession of anyone's binary, so the
qualifier is not load-bearing here — but it is another reason the standing rules forbid
obtaining, unpacking or decompiling any competitor's software.

**7.3 What Indian law does not change.**
- Trademark risk is governed by the Trade Marks Act, 1999 and is unaffected by any of the above.
- Patent risk is unaffected; independent creation is no defence. Note that in India,
  computer programmes "per se" are excluded from patentability under §3(k) of the Patents
  Act, 1970, which narrows — but does not eliminate — the software-patent surface.
- Copying expression remains infringement. The standing clean-room rules recorded in
  this file continue to apply without modification. Publishing MakeYourTree under MIT
  changes nothing here: releasing our own work freely grants us no licence over anyone
  else's, so the rules bind exactly as they did when the project was commercial.
