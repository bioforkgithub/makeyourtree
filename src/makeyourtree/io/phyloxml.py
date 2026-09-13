# SPDX-License-Identifier: MIT
"""phyloXML 1.20 reading and writing.

The schema is Zmasek & Han, "phyloXML: XML for evolutionary biology and
comparative genomics", BMC Bioinformatics 10:356 (2009), version 1.20 of
``phyloxml.xsd``.  Unlike Newick, phyloXML has a dedicated slot for everything a
viewer needs -- ``<name>`` and ``<confidence>`` are separate elements, so the
support-versus-clade-name ambiguity that dominates the Newick reader simply does
not arise here.

Security
--------
Tree files arrive from collaborators, web forms and mailing lists, so this
reader treats XML as hostile input.  Parsing goes through a raw expat parser
with:

* ``EntityDeclHandler`` and ``UnparsedEntityDeclHandler`` raising, which kills
  the "billion laughs" entity-expansion bomb at the declaration -- the standard
  library's ``ElementTree`` expands internal entities happily and would not;
* ``ExternalEntityRefHandler`` refusing, and parameter-entity parsing switched
  off, so no XXE can reach the filesystem or the network;
* a hard element-nesting cap, so a pathological document cannot exhaust memory
  through depth alone.

Nothing is ever fetched at runtime -- not the schema, not a namespace URL.
``phyloxml.org`` has in any case lapsed, so the namespace is matched, never
resolved, and a document that omits or misspells it is still read by matching
local element names.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from typing import Any, Iterable

from ..core.diagnostics import DiagnosticSink
from ..core.errors import ParseError
from ..core.node import Node
from ..core.tree import Tree
from ..style.color import Color
from .newick import _coerce

__all__ = ["read_phyloxml", "write_phyloxml", "PHYLOXML_NS"]

PHYLOXML_NS = "http://www.phyloxml.org"
_NS_SEP = "|"
_MAX_DEPTH = 5000
_PROPERTY_PREFIX = "makeyourtree:"

# xs:sequence is strict: a document whose children are out of order fails
# validation even though most readers tolerate it.  These are the orders from
# the 1.20 schema.
_CLADE_ORDER = ("name", "branch_length", "confidence", "width", "color",
                "taxonomy", "sequence", "events", "binary_characters",
                "distribution", "date", "reference", "property", "clade")
_PHYLOGENY_ORDER = ("name", "id", "description", "date", "confidence", "clade",
                    "clade_relation", "sequence_relation", "property")

_TAXONOMY_FIELDS = ("id", "code", "scientific_name", "authority", "common_name",
                    "synonym", "rank")
_SEQUENCE_FIELDS = ("symbol", "accession", "name", "gene_name", "location",
                    "mol_seq")


# ------------------------------------------------------------------ security


def _local(tag: str) -> str:
    """Local element name, whatever namespace the document did or did not use."""
    return tag.rsplit(_NS_SEP, 1)[-1]


def _parse_secure(text: str) -> ET.Element:
    """Parse *text* into an element tree with entity expansion disabled.

    Uses expat directly because ``ElementTree.XMLParser`` does not expose its
    underlying parser, and therefore offers no way to refuse an entity
    declaration.
    """
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate(encoding="utf-8", namespace_separator=_NS_SEP)
    depth = 0

    def _start(tag: str, attrib: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > _MAX_DEPTH:
            raise ParseError(f"XML nesting deeper than {_MAX_DEPTH} elements")
        builder.start(tag, attrib)

    def _end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        builder.end(tag)

    def _refuse_entity(*_args: Any) -> None:
        raise ParseError("XML entity declarations are refused for safety")

    parser.StartElementHandler = _start
    parser.EndElementHandler = _end
    parser.CharacterDataHandler = builder.data
    parser.EntityDeclHandler = _refuse_entity
    parser.UnparsedEntityDeclHandler = _refuse_entity
    parser.ExternalEntityRefHandler = lambda *_a: 0
    try:
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    except (AttributeError, expat.ExpatError):  # pragma: no cover - platform
        pass
    parser.buffer_text = True
    try:
        parser.Parse(text.encode("utf-8"), True)
    except expat.ExpatError as exc:
        raise ParseError(f"malformed XML: {exc}",
                         line=exc.lineno, col=exc.offset) from None
    return builder.close()


# ------------------------------------------------------------------ reading


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _first(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


_PROPERTY_CASTS = {
    "xsd:integer": int, "xsd:int": int, "xsd:long": int, "xsd:short": int,
    "xsd:byte": int, "xsd:nonNegativeInteger": int, "xsd:positiveInteger": int,
    "xsd:negativeInteger": int, "xsd:nonPositiveInteger": int,
    "xsd:unsignedInt": int, "xsd:unsignedLong": int, "xsd:unsignedShort": int,
    "xsd:unsignedByte": int,
    "xsd:double": float, "xsd:float": float, "xsd:decimal": float,
}


def _property_value(el: ET.Element) -> Any:
    """``<property>`` is mixed content, so the value needs trimming first."""
    raw = (el.text or "").strip()
    datatype = el.get("datatype", "xsd:string")
    if datatype == "xsd:boolean":
        return raw.lower() in ("true", "1")
    cast = _PROPERTY_CASTS.get(datatype)
    if cast is not None:
        try:
            return cast(raw)
        except ValueError:
            return raw
    return raw


def _read_clade(el: ET.Element, node: Node, sink: DiagnosticSink) -> None:
    """Map one ``<clade>`` element onto a node, ignoring what we cannot use."""
    node.name = _text(_first(el, "name"))

    length_el = _number(_text(_first(el, "branch_length")))
    length_attr = _number(el.get("branch_length"))
    if length_el is not None and length_attr is not None and length_el != length_attr:
        sink.warn("phyloxml.duplicate-branch-length",
                  "clade has both a branch_length element and attribute; "
                  "used the element")
    node.branch_length = length_el if length_el is not None else length_attr

    for conf in _children(el, "confidence"):
        value = _number(_text(conf))
        if value is None:
            continue
        kind = conf.get("type")
        if kind is None:
            sink.warn("phyloxml.confidence-without-type",
                      "confidence element has no required type attribute")
            kind = "unknown"
        if node.support is None:
            node.support = value
            node.attrs["confidence_type"] = kind
        else:
            node.attrs[f"confidence:{kind}"] = value

    width = _number(_text(_first(el, "width")))
    if width is not None:
        node.set_style(branch_width=width)
    color_el = _first(el, "color")
    if color_el is not None:
        rgb = [_number(_text(_first(color_el, c))) for c in ("red", "green", "blue")]
        if all(v is not None for v in rgb):
            alpha = _number(_text(_first(color_el, "alpha")))
            node.set_style(branch_color=Color(int(rgb[0]), int(rgb[1]), int(rgb[2]),
                                              255 if alpha is None else int(alpha)))

    tax = _first(el, "taxonomy")
    if tax is not None:
        for field in _TAXONOMY_FIELDS:
            value = _text(_first(tax, field))
            if value is not None:
                node.attrs["taxonomy_" + field] = value
    seq = _first(el, "sequence")
    if seq is not None:
        for field in _SEQUENCE_FIELDS:
            value = _text(_first(seq, field))
            if value is not None:
                node.attrs["sequence_" + field] = value
        if seq.get("type"):
            node.attrs["sequence_type"] = seq.get("type")

    events = _first(el, "events")
    if events is not None:
        for field in ("type", "duplications", "speciations", "losses"):
            value = _text(_first(events, field))
            if value is not None:
                node.attrs["event_" + field] = value

    for prop in _children(el, "property"):
        ref = prop.get("ref") or "property"
        ours = ref.startswith(_PROPERTY_PREFIX)
        key = ref[len(_PROPERTY_PREFIX):] if ours else ref
        value = _property_value(prop)
        if ours and isinstance(value, str) and value.startswith("{") \
                and value.endswith("}"):
            value = _coerce(value)
        node.attrs[key] = value

    if el.get("collapse", "").lower() in ("true", "1"):
        node.collapsed = True
    if el.get("id_source"):
        node.attrs.setdefault("id_source", el.get("id_source"))


def _read_phylogeny(el: ET.Element, sink: DiagnosticSink) -> Tree | None:
    root_el = _first(el, "clade")
    if root_el is None:
        sink.warn("phyloxml.empty-phylogeny", "phylogeny element has no clade")
        return None
    root = Node()
    # Explicit stack: a phyloXML document can be as deep as any other tree.
    work: list[tuple[ET.Element, Node]] = [(root_el, root)]
    while work:
        cur_el, cur_node = work.pop()
        _read_clade(cur_el, cur_node, sink)
        for child_el in _children(cur_el, "clade"):
            child = Node()
            cur_node.add_child(child)
            work.append((child_el, child))

    rooted_attr = el.get("rooted")
    if rooted_attr is None:
        sink.warn("phyloxml.missing-rooted",
                  "phylogeny is missing the required 'rooted' attribute; "
                  "assumed rooted")
    rooted = rooted_attr is None or rooted_attr.strip().lower() in ("true", "1")
    tree = Tree(root, name=_text(_first(el, "name")), rooted=rooted)
    description = _text(_first(el, "description"))
    if description:
        tree.metadata["description"] = description
    if el.get("branch_length_unit"):
        tree.metadata["branch_length_unit"] = el.get("branch_length_unit")
    if el.get("rerootable") is not None:
        tree.metadata["rerootable"] = el.get("rerootable").lower() in ("true", "1")
    for prop in _children(el, "property"):
        ref = prop.get("ref") or "property"
        key = ref[len(_PROPERTY_PREFIX):] if ref.startswith(_PROPERTY_PREFIX) else ref
        tree.metadata[key] = _property_value(prop)
    tree.refresh()
    return tree


def read_phyloxml(text: str, *, sink: DiagnosticSink | None = None,
                  **_ignored: Any) -> list[Tree]:
    """Read every ``<phylogeny>`` in a phyloXML document.

    phyloXML is natively a multi-tree format, so this always returns a list.
    A missing or misspelled namespace is tolerated: elements are matched on
    their local names.
    """
    sink = sink if sink is not None else DiagnosticSink()
    root = _parse_secure(text)
    if _local(root.tag) != "phyloxml":
        sink.warn("phyloxml.unexpected-root",
                  f"document root is <{_local(root.tag)}>, not <phyloxml>")
    if PHYLOXML_NS not in root.tag:
        sink.warn("phyloxml.namespace",
                  "document does not use the phyloXML namespace; "
                  "matched elements by local name")
    trees: list[Tree] = []
    for el in root.iter():
        if _local(el.tag) != "phylogeny":
            continue
        tree = _read_phylogeny(el, sink)
        if tree is not None:
            trees.append(tree)
    if not trees:
        raise ParseError("no <phylogeny> element found in phyloXML input")
    return trees


# ------------------------------------------------------------------ writing


def _sub(parent: ET.Element, name: str, text: str | None = None,
         **attrib: str) -> ET.Element:
    """Add a child element.

    Tags are plain local names; the namespace is declared once, as an ``xmlns``
    attribute on the root, which keeps the serialiser free of prefix mapping.
    """
    el = ET.SubElement(parent, name, attrib)
    if text is not None:
        el.text = text
    return el


def _escape_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(s: str) -> str:
    return _escape_text(s).replace('"', "&quot;")


def _serialise(root: ET.Element, indent: str) -> str:
    """Write an element tree out with an explicit stack.

    ``ElementTree``'s own serialiser and its ``indent`` helper each recurse once
    per level, so a 2000-deep phylogeny raises ``RecursionError`` before it ever
    reaches a file.  This does the same job iteratively.
    """
    out: list[str] = []
    stack: list[list[Any]] = [[root, 0, -1]]
    while stack:
        frame = stack[-1]
        el, depth, i = frame[0], frame[1], frame[2]
        pad = indent * depth
        if i < 0:
            out.append(pad + "<" + el.tag)
            for key, value in el.attrib.items():
                out.append(f' {key}="{_escape_attr(str(value))}"')
            body = (el.text or "").strip()
            if not len(el) and not body:
                out.append("/>" + "\n")
                stack.pop()
                continue
            out.append(">")
            if not len(el):
                out.append(_escape_text(body) + "</" + el.tag + ">" + "\n")
                stack.pop()
                continue
            out.append("\n")
            frame[2] = 0
            continue
        if i < len(el):
            frame[2] = i + 1
            stack.append([el[i], depth + 1, -1])
            continue
        out.append(pad + "</" + el.tag + ">" + "\n")
        stack.pop()
    return "".join(out)


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) and abs(v) < 1e16 else repr(v)


def _write_clade_body(el: ET.Element, node: Node, *, lengths: bool = True,
                      support: bool = True) -> None:
    """Emit a clade's own children in schema order, minus the sub-clades."""
    if node.name:
        _sub(el, "name", node.name)
    if lengths and node.branch_length is not None:
        _sub(el, "branch_length", _fmt(node.branch_length))
    if support and node.support is not None:
        _sub(el, "confidence", _fmt(node.support),
             type=str(node.attrs.get("confidence_type", "bootstrap")))
    style = node.style or {}
    width = style.get("branch_width")
    if width is not None:
        _sub(el, "width", _fmt(float(width)))
    color = style.get("branch_color")
    if isinstance(color, Color):
        color_el = _sub(el, "color")
        _sub(color_el, "red", str(color.r))
        _sub(color_el, "green", str(color.g))
        _sub(color_el, "blue", str(color.b))
        if color.a != 255:
            _sub(color_el, "alpha", str(color.a))

    taxonomy = {f: node.attrs["taxonomy_" + f] for f in _TAXONOMY_FIELDS
                if "taxonomy_" + f in node.attrs}
    if taxonomy:
        tax_el = _sub(el, "taxonomy")
        for field in _TAXONOMY_FIELDS:
            if field in taxonomy:
                _sub(tax_el, field, str(taxonomy[field]))
    sequence = {f: node.attrs["sequence_" + f] for f in _SEQUENCE_FIELDS
                if "sequence_" + f in node.attrs}
    if sequence:
        seq_attrib = {}
        if "sequence_type" in node.attrs:
            seq_attrib["type"] = str(node.attrs["sequence_type"])
        seq_el = _sub(el, "sequence", **seq_attrib)
        for field in _SEQUENCE_FIELDS:
            if field in sequence:
                _sub(seq_el, field, str(sequence[field]))

    skip = {"confidence_type", "sequence_type", "id_source"}
    skip.update("taxonomy_" + f for f in _TAXONOMY_FIELDS)
    skip.update("sequence_" + f for f in _SEQUENCE_FIELDS)
    for key, value in node.attrs.items():
        if key in skip or key.startswith("_") or key.startswith("confidence:"):
            continue
        if isinstance(value, bool):
            datatype, raw = "xsd:boolean", "true" if value else "false"
        elif isinstance(value, int):
            datatype, raw = "xsd:integer", str(value)
        elif isinstance(value, float):
            datatype, raw = "xsd:double", _fmt(value)
        elif isinstance(value, (tuple, list)):
            # The schema has no list datatype, so a list value keeps the brace
            # form it arrived in from a BEAST metacomment.  Only properties in
            # our own ref namespace are read back that way, so no foreign string
            # can be turned into a list by accident.
            datatype = "xsd:string"
            raw = "{" + ",".join(str(x) for x in value) + "}"
        else:
            datatype, raw = "xsd:string", str(value)
        _sub(el, "property", raw, ref=_PROPERTY_PREFIX + str(key),
             datatype=datatype, applies_to="clade")


