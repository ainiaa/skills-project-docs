"""Checks for uncompressed draw.io source; raster review remains a separate gate."""

import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("geometry must be finite")
    return number


def _style(value):
    return dict(part.split("=", 1) for part in value.split(";") if "=" in part)


def _unmeasured_label(style):
    return style.get("placeholders") == "1" or style.get("overflow") == "visible" or any(
        key in style for key in ("textRotation", "labelPosition", "verticalLabelPosition", "labelWidth", "horizontal"))


class _Text(HTMLParser):
    def __init__(self, size, html=False):
        super().__init__()
        self.stack = [size]
        self.lines = [[]]
        self.unsupported = False
        self.html = html
        self.margin = 0

    def handle_starttag(self, tag, attrs):
        if tag not in {"div", "p", "br", "span", "b", "strong", "i", "em", "u"}:
            self.unsupported = True
        attrs = dict(attrs)
        css = dict((key.strip().lower(), value.strip()) for part in (attrs.get("style") or "").split(";")
                   if ":" in part for key, value in [part.split(":", 1)])
        if (tag == "p" or attrs.get("class") or any(key not in {
                "font-size", "font-weight", "font-style", "font-family", "color",
                "background-color", "text-decoration", "margin-top"} for key in css)):
            self.unsupported = True
        for key in ("font-size", "margin-top"):
            if key in css and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?px", css[key]):
                self.unsupported = True
        if tag == "br":
            self.lines.append([("", self.stack[-1])])
            return
        if tag in {"div", "p"} and self.lines[-1]:
            self.lines.append([])
        size = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)px", css.get("font-size", ""))
        self.stack.append(_number(size[1]) if size else self.stack[-1])
        margin = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)px", css.get("margin-top", ""))
        self.margin += _number(margin[1]) if margin else 0

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if tag in {"div", "p"} and self.lines[-1]:
            self.lines.append([])
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data):
        if self.html:
            data = re.sub(r"[\t\r\n\f ]+", " ", data)
            if not any(char for char, _ in self.lines[-1]):
                data = data.lstrip(" ")
            for char in data:
                if char != " " or not self.lines[-1] or self.lines[-1][-1][0] != " ":
                    self.lines[-1].append((char, self.stack[-1]))
            return
        for index, part in enumerate(data.split("\n")):
            if index:
                self.lines.append([("", self.stack[-1])])
            self.lines[-1].extend((char, self.stack[-1]) for char in part)


def _text_size(value, style, width):
    size = _number(style.get("fontSize", "12"))
    if size <= 0:
        raise ValueError("fontSize must be positive")
    parser = _Text(size, html=style.get("html") == "1")
    if style.get("html") == "1":
        parser.feed(value)
        parser.close()
    else:
        parser.handle_data(value)
    widest, height = 0, 0
    # shortcut: font advances are estimates; use final image review for actual font/CSS layout.
    for line in parser.lines:
        if parser.html and line and line[-1][0] == " ":
            line = line[:-1]
        used, line_height = 0, size * 1.2
        for char, font in line:
            advance = 0 if not char or unicodedata.combining(char) else font * (
                1 if unicodedata.east_asian_width(char) in {"W", "F"} else 0.6)
            if style.get("whiteSpace") == "wrap" and used and used + advance > width:
                widest = max(widest, used)
                height += line_height
                used, line_height = 0, size * 1.2
            used += advance
            line_height = max(line_height, font * 1.2)
        if line:
            widest = max(widest, used)
            height += line_height
    return widest, height + parser.margin, parser.unsupported


def _overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _hits(first, second, box):
    """Open rectangle intersection, so an endpoint/boundary touch is allowed."""
    low, high = 0.0, 1.0
    for start, end, left, right in ((first[0], second[0], box[0], box[0] + box[2]),
                                   (first[1], second[1], box[1], box[1] + box[3])):
        if start == end:
            if not left < start < right:
                return False
        else:
            limits = sorted(((left - start) / (end - start), (right - start) / (end - start)))
            low, high = max(low, limits[0]), min(high, limits[1])
    return low < high


