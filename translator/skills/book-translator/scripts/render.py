"""Render the sealed book contract and verify real XeLaTeX output."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import core

PT_PER_MM = 72 / 25.4
SP_PER_PT = 65536 * 72.27 / 72
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "book.tex"
_ESCAPE = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#", "%": r"\%", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
_LITERAL_ESCAPE = {**_ESCAPE, "'": r"\textquotesingle{}", '"': r"\textquotedbl{}",
                   chr(96): r"\textasciigrave{}", "-": r"\char45{}",
                   "<": r"\textless{}", ">": r"\textgreater{}"}


def escape(text: str) -> str:
    """Treat all ordinary manuscript text as data, never as TeX."""
    return "".join(_ESCAPE.get(c, c) for c in text).replace("\r\n", "\n").replace("\r", "\n")


def _literal_text(text: str) -> str:
    """Escape data without applying TeX's quote/dash input substitutions."""
    return "".join(_LITERAL_ESCAPE.get(c, c) for c in text).replace("\r\n", "\n").replace("\r", "\n")


def _cell_text(text: str) -> str:
    """Wrap overwide ASCII cell runs without changing normal prose breaks."""
    pieces = re.split(r"([!-~]+)", text)
    for index in range(1, len(pieces), 2):
        literal = _literal_text(pieces[index])
        # Only overwide runs get expensive, ink-free fallback breaks. Leave CJK
        # punctuation and ordinary words to the existing locale/hyphenation rules.
        wrapped = r"\penalty1000{}".join(_literal_text(c) for c in pieces[index])
        pieces[index] = (r"{\sbox{\BTTempBox}{" + literal + r"}\ifdim\wd\BTTempBox>\linewidth " +
                         wrapped + r"\else " + literal + r"\fi}")
    return "".join(piece if index % 2 else _literal_text(piece) for index, piece in enumerate(pieces))


def _page_prefix(items: list[dict]) -> list[str]:
    pages = []
    for item in items:
        if "page" not in item:
            break
        pages.append(item["page"])
    return pages


def _source_page_plan(book: dict) -> tuple[dict, list[dict]]:
    """Plan graphic starts from source structure, independently of TeX positions."""
    blocks = [block for block in book["blocks"] if block["kind"] != "blank"]
    explicit = {item["page"] for block in blocks for item in block["target"] if "page" in item}
    emitted = set()
    plan, boundaries = {}, []
    for block in blocks:
        implicit = [page for page in block["source_pages"] if page not in emitted and page not in explicit]
        if implicit and (len(implicit) > 1 or implicit[0] != block["source_pages"][0]):
            raise ValueError(f"Block {block['id']} has ambiguous source-page boundaries; add exact inline page tokens")
        leading = []
        if block["kind"] in ("image", "group"):
            source_prefix, target_prefix = _page_prefix(block["source"]), _page_prefix(block["target"])
            if source_prefix != target_prefix:
                raise ValueError(f"Graphic block {block['id']} has inconsistent leading source/target page tokens")
            # A caption starting on a later source page is not the graphic's start.
            if source_prefix and source_prefix[0] == block["source_pages"][0]:
                leading = source_prefix
            boundaries.extend({"source_page": page, "block": block["id"],
                               "relation": block.get("relation")} for page in implicit + leading)
        plan[block["id"]] = (implicit, len(leading))
        emitted.update(implicit)
        emitted.update(item["page"] for item in block["target"] if "page" in item)
    return plan, boundaries