def _write_clade(parent: ET.Element, root: Node, *, lengths: bool = True,
                 support: bool = True) -> None:
    """Build the clade subtree with an explicit stack, deepest tree tolerated."""
    root_el = _sub(parent, "clade")
    stack: list[tuple[Node, ET.Element]] = [(root, root_el)]
    while stack:
        node, el = stack.pop()
        if node.collapsed:
            el.set("collapse", "true")
        _write_clade_body(el, node, lengths=lengths, support=support)
        # Elements are created in child order and pushed in reverse, so the
        # document keeps the tree's ordering whatever order the stack drains in.
        pairs = [(child, _sub(el, "clade")) for child in node.children]
        stack.extend(reversed(pairs))


def write_phyloxml(trees: Tree | Iterable[Tree], *, indent: str = "  ",
                   lengths: bool = True, support: bool = True) -> str:
    """Serialise trees as a namespaced phyloXML 1.20 document.

    Children are emitted in the order ``xs:sequence`` demands, ``rooted`` is
    always written because the schema requires it, and the branch length goes in
    the element rather than the attribute -- both forms are legal, but writing
    both is explicitly discouraged and the element is the portable one.

    *lengths* and *support* exist so the three writers share one vocabulary.
    :func:`~makeyourtree.io.writer.write_tree` forwards its keywords verbatim, so
    without them ``save_tree(t, path, format="phyloxml", support=False)`` --
    which is valid for Newick and NEXUS -- raised ``TypeError`` instead of
    doing the obvious thing.  Suppressing either drops the corresponding
    element; nothing else about the document changes.
    """
    items = [trees] if isinstance(trees, Tree) else list(trees)
    root = ET.Element("phyloxml", {"xmlns": PHYLOXML_NS})
    for tree in items:
        phy = _sub(root, "phylogeny", rooted="true" if tree.rooted else "false")
        if tree.name:
            _sub(phy, "name", tree.name)
        description = tree.metadata.get("description")
        if description:
            _sub(phy, "description", str(description))
        unit = tree.metadata.get("branch_length_unit")
        if unit:
            phy.set("branch_length_unit", str(unit))
        _write_clade(phy, tree.root, lengths=lengths, support=support)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + _serialise(root, indent)