def _page(model, problems, unchecked):
    for wrapper in model.iter():
        cell = wrapper.find("mxCell")
        if wrapper.tag in {"object", "UserObject"} and cell is not None:
            if wrapper.get("id"):
                cell.set("id", wrapper.get("id"))
            if wrapper.get("label") is not None:
                cell.set("value", wrapper.get("label"))
    cells = {cell.get("id"): cell for cell in model.iter("mxCell")}
    if any(not ident for ident in cells) or len(cells) != len(list(model.iter("mxCell"))):
        raise ValueError("missing or duplicate cell id")
    if not any(cell.get("vertex") == "1" or cell.get("edge") == "1" for cell in cells.values()):
        unchecked.append("no diagram vertices or edges to inspect")
    vertices, labels, routes = {}, {}, {}
    styles = {ident: _style(cell.get("style", "")) for ident, cell in cells.items()}

    def uncertain_geometry(ident, active=()):
        if ident in active:
            raise ValueError(f"{ident}: cyclic parent")
        cell = cells[ident]
        geometry = cell.find("mxGeometry")
        if ((geometry is not None and geometry.get("relative") == "1") or
                any(styles[ident].get(key, "0") != "0" for key in ("rotation", "flipH", "flipV"))):
            return True
        if (styles[ident].get("shape", "rectangle") not in {"rectangle", "swimlane"} or
                any(token and "=" not in token and token not in {"text", "swimlane", "group"}
                    for token in cell.get("style", "").split(";")) or
                geometry is not None and any(_number(geometry.get(key, "0")) == 0 for key in ("width", "height"))):
            return True
        parent = cell.get("parent")
        return parent in cells and cells[parent].get("vertex") == "1" and uncertain_geometry(parent, (*active, ident))

    def rectangle(ident, active=()):
        if ident in active:
            raise ValueError(f"{ident}: cyclic parent")
        cell = cells[ident]
        geometry = cell.find("mxGeometry")
        if geometry is None or geometry.get("relative") == "1":
            raise ValueError(f"{ident}: missing or relative vertex geometry")
        box = tuple(_number(geometry.get(key, "0")) for key in ("x", "y", "width", "height"))
        if box[2] <= 0 or box[3] <= 0:
            raise ValueError(f"{ident}: width and height must be positive")
        parent = cell.get("parent")
        if parent in cells and cells[parent].get("vertex") == "1":
            origin = rectangle(parent, (*active, ident))
            box = (box[0] + origin[0], box[1] + origin[1], *box[2:])
        return box

    def label(ident, value, style, box):
        if (_unmeasured_label(style) or cells[ident].get("placeholders") == "1" or
                cells[ident].find("mxGeometry/mxPoint[@as='offset']") is not None):
            unchecked.append(f"{ident}: external/transformed/substituted label needs image review")
            return
        spacing = _number(style.get("spacing", "2"))
        left = spacing + _number(style.get("spacingLeft", "0"))
        right = spacing + _number(style.get("spacingRight", "0"))
        top = spacing + _number(style.get("spacingTop", "0"))
        bottom = spacing + _number(style.get("spacingBottom", "0"))
        width, height, unsupported = _text_size(value, style, max(0, box[2] - left - right))
        if unsupported:
            unchecked.append(f"{ident}: rich HTML needs exported image review")
            return
        if width > box[2] - left - right or height > box[3] - top - bottom:
            problems.append(f"text_fit: {ident}: full text may be clipped; widen/heighten the card or split the view")
        x = box[0] + (left if style.get("align") == "left" else
                      box[2] - right - width if style.get("align") == "right" else (box[2] - width) / 2)
        y = box[1] + (top if style.get("verticalAlign") == "top" else
                      box[3] - bottom - height if style.get("verticalAlign") == "bottom" else (box[3] - height) / 2)
        labels[ident] = (x, y, width, height)

    page_width, page_height = (_number(model.get(key, "0")) for key in ("pageWidth", "pageHeight"))
    for ident, cell in cells.items():
        if cell.get("vertex") != "1":
            continue
        if uncertain_geometry(ident):
            unchecked.append(f"{ident}: relative/transformed/unsupported geometry needs image review")
            continue
        box = rectangle(ident)
        style = styles[ident]
        if page_width > 0 and page_height > 0 and (
                box[0] < 0 or box[1] < 0 or box[0] + box[2] > page_width or box[1] + box[3] > page_height):
            unchecked.append(f"{ident}: outside page guides; verify exported bounds")
        swimlane = "swimlane" in cell.get("style", "").split(";") or style.get("shape") == "swimlane"
        container = swimlane or style.get("container") == "1" or any(
            c.get("parent") == ident and c.get("vertex") == "1" and
            c.find("mxGeometry") is not None and c.find("mxGeometry").get("relative") != "1"
            for c in cells.values())
        if container and not (swimlane or style.get("container") == "1"):
            unchecked.append(f"{ident}: parent role is ambiguous; verify group/node bounds")
        text_only = "text" in cell.get("style", "").split(";")
        invisible_box = all(style.get(key, "none" if text_only else "") == "none"
                            for key in ("fillColor", "strokeColor"))
        if not container and not invisible_box:
            vertices[ident] = box
        if swimlane and cell.get("value"):
            unchecked.append(f"{ident}: swimlane header needs image review")
        elif cell.get("value"):
            label(ident, cell.get("value"), style, box)

    for ident, cell in cells.items():
        if cell.get("edge") != "1":
            continue
        if cell.get("data-diagram-role") == "lifeline":
            unchecked.append(f"{ident}: sequence lifeline needs notation/image review")
            continue
        style = styles[ident]
        geometry = cell.find("mxGeometry")
        if geometry is None:
            raise ValueError(f"{ident}: missing edge geometry")
        parent = cells.get(cell.get("parent"))
        if parent is not None and parent.get("vertex") == "1":
            unchecked.append(f"{ident}: nested edge coordinates need image review")
            continue
        if style.get("noEdgeStyle") != "1" and style.get("edgeStyle", "none") not in {"none", ""}:
            unchecked.append(f"{ident}: automatic route needs exported image review")
            continue
        if style.get("curved") == "1" or style.get("rounded") == "1":
            unchecked.append(f"{ident}: curved route needs exported image review")
            continue
        if (any(style.get(key, "0") != "0" for key in (
                "exitDx", "exitDy", "entryDx", "entryDy", "perimeterSpacing", "sourcePerimeterSpacing", "targetPerimeterSpacing")) or
                any(cell.get(side) in cells and uncertain_geometry(cell.get(side)) for side in ("source", "target"))):
            unchecked.append(f"{ident}: offset/transformed terminal needs image review")
            continue
        endpoints = []
        for side, prefix, key in (("source", "exit", "sourcePoint"), ("target", "entry", "targetPoint")):
            terminal = cell.get(side)
            point = geometry.find(f"mxPoint[@as='{key}']")
            if terminal in cells and all(prefix + axis in style for axis in ("X", "Y")):
                x, y, width, height = rectangle(terminal)
                px, py = (_number(style[prefix + axis]) for axis in ("X", "Y"))
                if style.get(prefix + "Perimeter") != "0" and not (
                        0 <= px <= 1 and 0 <= py <= 1 and (px in (0, 1) or py in (0, 1))):
                    unchecked.append(f"{ident}: projected perimeter port needs image review")
                    break
                endpoints.append((x + width * px, y + height * py))
            elif point is not None:
                endpoints.append((_number(point.get("x", "0")), _number(point.get("y", "0"))))
            else:
                unchecked.append(f"{ident}: implicit terminal needs exported image review")
                break
        if len(endpoints) != 2:
            continue
        points = [endpoints[0], *[(_number(p.get("x", "0")), _number(p.get("y", "0")))
                                  for p in geometry.findall("Array[@as='points']/mxPoint")], endpoints[1]]
        if all(point == points[0] for point in points):
            unchecked.append(f"{ident}: zero-length route needs image review")
            continue
        routes[ident] = points
        if page_width > 0 and page_height > 0 and any(
                not (0 <= x <= page_width and 0 <= y <= page_height) for x, y in points):
            unchecked.append(f"{ident}: route outside page guides; verify exported bounds")
        for other, box in vertices.items():
            if other not in {cell.get("source"), cell.get("target")} and any(
                    _hits(a, b, box) for a, b in zip(points, points[1:])):
                problems.append(f"edge_node: {ident} intersects {other}")
        if not cell.get("value"):
            continue
        if (_unmeasured_label(style) or geometry.get("relative") != "1" or
                any(_number(geometry.get(key, "0")) != 0 for key in ("x", "y")) or
                geometry.find("mxPoint[@as='offset']") is not None):
            unchecked.append(f"{ident}: noncentral edge label needs image review")
            continue
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        remaining = sum(lengths) / 2
        for a, b, length in zip(points, points[1:], lengths):
            if remaining <= length and length:
                center = tuple(a[i] + (b[i] - a[i]) * remaining / length for i in (0, 1))
                width, height, unsupported = _text_size(cell.get("value"), style, float("inf"))
                if unsupported:
                    unchecked.append(f"{ident}: rich HTML needs exported image review")
                else:
                    labels[ident] = (center[0] - width / 2, center[1] - height / 2, width, height)
                break
            remaining -= length

    for index, (ident, box) in enumerate(labels.items()):
        for other, node in vertices.items():
            if ident != other and _overlap(box, node):
                problems.append(f"label_node: {ident} overlaps {other}")
        for other, second in list(labels.items())[index + 1:]:
            if _overlap(box, second):
                problems.append(f"label_overlap: {ident} overlaps {other}")
        for other, points in routes.items():
            edge = cells[other]
            if ident not in {other, edge.get("source"), edge.get("target")} and any(
                    _hits(a, b, box) for a, b in zip(points, points[1:])):
                problems.append(f"label_edge: {ident} intersects {other}")