class _Renderer:
    def __init__(self, job_dir: Path, book: dict, terms: dict):
        self.job_dir = job_dir
        self.build_dir = job_dir / "build"
        self.book = book
        self.layout = core.load_json(job_dir / "job.json")["layout"]
        self.terms = {term["id"]: term for term in terms["terms"]}
        self.protected = {item["id"]: item for item in book["protected"]}
        self.notes = {item["id"]: item for item in book["notes"]}
        self.pages = {item["id"]: item for item in book["source_pages"]}
        self.seen_terms: set[str] = set()
        self.source_marks: list[dict] = []
        self.page_plan, self.graphic_boundaries = _source_page_plan(book)
        self.note_number = 0
        self.images: list[dict] = []
        self.literal_files: list[dict] = []
        self.assets: dict[str, str] = {}
        self.inline_images: list[dict] = []
        self.asset_pixels: dict[str, dict] = {}

    def protected_text(self, identifier: str) -> str:
        item = self.protected[identifier]
        value = item["value"]
        if item["kind"] in ("math", "variable"):
            return r"\(" + value + r"\)"
        if item["kind"] == "code":
            # Unlike normal prose, inline literal spaces and newlines are significant.
            literal = "".join(r"\hspace*{\fontdimen2\font}" if c == " " else
                              r"\hspace*{4\fontdimen2\font}" if c == "\t" else
                              r"\newline{}" if c == "\n" else _literal_text(c)
                              for c in value)
            return r"{\ttfamily " + literal + "}"
        return _literal_text(value)

    def term_text(self, identifier: str, literal: str | None = None) -> str:
        term = self.terms[identifier]
        text = _literal_text(term["target"] if literal is None else literal)
        if identifier in self.seen_terms:
            return text
        self.seen_terms.add(identifier)
        return (r"\BTFirstTerm{" + text + "}{" + str(term["number"]) +
                r"}\BTPosition{term:" + identifier + r"}\label{term:" + identifier + "}")

    def title_text(self) -> str:
        title = self.book["title"]
        result = []
        cursor = 0
        for span in self.book.get("title_terms", []):
            result.append(_literal_text(title[cursor:span["start"]]))
            result.append(self.term_text(span["term"], title[span["start"]:span["end"]]))
            cursor = span["end"]
        result.append(_literal_text(title[cursor:]))
        return "".join(result)

    def inline(self, items: list[dict], *, location: str = "body", deferred_notes: list[str] | None = None,
               index_offset: int = 0) -> str:
        result = []
        for index, item in enumerate(items, index_offset):
            kind, value = next(iter(item.items()))
            if kind == "text":
                result.append(escape(value))
            elif kind == "protected":
                result.append(self.protected_text(value))
            elif kind == "image":
                key = "inline:" + str(len(self.inline_images) + 1)
                path = self.asset(value["asset"])
                self.inline_images.append({"key": key, "location": f"{location}[{index}].image",
                                           "container": location, **value, **self.asset_pixels[value["asset"]]})
                numbers = "}{".join(format(value[field], ".10f") for field in ("width_em", "height_em", "raise_em"))
                result.append(r"\BTInlineImage{" + key + "}{" + numbers + "}{" + path + "}")
            elif kind == "term":
                result.append(self.term_text(value))
            elif kind == "note":
                self.note_number += 1
                number = str(self.note_number)
                note = self.notes[value]
                fragment = note.get("restoration", {}).get("original_fragment")
                pieces = []
                for note_index, token in enumerate(note["target"]):
                    if fragment and fragment in token.get("text", ""):
                        before, _, after = token["text"].partition(fragment)
                        pieces.append(escape(before) + _literal_text(fragment) + escape(after))
                    else:
                        pieces.append(self.inline([token], location="notes." + value + ".target", index_offset=note_index))
                content = (r"\BTPosition{note:" + value + ":start}" + "".join(pieces) +
                           r"\BTPosition{note:" + value + ":end}")
                result.append(r"\BTPosition{callout:" + value + "}")
                if deferred_notes is not None:
                    result.append(r"\footnotemark[" + number + "]")
                    deferred_notes.append(r"\footnotetext[" + number + "]{" + content + "}")
                else:
                    result.append(r"\footnote[" + number + "]{" + content + "}")
            elif kind == "page":
                key = "source:" + str(len(self.source_marks) + 1)
                page = self.pages[value]
                self.source_marks.append({"key": key, "source_page": value,
                                          "printed_label": page["printed_label"],
                                          "display": page["printed_label"],
                                          "locator": page["locator"]})
                result.append(r"\BTPosition{" + key + "}")
        return "".join(result)

    def asset(self, asset: str) -> str:
        if asset in self.assets:
            return self.assets[asset]
        from PIL import Image
        relative = "assets/image-" + str(len(self.assets) + 1) + ".png"
        destination = self.build_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Decode and re-encode, so neither asset names nor embedded metadata become TeX.
        with Image.open(self.job_dir / asset) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError(f"Image asset {asset} has multiple frames; select a single reviewed source image")
            normalized = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
            normalized.save(destination)
            self.asset_pixels[asset] = {"width_px": image.width, "height_px": image.height,
                                        "rgb_sha256": hashlib.sha256(normalized.convert("RGB").tobytes()).hexdigest(),
                                        "alpha_sha256": hashlib.sha256(normalized.convert("RGBA").getchannel("A").tobytes()).hexdigest()}
        self.assets[asset] = relative
        return relative

    def image_block(self, block: dict, caption: str, page_prefix: str, note_count: int) -> str:
        identifier = block["id"]
        if block["kind"] == "image":
            width, height = block["width"], block["height"]
            images = [{"asset": block["asset"], "x": 0, "y": 0, "width": width, "height": height}]
        else:
            width, height = block["canvas_width"], block["canvas_height"]
            images = block["images"]
        # Preserve source coordinates; only an explicit reviewed output factor may change scale.
        fit = block.get("fit")
        output_scale = fit["scale"] if fit else 1
        unit = 100 / max(width, height)
        unit_em = output_scale / (unit * block["source_em"])
        canvas = [r"\setlength{\unitlength}{" + f"{unit_em:.10f}em" + r"}\begin{picture}(" + f"{width * unit:.8f},{height * unit:.8f})"]
        for image in images:
            path = self.asset(image["asset"])
            canvas.append(r"\put(" + f"{image['x'] * unit:.8f},{(height - image['y'] - image['height']) * unit:.8f}" +
                          r"){\includegraphics[width=" + f"{image['width'] / block['source_em'] * output_scale:.10f}em,height={image['height'] / block['source_em'] * output_scale:.10f}em" + "]{" + path + "}}")
        canvas.append(r"\end{picture}")
        self.images.append({"id": identifier, "kind": block["kind"], "canvas_width": width,
                            "canvas_height": height, "source_em": block["source_em"],
                            "scale_evidence": block["scale_evidence"], "fit": fit,
                            "relation": block.get("relation"), "images": images})
        side = block.get("relation") in ("text-left", "text-right")
        start = r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:" + identifier + ":start}" + page_prefix + "\n"
        start += r"\def\BTCanvasScale{" + f"{output_scale:.10f}" + r"}\def\BTCanvasFloor{" + f"{fit['min_scale'] if fit else 1:.10f}" + "}\n"
        reservation = str(note_count) + r"\footnotesep-\skip\footins" if note_count else "0pt"
        start += r"\setlength{\BTAvailableHeight}{\dimexpr\textheight-" + reservation + r"\relax}" + "\n"
        image_box = r"\sbox{\BTImageBox}{" + "".join(canvas) + "}\n"
        if side:
            fraction = block["text_fraction"]
            text_width = f"{fraction:.8f}\\linewidth"
            image_width = f"{1 - fraction - .03:.8f}\\linewidth"
            text = r"\begin{minipage}[c]{" + text_width + "}\\noindent " + caption + r"\end{minipage}"
            image = (r"\begin{minipage}[c]{" + image_width + "}\n" + image_box +
                     r"\BTCheckCanvas{" + identifier + r"}\BTImageEvidence{" + identifier + "}\n" +
                     r"\leavevmode\BTPosition{canvas:" + identifier + r"}\usebox{\BTImageBox}\end{minipage}")
            pieces = [text, image] if block["relation"] == "text-left" else [image, text]
            content = r"\sbox{\BTTempBox}{" + r"\hfill".join(pieces) + "}\n"
            content += (r"\ifdim\dimexpr\ht\BTTempBox+\dp\BTTempBox\relax>\BTAvailableHeight"
                        r"\PackageError{book-translator}{Side-text group " + identifier +
                        r" exceeds a readable page; revise block boundaries while preserving source relationships}{}\fi" + "\n" +
                        r"\typeout{BTGROUP|" + identifier + r"|\number\ht\BTTempBox|\number\dp\BTTempBox}" + "\n" +
                        r"\leavevmode\BTPosition{group:" + identifier + r":baseline}\usebox{\BTTempBox}")
        else:
            content = r"\sbox{\BTTextBox}{\begin{minipage}{\linewidth}\noindent " + caption + r"\par\end{minipage}}" + "\n"
            content += image_box + r"\setlength{\BTAvailableHeight}{\dimexpr\BTAvailableHeight-\ht\BTTextBox-\dp\BTTextBox-\baselineskip\relax}" + "\n"
            content += r"\ifdim\BTAvailableHeight<\baselineskip\PackageError{book-translator}{Image caption " + identifier + r" leaves no readable image space; revise block boundaries}{}\fi" + "\n"
            content += r"\BTCheckCanvas{" + identifier + r"}\BTImageEvidence{" + identifier + "}\n"
            content += r"\noindent\makebox[\linewidth][c]{\BTPosition{canvas:" + identifier + r"}\usebox{\BTImageBox}}\par\smallskip\usebox{\BTTextBox}"
        return start + content + r"\BTPosition{block:" + identifier + r":end}\end{minipage}\par" + "\n"

    def body(self) -> str:
        output = []
        for block in self.book["blocks"]:
            identifier, kind = block["id"], block["kind"]
            if kind == "blank":
                continue
            if identifier == self.book["main_body_start"]:
                output.append(r"\BTMainBody")
            implicit, leading_count = self.page_plan[identifier]
            page_prefix = self.inline([{"page": implicit[0]}]) if implicit else ""
            if identifier == self.book["main_body_start"]:
                page_prefix = r"\BTPosition{mainbody:start}" + page_prefix
            if implicit:
                self.source_marks[-1]["placement_basis"] = "Inferred from a single unambiguous block-start source page"
            page_prefix += self.inline(block["target"][:leading_count])
            deferred_notes = [] if kind in ("image", "group") else None
            target = self.inline(block["target"][leading_count:], location="blocks." + identifier + ".target",
                                 deferred_notes=deferred_notes, index_offset=leading_count)
            # Text anchors travel inside any caption/side-text box. The outer block
            # baselines describe the minipage placement, not its first/last text line.
            target = (r"\BTPosition{block:" + identifier + ":content:start}" + target +
                      r"\BTPosition{block:" + identifier + ":content:end}")
            start = r"\BTPosition{block:" + identifier + ":start}" + page_prefix
            end = r"\BTPosition{block:" + identifier + ":end}"
            if kind in ("image", "group"):
                output.append(self.image_block(block, target, page_prefix, len(deferred_notes)) + "".join(deferred_notes) + "\n")
            elif kind == "heading":
                header = self.header_text(block["target"])
                output.append(r"\BTHeading{" + str(block["level"]) + "}{" + identifier + "}{" + start + target + end + "}{" + header + "}\n")
            elif kind == "paragraph":
                output.append(r"\BTParagraph{block:" + identifier + "}{" + page_prefix + target + "}\n")
            elif kind == "list_item":
                output.append(r"\BTListItem{" + identifier + "}{" + str(block["list_level"]) + "}{" +
                              _literal_text(block["label"]) + "}{" + page_prefix + target + "}\n")
            elif kind == "display_math":
                output.append(start + target + r"\[" + self.protected[block["protected_id"]]["value"] + r"\]" + end + "\n")
            elif kind == "code":
                value = self.protected[block["protected_id"]]["value"]
                relative = "assets/code-" + identifier + ".txt"
                (self.build_dir / "assets").mkdir(exist_ok=True)
                (self.build_dir / relative).write_text(value, encoding="utf-8", newline="")
                self.literal_files.append({"id": block["protected_id"], "path": relative,
                                           "sha256": hashlib.sha256(value.encode()).hexdigest()})
                output.append(start + target + "\n" + r"\VerbatimInput[fontsize=\small,breaklines=true,breakanywhere=true,tabsize=4]{" + relative + "}" + end + "\n")
        return "\n".join(output)

    def header_text(self, items: list[dict]) -> str:
        """Render running labels without terms, notes, source marks, or image effects."""
        return "".join(_literal_text(item["text"]) if "text" in item else
                       _literal_text(self.terms[item["term"]]["target"]) if "term" in item else
                       self.protected_text(item["protected"]) if "protected" in item else ""
                       for item in items)

    def tex(self) -> str:
        title = self.title_text()
        agent_preface = self.inline(self.book["agent_preface"])
        human = self.book["human_preface"]
        human_preface = (r"\BTHeading{2}{humanpreface}{Human preface}{Human preface}\BTParagraph{humanpreface}{" + self.inline(human) + "}\\clearpage\n") if human else ""
        body = self.body()
        rows = []
        for term in sorted(self.terms.values(), key=lambda item: item["number"]):
            rows.append(r"\BTPosition{glossary:" + term["id"] + "}" + str(term["number"]) + " & " + _cell_text(term["source"]) + " & " + _cell_text(term["target"]) +
                        r" & \BTFirstReference{" + term["id"] + r"} \\")
        substitutions = {"TITLE": title, "AGENT_PREFACE": agent_preface,
                         "BEFORE_BODY": "\u6b63\u6587\u524d", "GLOSSARY_TITLE": "\u672f\u8bed\u8868",
                         "NUMBER_HEADER": "\u5e8f\u53f7", "SOURCE_HEADER": "\u539f\u6587",
                         "TARGET_HEADER": "\u8bd1\u6587", "FIRST_PAGE_HEADER": "\u9996\u6b21\u51fa\u73b0\u9875",
                         "HUMAN_PREFACE": human_preface, "BODY": body, "TERMS": "\n".join(rows),
                         "SOURCE_OVERLAYS": "\n".join(r"\BTSourceOverlay{" + item["key"] + "}{" + _literal_text(item["display"]) + "}" for item in self.source_marks if item["display"] is not None)}
        for key, field in (("INNER", "inner_min_mm"), ("OUTER", "outer_mm"),
                           ("TOP", "top_mm"), ("BOTTOM", "bottom_mm"), ("MARK_EDGE", "source_mark_edge_mm")):
            substitutions[key] = format(self.layout[field], ".8f")
        template = TEMPLATE.read_text(encoding="utf-8")
        return re.sub(r"@@([A-Z_]+)@@", lambda match: substitutions[match[1]], template)


