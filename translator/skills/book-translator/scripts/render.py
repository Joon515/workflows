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


def escape(text: str) -> str:
    """Treat all ordinary manuscript text as data, never as TeX."""
    return "".join(_ESCAPE.get(c, c) for c in text).replace("\r\n", "\n").replace("\r", "\n")


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
        self.emitted_source_pages: set[str] = set()
        self.explicit_source_pages = {item["page"] for block in book["blocks"] for item in block["target"] if "page" in item}
        self.note_number = 0
        self.images: list[dict] = []
        self.literal_files: list[dict] = []
        self.assets: dict[str, str] = {}

    def protected_text(self, identifier: str) -> str:
        item = self.protected[identifier]
        value = item["value"]
        if item["kind"] in ("math", "variable"):
            return r"\(" + value + r"\)"
        if item["kind"] == "code":
            # Unlike normal prose, inline literal spaces and newlines are significant.
            literal = "".join(r"\hspace*{\fontdimen2\font}" if c == " " else
                              r"\hspace*{4\fontdimen2\font}" if c == "\t" else
                              r"\newline{}" if c == "\n" else escape(c)
                              for c in value)
            return r"{\ttfamily " + literal + "}"
        return escape(value)

    def inline(self, items: list[dict], *, deferred_notes: list[str] | None = None) -> str:
        result = []
        for item in items:
            kind, value = next(iter(item.items()))
            if kind == "text":
                result.append(escape(value))
            elif kind == "protected":
                result.append(self.protected_text(value))
            elif kind == "term":
                term = self.terms[value]
                target = escape(term["target"])
                if value not in self.seen_terms:
                    self.seen_terms.add(value)
                    result.append(r"\BTFirstTerm{" + target + r"}\textsuperscript{" + str(term["number"]) + r"}\label{term:" + value + "}")
                else:
                    result.append(target)
            elif kind == "note":
                self.note_number += 1
                number = str(self.note_number)
                content = (r"\BTPosition{note:" + value + ":start}" + self.inline(self.notes[value]["target"]) +
                           r"\BTPosition{note:" + value + ":end}")
                result.append(r"\BTPosition{callout:" + value + "}")
                if deferred_notes is not None:
                    result.append(r"\footnotemark[" + number + "]")
                    deferred_notes.append(r"\footnotetext[" + number + "]{" + content + "}")
                else:
                    result.append(r"\footnote[" + number + "]{" + content + "}")
            elif kind == "page":
                self.emitted_source_pages.add(value)
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
            image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB").save(destination)
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
        # Normalize to a 100pt canvas to avoid TeX's 16384pt dimension ceiling.
        unit = 100 / max(width, height)
        canvas = [r"\setlength{\unitlength}{1pt}\begin{picture}(" + f"{width * unit:.8f},{height * unit:.8f})"]
        for image in images:
            path = self.asset(image["asset"])
            canvas.append(r"\put(" + f"{image['x'] * unit:.8f},{(height - image['y'] - image['height']) * unit:.8f}" +
                          r"){\includegraphics[width=" + f"{image['width'] * unit:.8f}pt,height={image['height'] * unit:.8f}pt" + "]{" + path + "}}")
        canvas.append(r"\end{picture}")
        self.images.append({"id": identifier, "kind": block["kind"], "canvas_width": width,
                            "canvas_height": height, "relation": block.get("relation"), "images": images})
        side = block.get("relation") in ("text-left", "text-right")
        start = r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:" + identifier + ":start}" + page_prefix + "\n"
        reservation = str(note_count) + r"\footnotesep-\skip\footins" if note_count else "0pt"
        start += r"\setlength{\BTAvailableHeight}{\dimexpr\textheight-" + reservation + r"\relax}" + "\n"
        image_box = r"\sbox{\BTImageBox}{" + "".join(canvas) + "}\n"
        if side:
            fraction = block["text_fraction"]
            text_width = f"{fraction:.8f}\\linewidth"
            image_width = f"{1 - fraction - .03:.8f}\\linewidth"
            text = r"\begin{minipage}[c]{" + text_width + "}\\noindent " + caption + r"\end{minipage}"
            image = (r"\begin{minipage}[c]{" + image_width + "}\n" + image_box +
                     r"\BTScaleCanvas\BTImageEvidence{" + identifier + "}\n" +
                     r"\leavevmode\BTPosition{canvas:" + identifier + r"}\usebox{\BTImageBox}\end{minipage}")
            pieces = [text, image] if block["relation"] == "text-left" else [image, text]
            content = r"\sbox{\BTTempBox}{" + r"\hfill".join(pieces) + "}\n"
            content += (r"\ifdim\dimexpr\ht\BTTempBox+\dp\BTTempBox\relax>\BTAvailableHeight"
                        r"\PackageError{book-translator}{Side-text group " + identifier +
                        r" exceeds a readable page; revise block boundaries while preserving source relationships}{}\fi" + "\n" + r"\usebox{\BTTempBox}")
        else:
            content = r"\sbox{\BTTextBox}{\begin{minipage}{\linewidth}\noindent " + caption + r"\par\end{minipage}}" + "\n"
            content += image_box + r"\setlength{\BTAvailableHeight}{\dimexpr\BTAvailableHeight-\ht\BTTextBox-\dp\BTTextBox-\baselineskip\relax}" + "\n"
            content += r"\ifdim\BTAvailableHeight<\baselineskip\PackageError{book-translator}{Image caption " + identifier + r" leaves no readable image space; revise block boundaries}{}\fi" + "\n"
            content += r"\BTScaleCanvas\BTImageEvidence{" + identifier + "}\n"
            content += r"\noindent\makebox[\linewidth][c]{\BTPosition{canvas:" + identifier + r"}\usebox{\BTImageBox}}\par\smallskip\usebox{\BTTextBox}"
        return start + content + r"\BTPosition{block:" + identifier + r":end}\end{minipage}\par" + "\n"

    def body(self) -> str:
        output = []
        for block in self.book["blocks"]:
            identifier, kind = block["id"], block["kind"]
            implicit = [page for page in block["source_pages"] if page not in self.emitted_source_pages and page not in self.explicit_source_pages]
            if implicit and (len(implicit) > 1 or implicit[0] != block["source_pages"][0]):
                raise ValueError(f"Block {identifier} has ambiguous source-page boundaries; add exact inline page tokens")
            page_prefix = self.inline([{"page": implicit[0]}]) if implicit else ""
            if implicit:
                self.source_marks[-1]["placement_basis"] = "Inferred from a single unambiguous block-start source page"
            deferred_notes = [] if kind in ("image", "group") else None
            target = self.inline(block["target"], deferred_notes=deferred_notes)
            start = r"\BTPosition{block:" + identifier + ":start}" + page_prefix
            end = r"\BTPosition{block:" + identifier + ":end}"
            if kind in ("image", "group"):
                output.append(self.image_block(block, target, page_prefix, len(deferred_notes)) + "".join(deferred_notes) + "\n")
            elif kind == "heading":
                output.append(r"\BTHeading{" + str(block["level"]) + "}{" + start + target + end + "}\n")
            elif kind == "paragraph":
                output.append(r"\par\noindent " + start + target + end + "\\par\n")
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

    def tex(self) -> str:
        agent_preface = self.inline(self.book["agent_preface"])
        human = self.book["human_preface"]
        human_preface = (r"\BTHeading{2}{Human preface}" + self.inline(human) + "\\par\\clearpage\n") if human else ""
        body = self.body()
        rows = []
        for term in sorted(self.terms.values(), key=lambda item: item["number"]):
            decision = " | ".join(term[key] for key in ("authority", "authority_locator", "rationale"))
            rows.append(str(term["number"]) + " & " + escape(term["source"]) + " & " + escape(term["target"]) +
                        " & " + escape(decision) + r" & \pageref{term:" + term["id"] + r"} \\")
        substitutions = {"TITLE": escape(self.book["title"]), "AGENT_PREFACE": agent_preface,
                         "HUMAN_PREFACE": human_preface, "BODY": body, "TERMS": "\n".join(rows),
                         "SOURCE_OVERLAYS": "\n".join(r"\BTSourceOverlay{" + item["key"] + "}{" + escape(item["display"]) + "}" for item in self.source_marks if item["display"] is not None)}
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
        "source_marks": renderer.source_marks, "images": renderer.images,
        "literal_files": renderer.literal_files,
        "blocks": [{"id": block["id"], "kind": block["kind"]} for block in book["blocks"]],
        "term_ids": list(renderer.terms), "note_ids": list(renderer.notes)})
    return destination