def check_drawio_quality(xml):
    problems, unchecked = [], []
    try:
        root = ET.fromstring(xml)
        models = [root] if root.tag == "mxGraphModel" else root.findall(".//mxGraphModel")
        if not models:
            unchecked.append("no uncompressed mxGraphModel; export uncompressed XML before checking")
        for page in root.iter("diagram"):
            if page.find("mxGraphModel") is None:
                unchecked.append(f"page {page.get('name', page.get('id', '?'))}: no uncompressed model")
        for index, model in enumerate(models):
            page_problems, page_unchecked = [], []
            if not list(model.iter("mxCell")):
                raise ValueError("draw.io page has no cells")
            _page(model, page_problems, page_unchecked)
            parent = next((d for d in root.iter("diagram") if model in list(d)), None)
            name = parent.get("name", str(index + 1)) if parent is not None else str(index + 1)
            problems.extend(f"page {name}: {p}" for p in page_problems)
            unchecked.extend(f"page {name}: {p}" for p in page_unchecked)
    except (ET.ParseError, ValueError, KeyError, TypeError) as error:
        problems.append(f"invalid draw.io geometry: {error}")
    return {"status": "fail" if problems else "partial" if unchecked else "pass",
            "problems": problems, "unchecked": unchecked,
            "textMeasurement": "estimated", "visualReview": "required"}