def render(job_dir: Path) -> Path:
    job_dir = Path(job_dir).resolve()
    book = core.validate_book(job_dir, translated=True)
    terms = core.load_json(job_dir / "terms.json")
    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    renderer = _Renderer(job_dir, book, terms)
    tex = renderer.tex()
    destination = build_dir / "book.tex"
    destination.write_text(tex, encoding="utf-8")
    shutil.copyfile(TEMPLATE.with_name("translator.sty"), build_dir / "translator.sty")
    core.save_json(build_dir / "render-manifest.json", {
        "version": 1, "content_digest": core.content_digest(job_dir),
        "layout": renderer.layout,
        "source_marks": renderer.source_marks, "images": renderer.images, "inline_images": renderer.inline_images,
        "graphic_boundaries": renderer.graphic_boundaries,
        "literal_files": renderer.literal_files,
        "main_body_start": book["main_body_start"],
        "blocks": [{key: block[key] for key in ("id", "kind", "level", "list_type", "list_level", "label") if key in block}
                   for block in book["blocks"] if block["kind"] != "blank"],
        "heading_text": {block["id"]: [item["text"] if "text" in item else renderer.terms[item["term"]]["target"]
                                         for item in block["target"] if "text" in item or "term" in item]
                         for block in book["blocks"] if block["kind"] == "heading"},
        "term_ids": list(renderer.terms), "note_ids": list(renderer.notes),
        "note_metadata": [{key: note[key] for key in ("id", "content_type", "literal_reason", "source_evidence") if key in note}
                          for note in book["notes"]]})
    return destination


def _positions(aux: str) -> dict:
    positions = {}
    for key, body in re.findall(r"\\zref@newlabel\{([^}]+)\}\{([^\n]+)\}", aux):
        properties = {name: int(value) for name, value in re.findall(r"\\(posx|posy|abspage)\{(-?\d+)\}", body)}
        if len(properties) == 3:
            positions[key] = {"page": properties["abspage"], "physical_pdf_page": properties["abspage"], "x_pt": properties["posx"] / SP_PER_PT,
                              "y_from_bottom_pt": properties["posy"] / SP_PER_PT}
    return positions