def _positions(aux: str) -> dict:
    positions = {}
    for key, body in re.findall(r"\\zref@newlabel\{([^}]+)\}\{([^\n]+)\}", aux):
        properties = {name: int(value) for name, value in re.findall(r"\\(posx|posy|abspage)\{(-?\d+)\}", body)}
        if len(properties) == 3:
            positions[key] = {"page": properties["abspage"], "x_pt": properties["posx"] / SP_PER_PT,
                              "y_from_bottom_pt": properties["posy"] / SP_PER_PT}
    return positions


def _verify(build_dir: Path, manifest: dict, log: str, aux: str) -> dict:
    import pymupdf
    errors = []
    checks = {name: True for name in ("compiler", "pdf_geometry", "preface", "source_boundaries", "image_relations", "footnotes", "references", "overflow")}
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
        page_evidence.append({"page": number, "width_pt": size[0], "height_pt": size[1],
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
    dimensions = {identifier: (int(w) / SP_PER_PT, int(h) / SP_PER_PT)
                  for identifier, w, h in re.findall(r"BTIMAGE\|([^|\s]+)\|(\d+)\|(\d+)", log)}
    for canvas in manifest["images"]:
        origin = position("canvas:" + canvas["id"], "image_relations")
        if not origin or canvas["id"] not in dimensions:
            fail("image_relations", f"Missing compiled image canvas {canvas['id']}")
            continue
        width, height = dimensions[canvas["id"]]
        if abs(width / height - canvas["canvas_width"] / canvas["canvas_height"]) > .001:
            fail("image_relations", f"Image canvas {canvas['id']} lost its aspect ratio")
        page = document[origin["page"] - 1]
        actual = [pymupdf.Rect(item["bbox"]) for item in page.get_image_info()]
        rectangles = []
        scale = width / canvas["canvas_width"]
        # A savepos inside the image hbox records its actual bottom-left origin.
        top = page.rect.height - origin["y_from_bottom_pt"] - height
        for image in canvas["images"]:
            expected = pymupdf.Rect(origin["x_pt"] + image["x"] * scale, top + image["y"] * scale,
                                 origin["x_pt"] + (image["x"] + image["width"]) * scale,
                                 top + (image["y"] + image["height"]) * scale)
            match = next((rect for rect in actual if max(abs(a - b) for a, b in zip(rect, expected)) < .6), None)
            if match is None:
                fail("image_relations", f"Image {image['asset']} in {canvas['id']} changed its source offset, gap, or relative geometry")
            if expected.x0 < (inner if origin["page"] % 2 else outer) * PT_PER_MM - .7 or expected.x1 > page.rect.width - (outer if origin["page"] % 2 else inner) * PT_PER_MM + .7 or expected.y0 < layout["top_mm"] * PT_PER_MM - .7 or expected.y1 > page.rect.height - layout["bottom_mm"] * PT_PER_MM + .7:
                fail("image_relations", f"Image {canvas['id']} exceeds the A5 text area")
            rectangles.append({"asset": image["asset"], "expected_rect_pt": list(expected), "pdf_rect_pt": list(match) if match else None})
        images.append({"id": canvas["id"], **origin, "width_pt": width, "height_pt": height, "rectangles": rectangles})
    term_pages = {}
    for identifier in manifest["term_ids"]:
        match = re.search(r"\\newlabel\{term:" + re.escape(identifier) + r"\}\{\{[^}]*\}\{(\d+)\}", aux)
        if not match:
            fail("references", f"Term {identifier} has no measured first-use page label")
        else:
            term_pages[identifier] = int(match[1])
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
        footnote_pages.append({"page": int(number), "height_pt": height, "maximum_pt": limit})
    notes = []
    for identifier in manifest["note_ids"]:
        start = position("note:" + identifier + ":start", "footnotes")
        end = position("note:" + identifier + ":end", "footnotes")
        callout = position("callout:" + identifier, "footnotes")
        if start and end and callout:
            if start["page"] != callout["page"]:
                fail("footnotes", f"Note {identifier} has no first footer line on its callout page")
            notes.append({"id": identifier, "callout": callout, "start": start, "end": end})
    if notes and not footnote_pages:
        fail("footnotes", "No real bottom-footnote insertion evidence was recorded")
    document.close()
    return {"checks": checks, "passed": all(checks.values()), "errors": errors, "pages": page_evidence,
            "agent_preface_pages": preface_pages, "source_marks": source_marks, "block_boundaries": boundaries,
            "images": images, "term_first_pages": term_pages, "footnote_pages": footnote_pages, "notes": notes, "compiled_geometry_pt": geometry}


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