def _physical_text_lines(raw_lines: list[dict], em: float, left: float) -> list[dict]:
    """Merge PDF fragments by their dominant body-glyph baseline, not span origin.

    A span can start with an inferred space at a preceding subscript baseline;
    even a full-size math operator can have a raised origin. Neither creates a
    new prose line. Keep the owning line's nonblank glyph bounds, including its
    inline scripts, while using only its body-baseline glyphs for hanging indents.
    """
    physical = []
    extensions = []
    for line in raw_lines:
        by_baseline = {}
        glyphs, full_size = [], []
        for span in line["spans"]:
            for char in span["chars"]:
                if not char["c"].strip() or char["bbox"][0] < left - .3:
                    continue
                glyphs.append(char)
                if abs(span["size"] - em) < .4:
                    full_size.append(char)
                    y = char["origin"][1]
                    # Extension-font origins can be above all of their ink.
                    # Such a glyph is not an independent prose baseline.
                    if char["bbox"][1] >= y - .3:
                        continue
                    key = next((value for value in by_baseline if abs(value - y) < .3), y)
                    by_baseline.setdefault(key, []).append(char)
        if not by_baseline:
            if full_size:
                extensions.append((glyphs, full_size))
            continue
        y = max(by_baseline, key=lambda value: len(by_baseline[value]))
        row = next((item for item in physical if abs(item["baseline"] - y) < .3), None)
        if row is None:
            row = {"baseline": y, "body": [], "glyphs": []}
            physical.append(row)
        row["body"].extend(full_size)
        row["glyphs"].extend(glyphs)
    # A line-start sum may be extracted separately from its following prose.
    # Rejoin it by actual ink height; do not drop its bounds or hanging x.
    for glyphs, full_size in extensions:
        top = min(char["bbox"][1] for char in glyphs)
        bottom = max(char["bbox"][3] for char in glyphs)
        candidates = [row for row in physical
                      if min(bottom, max(char["bbox"][3] for char in row["glyphs"])) >
                      max(top, min(char["bbox"][1] for char in row["glyphs"])) + .5]
        if candidates:
            row = min(candidates, key=lambda item: abs(item["baseline"] - (top + bottom) / 2))
        else:
            row = {"baseline": full_size[0]["origin"][1], "body": [], "glyphs": []}
            physical.append(row)
        row["body"].extend(full_size)
        row["glyphs"].extend(glyphs)
    return sorted(physical, key=lambda item: item["baseline"])


def _layout_evidence(document, manifest: dict, log: str, positions: dict, geometry: dict, fail) -> tuple[list, list]:
    """Check physical-side headers and real PDF paragraph/list glyph placement."""
    import pymupdf

    normalize = lambda text: "".join(text.split())
    epoch = positions.get("mainbody:start")
    first_block = positions.get("block:" + manifest["main_body_start"] + ":start")
    if not epoch or not first_block or epoch["page"] != first_block["page"]:
        fail("pagination", "The explicit main-body start lacks a same-page physical epoch")
    epoch_page = epoch["page"] if epoch else len(document) + 1
    layout = manifest["layout"]
    top = layout["top_mm"] * PT_PER_MM
    bottom = document[0].rect.height - layout["bottom_mm"] * PT_PER_MM
    lines = {}
    glyph_lines = {}
    for number, page in enumerate(document, 1):
        lines[number] = [line for block in page.get_text("dict")["blocks"]
                         for line in block.get("lines", []) if line["spans"]]
        # Font-wide ascenders put extension glyphs above their real outlines.
        raw = page.get_text("rawdict", flags=(pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES) |
                            pymupdf.TEXT_ACCURATE_BBOXES)
        glyph_lines[number] = [line for block in raw["blocks"] for line in block.get("lines", [])]
    rows = {int(page): (folio, chapter.strip(), section.strip())
            for page, folio, chapter, section in re.findall(r"BTPAGE\|(\d+)\|([^|\n]*)\|([^|\n]*)\|([^\n]*)", log)}
    headings = []
    in_body = False
    for block in manifest["blocks"]:
        in_body = in_body or block["id"] == manifest["main_body_start"]
        if in_body and block["kind"] == "heading" and block["level"] <= 2:
            point = positions.get("block:" + block["id"] + ":start")
            if point:
                headings.append({**block, "page": point["page"]})
    glossary = positions.get("glossary:start")
    if glossary:
        headings.append({"id": "glossary", "kind": "heading", "level": 1, "page": glossary["page"]})
    pagination = []
    for number, page in enumerate(document, 1):
        folio = str(number - epoch_page + 1) if number >= epoch_page else ""
        row = rows.get(number)
        if not row or row[0].strip() != folio:
            fail("pagination", f"Physical PDF page {number} has an incorrect body-relative folio")
        header_lines = [line for line in lines[number] if max(span["origin"][1] for span in line["spans"]) < top - 2]
        footer_lines = [line for line in lines[number] if min(span["origin"][1] for span in line["spans"]) > bottom + 12]
        if footer_lines:
            fail("pagination", f"Physical PDF page {number} has unexpected footer text or a footer folio")
        if number < epoch_page:
            if header_lines or any(key.startswith(f"header:{number}:") for key in positions):
                fail("pagination", f"Front matter PDF page {number} prints a running header or folio")
            pagination.append({"physical_pdf_page": number, "printed_page": None, "side": "right" if number % 2 else "left"})
            continue
        candidates = [heading for heading in headings if heading["page"] <= number]
        chapters = [heading for heading in candidates if heading["level"] == 1]
        chapter = chapters[-1]["id"] if chapters else ""
        chapter_index = next((index for index, heading in enumerate(headings) if heading["id"] == chapter), -1)
        sections = [heading for heading in headings[chapter_index + 1:] if heading["page"] <= number and heading["level"] == 2]
        section = sections[-1]["id"] if sections else ""
        if row and (row[1] != chapter or row[2] != section):
            fail("pagination", f"Physical PDF page {number} has stale or wrong chapter/section marks")
        label_id = section if number % 2 else chapter
        expected_chunks = manifest["heading_text"].get(label_id, ["\u672f\u8bed\u8868"] if label_id == "glossary" else [])
        header = {}
        for role in ("inner", "outer"):
            start = positions.get(f"header:{number}:{role}:start")
            end = positions.get(f"header:{number}:{role}:end")
            if not start or not end or start["page"] != number or end["page"] != number:
                fail("pagination", f"Physical PDF page {number} lacks measured {role} header positions")
                continue
            baseline = page.rect.height - start["y_from_bottom_pt"]
            text = "".join(span["text"] for line in header_lines for span in line["spans"]
                           if abs(span["origin"][1] - baseline) < .5 and
                           span["bbox"][0] >= start["x_pt"] - .6 and span["bbox"][2] <= end["x_pt"] + .6)
            left = (layout["inner_min_mm"] if number % 2 else layout["outer_mm"]) * PT_PER_MM
            right = left + geometry.get("text_width", 0)
            aligned_left = (role == "inner") == bool(number % 2)
            edge = start["x_pt"] if aligned_left else end["x_pt"]
            if abs(edge - (left if aligned_left else right)) > .6 or baseline >= top - 2:
                fail("pagination", f"Physical PDF page {number} {role} header is not on its physical binding side")
            if role == "outer" and normalize(text) != folio:
                fail("pagination", f"Physical PDF page {number} lacks its exact outer header folio")
            if role == "inner" and any(normalize(chunk) not in normalize(text) for chunk in expected_chunks):
                fail("pagination", f"Physical PDF page {number} lacks its chapter/section inner header label")
            header[role] = {"text": text, "start": start, "end": end}
        if len(header) == 2:
            a, b = header["inner"], header["outer"]
            if min(a["end"]["x_pt"], b["end"]["x_pt"]) > max(a["start"]["x_pt"], b["start"]["x_pt"]) + .5:
                fail("pagination", f"Physical PDF page {number} running label overlaps its folio")
        body_lines = [line for line in lines[number] if top <= line["bbox"][1] < bottom]
        if not body_lines and not page.get_image_info():
            fail("pagination", f"Physical PDF page {number} is an allocated padding page without content")
        pagination.append({"physical_pdf_page": number, "printed_page": int(folio), "side": "right" if number % 2 else "left",
                           "chapter": chapter, "section": section, "headers": header})
    type_rows = {identifier: (kind, int(em) / SP_PER_PT, int(label) / SP_PER_PT if label else 0)
                 for identifier, kind, em, label in re.findall(r"BTTYPE\|([^|\s]+)\|(paragraph|list_item)\|(\d+)(?:\|(\d+))?", log)}
    required = [{"id": "preface", "kind": "paragraph", "key": "preface"}]
    if "humanpreface:start" in positions:
        required.append({"id": "humanpreface", "kind": "paragraph", "key": "humanpreface"})
    required.extend({**block, "key": "block:" + block["id"]} for block in manifest["blocks"] if block["kind"] in ("paragraph", "list_item"))
    typography = []
    for block in required:
        key = block["key"]
        identifier = block["id"] if block["kind"] == "list_item" else key
        metric = type_rows.get(identifier)
        start, end = positions.get(key + ":start"), positions.get(key + ":end")
        if not metric or not start or not end or metric[1] <= 0:
            fail("typography", f"Missing paragraph/list font-em and position evidence for {key}")
            continue
        _, em, label_width = metric
        number = start["page"]
        left = (layout["inner_min_mm"] if number % 2 else layout["outer_mm"]) * PT_PER_MM
        indent = 2 * em
        label = None
        if block["kind"] == "list_item":
            indent += block["list_level"] * 2 * em
            label = positions.get("list:" + block["id"] + ":label")
            if not label or label["page"] != number or abs(label["x_pt"] - left - indent) > .3:
                fail("typography", f"List {key} lost its source marker's nested two-em indentation")
            indent += label_width
        if abs(start["x_pt"] - left - indent) > .3:
            fail("typography", f"Paragraph/list {key} does not begin at its required two-em/hanging indent")
        baseline = document[number - 1].rect.height - start["y_from_bottom_pt"]
        first_spans = [span for line in lines[number] for span in line["spans"]
                       if abs(span["origin"][1] - baseline) < .5 and span["bbox"][2] > start["x_pt"] - .1 and
                       span["bbox"][0] >= start["x_pt"] - .3]
        if not first_spans and start["y_from_bottom_pt"] != end["y_from_bottom_pt"]:
            fail("typography", f"Paragraph/list {key} has no actual PDF glyphs at its measured first baseline")
        continuation = []
        physical_lines = _physical_text_lines(glyph_lines[number], em, left)
        if block["kind"] == "list_item" and start["page"] == end["page"]:
            last_baseline = document[number - 1].rect.height - end["y_from_bottom_pt"]
            for line in physical_lines:
                if not baseline + .7 * em < line["baseline"] <= last_baseline + .4:
                    continue
                x = min(char["origin"][0] for char in line["body"])
                continuation.append(x)
                if abs(x - start["x_pt"]) > .5:
                    fail("typography", f"List {key} continuation does not hang beneath its text")
            if label:
                marker_text = "".join(span["text"] for line in lines[number] for span in line["spans"]
                                      if abs(span["origin"][1] - baseline) < .5 and
                                      span["bbox"][0] >= label["x_pt"] - .5 and span["bbox"][2] <= start["x_pt"] + .3)
                if normalize(block["label"]) not in normalize(marker_text):
                    fail("typography", f"List {key} source marker is absent from actual PDF text")
        line_boxes = []
        if start["page"] == end["page"]:
            last_baseline = document[number - 1].rect.height - end["y_from_bottom_pt"]
            for line in physical_lines:
                if baseline - .3 <= line["baseline"] <= last_baseline + .3:
                    boxes = [char["bbox"] for char in line["glyphs"]]
                    line_boxes.append([min(box[0] for box in boxes), min(box[1] for box in boxes),
                                       max(box[2] for box in boxes), max(box[3] for box in boxes)])
            if any(following[1] < previous[3] - .5 for previous, following in zip(line_boxes, line_boxes[1:])):
                fail("typography", f"Paragraph/list {key} actual PDF glyph lines overlap")
        typography.append({"id": block["id"], "kind": block["kind"], "font_em_pt": em, "start": start, "end": end,
                           "initial_indent_pt": indent, "label": label, "continuation_x_pt": continuation, "line_boxes_pt": line_boxes})
    return pagination, typography


def _verify(build_dir: Path, manifest: dict, log: str, aux: str) -> dict:
    import pymupdf
    errors = []
    checks = {name: True for name in ("compiler", "pdf_geometry", "preface", "source_boundaries", "image_relations", "inline_images", "footnotes", "references", "overflow", "pagination", "typography")}
    def fail(check: str, message: str) -> None:
        checks[check] = False
        errors.append(message)
    layout = manifest["layout"]
    inner = layout["inner_min_mm"]
    outer = layout["outer_mm"]
    edge_mm = layout["source_mark_edge_mm"]
    geometry_keys = ("paper_width", "paper_height", "text_width", "text_height", "odd_left", "even_left", "top")
    geometry_match = re.search(r"BTGEOMETRY\|" + r"\s*\|".join([r"(\d+)"] * 7), log)
    geometry = dict(zip(geometry_keys, (int(value) / SP_PER_PT for value in geometry_match.groups()))) if geometry_match else {}
    expected_geometry = (148, 210, 148 - inner - outer, 210 - layout["top_mm"] - layout["bottom_mm"], inner, outer, layout["top_mm"])
    if not geometry or any(abs(geometry[key] - expected * PT_PER_MM) > .2 for key, expected in zip(geometry_keys, expected_geometry)):
        fail("pdf_geometry", "Compiled TeX margins do not match the current mirrored job layout")
    if re.search(r"Overfull \\[hv]box", log):
        fail("overflow", "XeLaTeX reported overfull output; inspect build/book.log and revise the affected content")
    if re.search(r"(?:undefined references|Reference .+ undefined|Label\(s\) may have changed|Rerun to get|rerunfilecheck Warning)", log, re.I):
        fail("references", "XeLaTeX references or saved positions have not converged")
    if "Missing character:" in log:
        fail("compiler", "XeLaTeX reported missing font glyphs; supply a font covering the manuscript")
    positions = _positions(aux)
    epoch_page = positions.get("mainbody:start", {}).get("page")
    def printed_folio(physical: int) -> int | None:
        return physical - epoch_page + 1 if epoch_page is not None and physical >= epoch_page else None
    for point in positions.values():
        point["printed_page"] = printed_folio(point["page"])
    document = pymupdf.open(build_dir / "book.pdf")
    page_evidence = []
    for number, page in enumerate(document, 1):
        size = [page.rect.width, page.rect.height]
        if abs(size[0] - 148 * PT_PER_MM) > .3 or abs(size[1] - 210 * PT_PER_MM) > .3:
            fail("pdf_geometry", f"PDF page {number} is not A5")
        spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"] if span["text"].strip()]
        for span in spans:
            box = pymupdf.Rect(span["bbox"])
            if box.x0 < -.2 or box.y0 < -.2 or box.x1 > page.rect.width + .2 or box.y1 > page.rect.height + .2:
                fail("pdf_geometry", f"Text is clipped outside PDF page {number}: {span['text'][:40]}")
        page_evidence.append({"page": number, "physical_pdf_page": number, "printed_page": printed_folio(number),
                              "width_pt": size[0], "height_pt": size[1],
                              "inner_mm": inner, "outer_mm": outer, "top_mm": layout["top_mm"], "bottom_mm": layout["bottom_mm"],
                              "text_left_mm": inner if number % 2 else outer, "text_right_mm": outer if number % 2 else inner,
                              "text_spans": len(spans), "images": len(page.get_image_info())})
    def position(key: str, check: str) -> dict | None:
        item = positions.get(key)
        if not item or not 1 <= item["page"] <= len(document):
            fail(check, f"Missing or invalid compiled boundary {key}")
            return None
        return item
    preface_start = position("preface:start", "preface")
    preface_end = position("preface:end", "preface")
    preface_pages = []
    if preface_start and preface_end:
        preface_pages = list(range(preface_start["page"], preface_end["page"] + 1))
        if len(preface_pages) > 2:
            fail("preface", f"Agent preface occupies {len(preface_pages)} pages; maximum is two")
    source_marks = []
    for mark in manifest["source_marks"]:
        point = position(mark["key"], "source_boundaries")
        if not point:
            continue
        page = document[point["page"] - 1]
        baseline = page.rect.height - point["y_from_bottom_pt"]
        outer_right = bool(point["page"] % 2)
        candidates = [span for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]
                      if abs(span["origin"][1] - baseline) < .5 and
                      ((span["bbox"][0] > page.rect.width - outer * PT_PER_MM - .5) if outer_right else (span["bbox"][2] < outer * PT_PER_MM + .5))]
        label = "".join(span["text"] for span in candidates)
        if mark["display"] is not None and label != mark["display"]:
            fail("source_boundaries", f"Source boundary {mark['source_page']} has no exact outer-edge printed label at its compiled baseline")
        if candidates and mark["display"] is not None:
            edge = max(span["bbox"][2] for span in candidates) if outer_right else min(span["bbox"][0] for span in candidates)
            expected = page.rect.width - edge_mm * PT_PER_MM if outer_right else edge_mm * PT_PER_MM
            if abs(edge - expected) > .7:
                fail("source_boundaries", f"Source label {mark['source_page']} is not {edge_mm}mm from its outer edge")
        if mark["display"] is not None:
            for previous_mark in source_marks:
                if previous_mark["display"] is not None and previous_mark["page"] == point["page"] and abs(previous_mark["baseline_from_top_pt"] - baseline) < 6:
                    fail("source_boundaries", f"Source labels {previous_mark['source_page']} and {mark['source_page']} collide; revise line breaks without moving source boundaries")
        source_marks.append({**mark, **point, "baseline_from_top_pt": baseline, "outer_edge_mm": edge_mm})
    boundaries = []
    for block in manifest["blocks"]:
        start = position("block:" + block["id"] + ":start", "source_boundaries")
        end = position("block:" + block["id"] + ":end", "source_boundaries")
        if start and end:
            if block["kind"] in ("image", "group") and start["page"] != end["page"]:
                fail("image_relations", f"Indivisible image/group {block['id']} crossed a page boundary")
            boundaries.append({**block, "start": start, "end": end})
    images = []
    dimensions = {identifier: tuple(int(value) / SP_PER_PT for value in (em, w, h))
                  for identifier, em, w, h in re.findall(r"BTIMAGE\|([^|\s]+)\|(\d+)\|(\d+)\|(\d+)", log)}
    for canvas in manifest["images"]:
        origin = position("canvas:" + canvas["id"], "image_relations")
        if not origin or canvas["id"] not in dimensions:
            fail("image_relations", f"Missing compiled image canvas {canvas['id']}")
            continue
        em, width, height = dimensions[canvas["id"]]
        natural_width = canvas["canvas_width"] / canvas["source_em"] * em
        natural_height = canvas["canvas_height"] / canvas["source_em"] * em
        fit = canvas.get("fit")
        output_scale = fit["scale"] if fit else 1
        if not 0 < output_scale <= 1 or (fit and not 0 < fit["min_scale"] <= output_scale):
            fail("image_relations", f"Image canvas {canvas['id']} violates its reviewed no-enlargement/legibility bounds")
        if abs(width - natural_width * output_scale) > .08 or abs(height - natural_height * output_scale) > .08:
            fail("image_relations", f"Image canvas {canvas['id']} changed its reviewed uniform source-font scale")
        page = document[origin["page"] - 1]
        actual = [pymupdf.Rect(item["bbox"]) for item in page.get_image_info()]
        rectangles = []
        pdf_tops = []
        scale = em / canvas["source_em"] * output_scale
        # A savepos inside the image hbox records its actual bottom-left origin.
        top = page.rect.height - origin["y_from_bottom_pt"] - height
        for image in canvas["images"]:
            expected = pymupdf.Rect(origin["x_pt"] + image["x"] * scale, top + image["y"] * scale,
                                 origin["x_pt"] + (image["x"] + image["width"]) * scale,
                                 top + (image["y"] + image["height"]) * scale)
            match = next((rect for rect in actual if max(abs(a - b) for a, b in zip(rect, expected)) < .6), None)
            if match is None:
                fail("image_relations", f"Image {image['asset']} in {canvas['id']} changed its source offset, gap, or relative geometry")
            else:
                # Recover the canvas top from actual PDF panel geometry, not from
                # the source mark or the caption's saved text baseline.
                pdf_tops.append(match.y0 - image["y"] * match.width / image["width"])
            if expected.x0 < (inner if origin["page"] % 2 else outer) * PT_PER_MM - .7 or expected.x1 > page.rect.width - (outer if origin["page"] % 2 else inner) * PT_PER_MM + .7 or expected.y0 < layout["top_mm"] * PT_PER_MM - .7 or expected.y1 > page.rect.height - layout["bottom_mm"] * PT_PER_MM + .7:
                fail("image_relations", f"Image {canvas['id']} exceeds the A5 text area")
            rectangles.append({"asset": image["asset"], "expected_rect_pt": list(expected), "pdf_rect_pt": list(match) if match else None})
        images.append({"id": canvas["id"], **origin, "width_pt": width, "height_pt": height,
                       "natural_width_pt": natural_width, "natural_height_pt": natural_height,
                       "scale": output_scale, "fit": fit,
                       "rectangles": rectangles, "top_from_pdf_pt": pdf_tops})
    graphic_boundaries = []
    side_dimensions = {identifier: (int(height) / SP_PER_PT, int(depth) / SP_PER_PT)
                       for identifier, height, depth in re.findall(r"BTGROUP\|([^|\s]+)\|(\d+)\|(\d+)", log)}
    for expected in manifest["graphic_boundaries"]:
        identifier = expected["block"]
        marks = [mark for mark in source_marks if mark["source_page"] == expected["source_page"]]
        canvas = next((image for image in images if image["id"] == identifier), None)
        if len(marks) != 1 or canvas is None:
            fail("source_boundaries", f"Graphic start {identifier}/{expected['source_page']} lacks unique marker/canvas evidence")
            continue
        mark = marks[0]
        tops = canvas["top_from_pdf_pt"]
        if not tops:
            fail("source_boundaries", f"Graphic start {identifier} has no independent PDF canvas geometry")
            continue
        if expected["relation"] in ("text-left", "text-right"):
            baseline = position("group:" + identifier + ":baseline", "source_boundaries")
            dimensions = side_dimensions.get(identifier)
            if baseline is None or dimensions is None or baseline["page"] != canvas["page"]:
                fail("source_boundaries", f"Graphic start {identifier} has no assembled side-group box evidence")
                continue
            box_top = document[canvas["page"] - 1].rect.height - baseline["y_from_bottom_pt"] - dimensions[0]
            box_bottom = box_top + sum(dimensions)
            if any(top < box_top - .5 or top + canvas["height_pt"] > box_bottom + .5 for top in tops):
                fail("source_boundaries", f"Graphic start {identifier} assembled box disagrees with actual PDF canvas geometry")
            tops = [box_top]
        if mark["page"] != canvas["page"] or any(abs(mark["baseline_from_top_pt"] - top) > .5 for top in tops):
            fail("source_boundaries", f"Source boundary {expected['source_page']} is not at graphic start {identifier} on its actual PDF page")
        graphic_boundaries.append({**expected, "page": canvas["page"],
                                   "expected_top_pt": tops, "marker_baseline_pt": mark["baseline_from_top_pt"]})
    inline_images = []
    em_sizes = {}
    for key, em in re.findall(r"BTINLINE\|([^|\s]+)\|(\d+)", log):
        em_sizes.setdefault(key, set()).add(int(em) / SP_PER_PT)
    pdf_images = {}
    pixel_hashes = {}
    used_images = set()
    previous_inline = {}

    def in_reading_order(first: dict, second: dict) -> bool:
        if first["page"] != second["page"]:
            return first["page"] < second["page"]
        if abs(first["y_from_bottom_pt"] - second["y_from_bottom_pt"]) > .2:
            return first["y_from_bottom_pt"] > second["y_from_bottom_pt"]
        return first["x_pt"] <= second["x_pt"] + .2

    for image in manifest["inline_images"]:
        key, location = image["key"], image["location"]
        start = position(key + ":start", "inline_images")
        end = position(key + ":end", "inline_images")
        sizes = em_sizes.get(key, set())
        if not start or not end or len(sizes) != 1 or next(iter(sizes)) <= 0:
            fail("inline_images", f"{location}: missing or ambiguous compiled inline image/font-em evidence ({key})")
            continue
        em = next(iter(sizes))
        width, height, raise_pt = (image[field] * em for field in ("width_em", "height_em", "raise_em"))
        if start["page"] != end["page"] or abs(start["y_from_bottom_pt"] - end["y_from_bottom_pt"]) > .08 or abs(end["x_pt"] - start["x_pt"] - width) > .08:
            fail("inline_images", f"{location}: inline image split, reordered, or changed its baseline/advance")
        previous = previous_inline.get(image["container"])
        if previous and not in_reading_order(previous["end"], start):
            fail("inline_images", f"{location}: inline image reading order differs from {previous['location']}")
        previous_inline[image["container"]] = {"end": end, "location": location}
        category, identifier, _ = image["container"].split(".")
        parent = "block:" + identifier + ":content" if category == "blocks" else "note:" + identifier
        parent_start = position(parent + ":start", "inline_images")
        parent_end = position(parent + ":end", "inline_images")
        if parent_start and parent_end and (not in_reading_order(parent_start, start) or not in_reading_order(end, parent_end)):
            fail("inline_images", f"{location}: inline image escaped its compiled {parent} boundaries")
        page_number = start["page"]
        page = document[page_number - 1]
        baseline = page.rect.height - start["y_from_bottom_pt"]
        expected = pymupdf.Rect(start["x_pt"], baseline - raise_pt - height, start["x_pt"] + width, baseline - raise_pt)
        if page_number not in pdf_images:
            pdf_images[page_number] = (page.get_image_info(xrefs=True), {row[0]: row[1] for row in page.get_images(full=True)})
        actual, masks = pdf_images[page_number]
        match = next(((index, item) for index, item in enumerate(actual)
                      if (page_number, index) not in used_images and
                      max(abs(a - b) for a, b in zip(item["bbox"], expected)) < .08), None)
        if match is None:
            fail("inline_images", f"{location}: omitted, moved, or distorted inline image {image['asset']} on PDF page {page_number}; expected {list(expected)}")
        else:
            index, item = match
            used_images.add((page_number, index))
            a, b, c, d, _, _ = item["transform"]
            if abs(a - width) > .08 or abs(d - height) > .08 or abs(b) > .08 or abs(c) > .08:
                fail("inline_images", f"{location}: inline image was rotated, reflected, or distorted")
            xref = item["xref"]
            mask = masks.get(xref, 0)
            if not xref:
                fail("inline_images", f"{location}: inline image has no verifiable PDF raster object")
            else:
                identity = (xref, mask)
                if identity not in pixel_hashes:
                    pixels = pymupdf.Pixmap(document, xref)
                    rgb = pixels if pixels.colorspace.n == 3 else pymupdf.Pixmap(pymupdf.csRGB, pixels)
                    alpha = pymupdf.Pixmap(document, mask).samples if mask else bytes([255]) * (pixels.width * pixels.height)
                    pixel_hashes[identity] = {"width_px": pixels.width, "height_px": pixels.height,
                                              "rgb_sha256": hashlib.sha256(rgb.samples).hexdigest(),
                                              "alpha_sha256": hashlib.sha256(alpha).hexdigest()}
                if any(pixel_hashes[identity][field] != image[field] for field in ("width_px", "height_px", "rgb_sha256", "alpha_sha256")):
                    fail("inline_images", f"{location}: PDF raster pixels differ from unchanged source asset {image['asset']}")
        if expected.x0 < (inner if page_number % 2 else outer) * PT_PER_MM - .2 or expected.x1 > page.rect.width - (outer if page_number % 2 else inner) * PT_PER_MM + .2 or expected.y0 < layout["top_mm"] * PT_PER_MM - .2 or expected.y1 > page.rect.height - layout["bottom_mm"] * PT_PER_MM + .2:
            fail("inline_images", f"{location}: inline image exceeds the A5 text area on PDF page {page_number}")
        inline_images.append({**image, "start": start, "end": end, "font_em_pt": em,
                              "width_pt": width, "height_pt": height, "raise_pt": raise_pt,
                              "baseline_from_top_pt": baseline, "expected_rect_pt": list(expected),
                              "pdf_rect_pt": list(match[1]["bbox"]) if match else None})
    epoch = position("mainbody:start", "pagination")
    term_pages, term_references = {}, {}
    glossary_rows, glossary_page_chars = [], {}
    for identifier in manifest["term_ids"]:
        first = position("term:" + identifier, "references")
        row = position("glossary:" + identifier, "references")
        if first and epoch:
            physical = first["page"]
            printed = physical - epoch["page"] + 1 if physical >= epoch["page"] else None
            display = str(printed) if printed is not None else "\u6b63\u6587\u524d PDF " + str(physical)
            term_pages[identifier] = physical
            term_references[identifier] = {"physical_pdf_page": physical, "printed_page": printed, "display": display}
            if row:
                page = document[row["page"] - 1]
                baseline = page.rect.height - row["y_from_bottom_pt"]
                left = (inner if row["page"] % 2 else outer) * PT_PER_MM
                width = geometry.get("text_width", 0)
                padding = 6 * 72 / 72.27
                table_width = width - 6 * padding
                next_rows = [point for key, point in positions.items() if key.startswith("glossary:") and key != "glossary:start" and
                             point["page"] == row["page"] and point["y_from_bottom_pt"] < row["y_from_bottom_pt"] - .5]
                next_baseline = min((page.rect.height - point["y_from_bottom_pt"] for point in next_rows), default=page.rect.height)
                if row["page"] not in glossary_page_chars:
                    glossary_page_chars[row["page"]] = [char for block in page.get_text("rawdict")["blocks"]
                                                        for line in block.get("lines", []) for span in line["spans"] for char in span["chars"]]
                fractions = (.08, .32, .34, .26)
                first_baselines, cell_texts = [], []
                for column, fraction in enumerate(fractions):
                    x = left + sum(fractions[:column]) * table_width + column * 2 * padding
                    glyphs = [char for char in glossary_page_chars[row["page"]]
                              if x - .3 <= char["origin"][0] <= x + fraction * table_width + .3 and
                              baseline - .2 <= char["origin"][1] < next_baseline - .2]
                    visible = [char for char in glyphs if char["c"].strip()]
                    first_baselines.append(min((char["origin"][1] for char in visible), default=None))
                    cell_texts.append("".join(char["c"] for char in glyphs))
                if any(value is None or abs(value - baseline) > .2 for value in first_baselines):
                    fail("typography", f"Glossary row {identifier} number/source/translation/reference first baselines do not align: {first_baselines}")
                glossary_rows.append({"id": identifier, **row, "first_text_baselines_pt": first_baselines})
                if "".join(display.split()) != "".join(cell_texts[3].split()):
                    fail("references", f"Glossary {identifier} does not display its logical first-use reference")
    footnote_pages = []
    for number, height, limit in re.findall(r"BTFOOT\|(\d+)\|(\d+)\|(\d+)", log):
        height, limit = int(height) / SP_PER_PT, int(limit) / SP_PER_PT
        if height > limit + .1:
            fail("footnotes", f"Footnotes exceed half the text area on page {number}")
        if height < 5:
            fail("footnotes", f"Footnote footer on page {number} contains less than one line")
        page = document[int(number) - 1]
        minimum_top = layout["top_mm"] * PT_PER_MM + geometry.get("text_height", 0) / 2
        rules = [drawing["rect"] for drawing in page.get_drawings() if drawing["rect"].height < .8 and abs(drawing["rect"].width - .4 * geometry.get("text_width", 0)) < 1 and drawing["rect"].y0 >= minimum_top - .7]
        if not rules:
            fail("footnotes", f"Footnote footer on page {number} has no horizontal separator rule")
        footnote_pages.append({"page": int(number), "physical_pdf_page": int(number), "printed_page": printed_folio(int(number)),
                               "height_pt": height, "maximum_pt": limit})
    notes = []
    for identifier in manifest["note_ids"]:
        start = position("note:" + identifier + ":start", "footnotes")
        end = position("note:" + identifier + ":end", "footnotes")
        callout = position("callout:" + identifier, "footnotes")
        if start and end and callout:
            if start["page"] != callout["page"]:
                fail("footnotes", f"Note {identifier} has no first footer line on its callout page")
            metadata = next(item for item in manifest["note_metadata"] if item["id"] == identifier)
            notes.append({**metadata, "callout": callout, "start": start, "end": end})
    if notes and not footnote_pages:
        fail("footnotes", "No real bottom-footnote insertion evidence was recorded")
    pagination, typography = _layout_evidence(document, manifest, log, positions, geometry, fail)
    document.close()
    return {"checks": checks, "passed": all(checks.values()), "errors": errors, "pages": page_evidence,
            "agent_preface_pages": preface_pages, "source_marks": source_marks, "block_boundaries": boundaries,
            "images": images, "graphic_boundaries": graphic_boundaries, "inline_images": inline_images,
            "term_first_pages": term_pages, "term_first_references": term_references,
            "pagination": pagination, "typography": typography, "glossary_rows": glossary_rows,
            "footnote_pages": footnote_pages, "notes": notes, "compiled_geometry_pt": geometry}


def build(job_dir: Path) -> Path:
    job_dir = Path(job_dir).resolve()
    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "content_digest": None, "passed": False,
              "errors": [], "evidence": ["book.tex", "translator.sty", "book.log", "compiler.log", "book.aux", "book.pdf", "render-manifest.json"]}
    try:
        report["content_digest"] = core.content_digest(job_dir)
        render(job_dir)
        manifest = core.load_json(build_dir / "render-manifest.json")
        report["content_digest"] = manifest["content_digest"]
        executable = shutil.which("xelatex")
        if not executable:
            raise RuntimeError("XeLaTeX is required; install a TeX distribution with ctexbook before building")
        previous = None
        compiler_log = []
        for run in range(1, 7):
            result = subprocess.run([executable, "-no-shell-escape", "-halt-on-error", "-file-line-error", "-interaction=nonstopmode", "book.tex"],
                                    cwd=build_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            compiler_log.append(f"=== XeLaTeX run {run} ===\n" + result.stdout + result.stderr)
            (build_dir / "compiler.log").write_text("\n".join(compiler_log), encoding="utf-8")
            if result.returncode:
                details = "\n".join((result.stdout + result.stderr).splitlines()[-18:])
                raise RuntimeError("XeLaTeX compilation failed; inspect build/compiler.log:\n" + details)
            aux = (build_dir / "book.aux").read_text(encoding="utf-8")
            if previous == aux and run >= 2:
                break
            previous = aux
        log = (build_dir / "book.log").read_text(encoding="utf-8")
        report.update(_verify(build_dir, manifest, log, aux))
        if core.content_digest(job_dir) != manifest["content_digest"]:
            report["passed"] = False
            report["errors"].append("Authoritative inputs changed during compilation; rebuild the current manuscript")
        report["artifacts"] = {name: hashlib.sha256((build_dir / name).read_bytes()).hexdigest()
                               for name in ("book.tex", "translator.sty", "book.pdf", "book.log", "book.aux", "render-manifest.json")}
        report["pdf_sha256"] = report["artifacts"]["book.pdf"]
        core.save_json(build_dir / "verification.json", report)
        if not report["passed"]:
            raise ValueError("Book layout verification failed: " + "; ".join(report["errors"]))
        return build_dir / "book.pdf"
    except Exception as error:
        if not report["errors"]:
            report["errors"].append(str(error))
        report["passed"] = False
        core.save_json(build_dir / "verification.json", report)
        raise
