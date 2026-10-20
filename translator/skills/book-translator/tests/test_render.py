"""Real compiler and PDF layout tests; fixtures never claim model approval."""
from __future__ import annotations

import copy
import hashlib
import math
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core
import render


def make_job(root: Path) -> Path:
    """Create a sealed, synthetic representative rendering job at root."""
    from PIL import Image, ImageDraw
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source.txt").write_text("Synthetic source evidence for renderer tests, not a real translation.\n", encoding="utf-8")
    for filename, color in (("first.png", "#1964a6"), ("second.png", "#cb7822")):
        image = Image.new("RGB", (160, 80), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 156, 76), outline="white", width=3)
        draw.text((12, 30), filename, fill="white")
        image.save(root / filename)
    Image.new("RGB", (100, 900), "#54865b").save(root / "tall.png")
    job = {"version": 1, "title": "Synthetic book", "source_language": "en", "target_language": "zh-Hans",
           "source_file": "source.txt", "source_sha256": hashlib.sha256((root / "source.txt").read_bytes()).hexdigest(),
           "max_rounds": 3, "round": 0, "state": "initialized", "history": [],
           "models": {"terminology": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                      "translation": {"provider": "anthropic", "model": "claude-sonnet-4-6"}},
           "layout": {"paper": "a5", "outer_mm": 8, "inner_min_mm": 20,
                      "top_mm": 15, "bottom_mm": 15, "source_mark_edge_mm": 3}}
    protected = [{"id": "Name", "kind": "name", "value": "Fourier"},
                 {"id": "Formula", "kind": "math", "value": r"E = mc^{2}"},
                 {"id": "Code", "kind": "code", "value": "# Keep this comment exactly: 100% & _\nvalue = 3  # inline comment\n\tprint(value)\n"}]
    blocks = []
    def block(identifier, kind, pages, source, target, **fields):
        blocks.append({"id": identifier, "kind": kind, "source_pages": pages,
                       "source": source, "target": target, **fields})
    block("Chapter", "heading", ["P1"], [{"text": "Source chapter"}],
          [{"text": "Representative chapter \u4e2d\u6587"}], level=1)
    block("Intro", "paragraph", ["P1", "P2"],
          [{"protected": "Name"}, {"text": " method and original first page. "}, {"page": "P2"},
           {"text": "The next original page begins inside this paragraph."}, {"note": "LongNote"}],
          [{"term": "Method"}, {"text": " preserves its original name. The exact original boundary is here: "},
           {"page": "P2"}, {"text": "\u8fd9\u662f\u7ffb\u8bd1\u6587\u672c\u3002 100% & # _ { } $ ~ ^ \\ are literal text. "},
           {"note": "LongNote"}, {"text": " The body continues after its note callout. " + "A readable body sentence continues the discussion. " * 30}])
    block("FormulaBlock", "display_math", ["P2"],
          [{"text": "The displayed formula is "}, {"protected": "Formula"}, {"text": "."}],
          [{"text": "The displayed formula is "}, {"protected": "Formula"}, {"text": "."}], protected_id="Formula")
    block("CodeBlock", "code", ["P2"], [{"text": "Literal reviewed source code."}], [{"text": "Literal reviewed source code."}], protected_id="Code")
    for index in range(5):
        original = ([{"protected": "Name"}, {"text": " method. "}] if index == 0 else [])
        translated = ([{"term": "Method"}, {"text": " appears again without first-use emphasis. "}] if index == 0 else [])
        block("Paragraph" + str(index), "paragraph", ["P2"], original + [{"text": "Source discussion. " * 15}],
              translated + [{"text": "Additional translated discussion keeps the pagination representative. " * 12}])
    block("ImageChapter", "heading", ["P3"], [{"page": "P3"}, {"text": "Original unnumbered page."}],
          [{"page": "P3"}, {"text": "Images and source relationships"}], level=1)
    group_images = [{"asset": "first.png", "x": 20, "y": 15, "width": 80, "height": 40},
                    {"asset": "second.png", "x": 125, "y": 55, "width": 60, "height": 30}]
    block("OffsetGroup", "group", ["P3"], [{"text": "Two offset source images."}, {"note": "CaptionNote"}],
          [{"text": "A caption retaining the exact offsets and gaps."}, {"note": "CaptionNote"}],
          relation="row", images=group_images, canvas_width=220, canvas_height=110, text_fraction=.5, source_em=16, scale_evidence="Synthetic source body font is 16 source units.")
    block("SideGroup", "group", ["P3"], [{"text": "Source side text."}],
          [{"text": "Side text stays beside the entire source canvas. " * 4}],
          relation="text-left", images=copy.deepcopy(group_images), canvas_width=220, canvas_height=110, text_fraction=.5, source_em=16, scale_evidence="Synthetic source body font is 16 source units.")
    block("TallImage", "image", ["P3"], [{"text": "Source tall image."}, {"note": "TallNote"}],
          [{"text": "The tall source image keeps its font-relative scale, never cropped or split."}, {"note": "TallNote"}], asset="tall.png", width=100, height=900, source_em=24, scale_evidence="Synthetic source body font is 24 source units.")
    notes = [{"id": "LongNote", "content_type": "prose", "source": [{"text": "A long source note. " * 100}],
              "target": [{"term": "Footer"}, {"text": ". " + "The long note continues in the following bottom footer without truncation. " * 100 + " FOOTNOTE-END"}]},
             {"id": "CaptionNote", "content_type": "prose", "source": [{"text": "Caption note."}],
              "target": [{"text": "A caption note belongs at the real page bottom, not inside the image canvas."}]},
             {"id": "TallNote", "content_type": "prose", "source": [{"text": "Tall source image note."}],
              "target": [{"text": "The oversized image leaves room for this bottom footer."}]}]
    book = {"version": 2, "main_body_start": "Chapter", "title": "Synthetic layout evidence", "source_pages": [
        {"id": "P1", "locator": "synthetic:1", "printed_label": "xii", "label_verified": True, "evidence": "Reviewed synthetic label xii."},
        {"id": "P2", "locator": "synthetic:2", "printed_label": "A-7", "label_verified": True, "evidence": "Reviewed synthetic label A-7."},
        {"id": "P3", "locator": "synthetic:3", "printed_label": None, "label_verified": False, "evidence": "Synthetic unnumbered source page."}],
        "protected": protected, "blocks": blocks, "notes": notes,
        "agent_preface": [{"text": "This synthetic machine-translation fixture uses reviewed terminology and literal protected content. Its source is synthetic and has no OCR uncertainty. No model translation or semantic review is claimed. The review status is unapproved."}],
        "human_preface": [{"text": "This separate synthetic human-preface slot does not count toward the agent-preface page limit."}]}
    terms = {"version": 1, "terms": [
        {"id": "Method", "number": 1, "source": "Fourier method", "target": "Fourier \u65b9\u6cd5", "authority": "Synthetic field consensus", "authority_locator": "Fixture decision 1", "rationale": "Preserve the original name.", "protected_ids": ["Name"]},
        {"id": "Footer", "number": 2, "source": "footer evidence", "target": "footer evidence", "authority": "Synthetic field consensus", "authority_locator": "Fixture decision 2", "rationale": "Used first inside a footnote.", "protected_ids": []}]}
    source = copy.deepcopy(book)
    source["agent_preface"] = []
    source["human_preface"] = None
    for item in source["blocks"] + source["notes"]:
        item["target"] = []
    core.save_json(root / "job.json", job)
    core.save_json(root / "book-source.json", source)
    core.save_json(root / "terms.json", terms)
    core.seal_source(root)
    core.save_json(root / "book.json", book)
    return root


def make_inline_job(root: Path) -> Path:
    """Seal an independent synthetic PDF source with inline raster mathematics."""
    import pymupdf
    from PIL import Image, ImageDraw
    root = make_job(root)
    for filename, expression, transparent in (("glyph-x.png", "x + 1", False), ("glyph-y.png", "y - 2", True)):
        image = Image.new("RGBA" if transparent else "RGB", (80, 40), (255, 255, 255, 0) if transparent else "white")
        ImageDraw.Draw(image).text((10, 12), expression, fill="black")
        image.save(root / filename)
    with pymupdf.open() as source_pdf:
        page = source_pdf.new_page(width=148 * render.PT_PER_MM, height=210 * render.PT_PER_MM)
        page.insert_text((50, 70), "Synthetic inline source, not a translation.")
        page.insert_text((50, 100), "Before")
        page.insert_image(pymupdf.Rect(90, 90, 110, 100), filename=root / "glyph-x.png")
        page.insert_text((115, 100), "middle")
        page.insert_image(pymupdf.Rect(150, 90, 170, 100), filename=root / "glyph-y.png")
        page.insert_text((175, 100), "after; the note also retains raster mathematics.")
        source_pdf.save(root / "inline-source.pdf")
    def image(asset, width, raise_em):
        return {"image": {"asset": asset, "width_em": width, "height_em": width / 2, "raise_em": raise_em}}
    heading = [{"text": "HeadingBefore "}, image("glyph-x.png", 2.4, -.1), {"text": " HeadingAfter"}]
    body = [{"text": "BodyBefore "}, image("glyph-x.png", 2, -.2), {"text": " BodyMiddle "},
            image("glyph-y.png", 1.6, .25), {"text": " BodyAfter"}, {"note": "InlineNote"}]
    note = [{"text": "NoteBefore "}, image("glyph-y.png", 1.2, -.15), {"text": " NoteAfter"}]
    book = {"version": 2, "main_body_start": "InlineHeading", "title": "Synthetic inline mathematics", "source_pages": [
        {"id": "InlineSource", "locator": "inline-source.pdf:1", "printed_label": None,
         "label_verified": False, "evidence": "Synthetic native source PDF with two unchanged raster glyph assets."}],
        "protected": [], "blocks": [
            {"id": "InlineHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"], "source": heading, "target": copy.deepcopy(heading)},
            {"id": "InlineBody", "kind": "paragraph", "source_pages": ["InlineSource"], "source": body, "target": copy.deepcopy(body)}],
        "notes": [{"id": "InlineNote", "content_type": "prose", "source": [{"text": "Original source explanation "}, image("glyph-y.png", 1.2, -.15), {"text": " surrounding a formula."}], "target": copy.deepcopy(note)}],
        "agent_preface": [{"text": "Synthetic raster geometry evidence only. No model translation, terminology authority, or semantic review is claimed."}],
        "human_preface": None}
    source = copy.deepcopy(book)
    source["agent_preface"] = []
    for item in source["blocks"] + source["notes"]:
        item["target"] = []
    job = core.load_json(root / "job.json")
    job.update(source_file="inline-source.pdf", source_sha256=hashlib.sha256((root / "inline-source.pdf").read_bytes()).hexdigest())
    core.save_json(root / "job.json", job)
    core.save_json(root / "book-source.json", source)
    core.save_json(root / "terms.json", {"version": 1, "terms": []})
    core.save_json(root / "book.json", book)
    core.seal_source(root)
    return root



def make_inline_caption_job(root: Path, relation: str | None = None) -> Path:
    """Keep the inline source tokens unchanged inside a real boxed caption."""
    root = make_inline_job(root)
    for filename in ("book-source.json", "book.json"):
        manuscript = core.load_json(root / filename)
        caption = manuscript["blocks"][1]
        if relation is None:
            caption.update(kind="image", asset="first.png", width=160, height=80, source_em=12, scale_evidence="Synthetic source body font is 12 source units.")
        else:
            caption.update(kind="group", relation=relation, canvas_width=220, canvas_height=110, source_em=16, scale_evidence="Synthetic source body font is 16 source units.",
                           text_fraction=.5, images=[
                               {"asset": "first.png", "x": 20, "y": 15, "width": 80, "height": 40},
                               {"asset": "second.png", "x": 125, "y": 55, "width": 60, "height": 30}])
        core.save_json(root / filename, manuscript)
    core.seal_source(root)
    return root


def make_graphic_boundary_job(root: Path, relation: str | None = None, *, implicit: bool = False) -> Path:
    """Retain a leading graphic boundary plus a distinct internal caption boundary."""
    root = make_inline_caption_job(root, relation)
    for filename in ("book-source.json", "book.json"):
        manuscript = core.load_json(root / filename)
        manuscript["source_pages"] += [
            {"id": "GraphicStart", "locator": "synthetic:graphic", "printed_label": "47",
             "label_verified": True, "evidence": "Synthetic graphic-start label."},
            {"id": "CaptionNext", "locator": "synthetic:caption", "printed_label": "48",
             "label_verified": True, "evidence": "Synthetic internal-caption label."}]
        block = manuscript["blocks"][1]
        block["source_pages"] = ["GraphicStart", "CaptionNext"]
        fields = ("source", "target") if filename == "book.json" else ("source",)
        for field in fields:
            tokens = block[field]
            prefix = [] if implicit else [{"page": "GraphicStart"}]
            block[field] = prefix + tokens[:3] + [{"page": "CaptionNext"}] + tokens[3:]
        core.save_json(root / filename, manuscript)
    core.seal_source(root)
    return root



def make_restoration_job(root: Path, *, status: str = "conjectural") -> Path:
    """Generate damaged-source pixels and a disclosed reconstruction, without model inference."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont
    root = make_inline_job(root)
    image = Image.new("RGB", (280, 40), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=20)
    draw.text((12, 8), "development", font=font, fill="black")
    image.save(root / "intact.png")
    left = 12 + int(draw.textlength("devel", font=font))
    right = 12 + int(draw.textlength("develo", font=font))
    draw.rectangle((left, 5, right, 32), fill="white")
    image.save(root / "damage.png")
    with pymupdf.open() as source_pdf:
        page = source_pdf.new_page(width=148 * render.PT_PER_MM, height=210 * render.PT_PER_MM)
        page.insert_text((50, 70), "Synthetic damaged source evidence; no real-book reconstruction claim.")
        page.insert_text((50, 100), "The compiler's " + chr(34))
        page.insert_image(pymupdf.Rect(130, 88, 270, 108), filename=root / "damage.png")
        page.insert_text((270, 100), chr(34) + "--process.")
        source_pdf.save(root / "restoration-source.pdf")
    fragment = 'The compiler\'s "devel[gap]pment"--process.'
    crop = {"image": {"asset": "damage.png", "width_em": 14, "height_em": 2, "raise_em": 0}}
    book = core.load_json(root / "book.json")
    book.update(title="Synthetic disclosed source reconstruction", main_body_start="RestorationChapter", protected=[],
                blocks=[{"id": "RestorationChapter", "kind": "heading", "level": 1, "source_pages": ["InlineSource"],
                         "source": [{"text": "Damaged source reconstruction"}], "target": [{"text": "\u635f\u574f\u539f\u6587\u91cd\u5efa"}]},
                        {"id": "RestorationBody", "kind": "paragraph", "source_pages": ["InlineSource"],
                         "source": [{"text": "The compiler's \"development"}, {"note": "DamageNote"}, {"text": "\"--process."}],
                         "target": [{"text": "\u7f16\u8bd1\u5668\u7684\u5f00\u53d1"}, {"note": "DamageNote"}, {"text": "\u8fc7\u7a0b\u4fdd\u7559\u4e86\u539f\u59cb\u635f\u574f\u8bc1\u636e\u3002"}]}],
                notes=[{"id": "DamageNote", "content_type": "prose",
                        "restoration": {"source_page": "InlineSource", "original_fragment": fragment, "replacement": "development",
                                        "status": status, "evidence": "restoration-source.pdf:1 shows the damaged raster; intact.png retains the generated authored word before erasure. This is synthetic fixture evidence, not a real edition.",
                                        "damage_asset": "damage.png"},
                        "source_evidence": [{"asset": "damage.png", "source_page": "InlineSource", "description": "Exact generated source raster at PDF bbox [130,88,270,108], with erased source pixels unchanged."},
                                            {"asset": "intact.png", "source_page": "InlineSource", "description": "Synthetic authored witness before erasure, retained for audit only and never rendered."}],
                        "source": [{"text": "Editorial completion. Original fragment: "},
                                   {"text": fragment}, copy.deepcopy(crop)],
                        "target": [{"text": "\u6b64\u5904\u4e3a\u8865\u5168\u3002\u539f\u6587\u6b8b\u7247\uff1a"},
                                   {"text": fragment}, copy.deepcopy(crop)]}])
    book["source_pages"][0].update(locator="restoration-source.pdf:1", evidence="Generated source page contains the exact damaged word raster; synthetic fixture only.")
    source = copy.deepcopy(book)
    source["agent_preface"] = []
    for item in source["blocks"] + source["notes"]:
        item["target"] = []
    job = core.load_json(root / "job.json")
    job.update(source_file="restoration-source.pdf", source_sha256=hashlib.sha256((root / "restoration-source.pdf").read_bytes()).hexdigest())
    core.save_json(root / "job.json", job)
    core.save_json(root / "book-source.json", source)
    core.save_json(root / "book.json", book)
    core.seal_source(root)
    return root



def make_flow_job(root: Path, *, front_heading: bool = False) -> Path:
    """Create a synthetic book spanning physical sides with structured nested lists."""
    root = make_inline_job(root)
    book = core.load_json(root / "book.json")
    blocks = []
    def add(identifier, kind, text, **fields):
        blocks.append({"id": identifier, "kind": kind, "source_pages": ["InlineSource"],
                       "source": [{"text": "Original source " + text}], "target": [{"text": text}], **fields})
    if front_heading:
        add("FrontHeading", "heading", "Front source chapter", level=1)
        add("FrontText", "paragraph", "Front matter is not assigned a printed body page.")
    add("BodyChapter", "heading", "Body chapter", level=1)
    add("SectionOne", "heading", "First section", level=2)
    add("AfterHeading", "paragraph", "Indented after heading. " + "Ordinary flowing prose remains readable. " * 10)
    for identifier, label, depth, kind in (("Ordered", "7.", 0, "ordered"), ("Bullet", "\u2022", 1, "unordered"), ("Nested", "(iv)", 2, "ordered")):
        add(identifier, "list_item", identifier + " continuation content uses a hanging indent. " * 8,
            list_type=kind, list_level=depth, label=label)
    add("Subsection", "heading", "Not a running section", level=3)
    for index in range(10):
        add("Flow" + str(index), "paragraph", "Flowing body paragraph. " + "Readable body text follows the section and preserves layout. " * 18)
    add("NextChapter", "heading", "Next chapter", level=1)
    add("NextText", "paragraph", "The new chapter clears the previous section. " * 10)
    book.update(blocks=blocks, notes=[], main_body_start="BodyChapter", human_preface=None)
    source = copy.deepcopy(book)
    source["agent_preface"] = []
    for block in source["blocks"]:
        block["target"] = []
    core.save_json(root / "book-source.json", source)
    core.save_json(root / "book.json", book)
    core.seal_source(root)
    return root


def make_graphic_fit_job(root: Path, relation: str | None = "row") -> Path:
    """Create oversized synthetic artwork with explicit output-only fit evidence."""
    root = make_graphic_boundary_job(root, relation)
    side = relation in ("text-left", "text-right")
    source_em = 8 if side else 4 if relation is None else 5
    scale = .5 if side else .8 if relation is None else .7
    for filename in ("book-source.json", "book.json"):
        manuscript = core.load_json(root / filename)
        manuscript["blocks"][1]["source_em"] = source_em
        manuscript["blocks"][1]["scale_evidence"] = f"Synthetic source body font is {source_em} source units."
        core.save_json(root / filename, manuscript)
    core.seal_source(root)
    manuscript = core.load_json(root / "book.json")
    manuscript["blocks"][1]["fit"] = {
        "scale": scale, "min_scale": scale,
        "legibility_evidence": "Synthetic layout-fixture threshold only; real artwork labels and details require independent actual-size PDF review."}
    core.save_json(root / "book.json", manuscript)
    return root


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-render-test-")
        self.job = make_job(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for term-marker attachment")
    def test_first_use_superscript_stays_with_wrapping_term_tail(self):
        import pymupdf
        job = make_inline_job(self.job / "term-marker-attachment")
        book = core.load_json(job / "book.json")
        book.update(protected=[], notes=[], main_body_start="MarkerHeading", blocks=[
            {"id": "MarkerHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Synthetic marker attachment"}], "target": [{"text": "Synthetic marker attachment"}]}])
        terms = []
        for index, prefix_length in enumerate((17, 18, 19, 20, 21, 0)):
            identifier = "Marker" + str(index)
            target = ("\u8fd9\u662f\u5408\u6210\u4e13\u7528\u672f\u8bed\uff08VDSM\uff09" if prefix_length else "\u4e59" * 50 + "\u672b")
            prefix = "A " * prefix_length
            terms.append({"id": identifier, "number": index + 12, "source": "Synthetic marker case " + str(index),
                          "target": target, "authority": "Synthetic typography fixture", "authority_locator": "Fixture only",
                          "rationale": "Exercise line-edge marker attachment without boxing the term.", "protected_ids": []})
            book["blocks"].append({"id": identifier, "kind": "paragraph", "source_pages": ["InlineSource"],
                                   "source": [{"text": prefix + target + " Marker remains attached."}],
                                   "target": [{"text": prefix}, {"term": identifier}, {"text": " Marker remains attached."}]})
        source = copy.deepcopy(book)
        source["agent_preface"] = []
        for block in source["blocks"]:
            block["target"] = []
        core.save_json(job / "book-source.json", source)
        core.save_json(job / "book.json", book)
        core.save_json(job / "terms.json", {"version": 1, "terms": terms})
        core.seal_source(job)
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        typography = {row["id"]: row for row in report["typography"]}
        with pymupdf.open(pdf) as document:
            for term in terms:
                with self.subTest(term=term["id"]):
                    row = typography[term["id"]]
                    self.assertEqual(row["start"]["page"], row["end"]["page"])
                    page = document[row["start"]["page"] - 1]
                    first = page.rect.height - row["start"]["y_from_bottom_pt"]
                    last = page.rect.height - row["end"]["y_from_bottom_pt"]
                    em = row["font_em_pt"]
                    chars = [(char, span) for block in page.get_text("rawdict")["blocks"]
                             for line in block.get("lines", []) for span in line["spans"] for char in span["chars"]
                             if first - .3 <= char["origin"][1] <= last + .3 and "Bold" in span["font"]]
                    tails = [char for char, span in chars if char["c"] == term["target"][-1] and abs(span["size"] - em) < .1]
                    self.assertEqual(len(tails), 1)
                    tail = tails[0]
                    markers = [span for block in page.get_text("dict")["blocks"]
                               for line in block.get("lines", []) for span in line["spans"]
                               if span["text"] == str(term["number"]) and span["size"] < em - .5
                               and -.3 < span["origin"][0] - tail["origin"][0] < 2 * em
                               and .1 < tail["origin"][1] - span["origin"][1] < em]
                    self.assertEqual(len(markers), 1, "The superscript must be raised beside the term tail, never on the next line")
                    if term is terms[-1]:
                        self.assertGreater(len({round(char["origin"][1], 1) for char, _ in chars}), 1)

    def title_glyphs(self, page):
        spans = [span for block in page.get_text("dict")["blocks"]
                 for line in block.get("lines", []) for span in line["spans"]]
        title_size = max(span["size"] for span in spans)
        large = [span for span in spans if abs(span["size"] - title_size) < .1]
        baselines = sorted({round(span["origin"][1], 1) for span in large})
        last = baselines[0]
        for baseline in baselines[1:]:
            if baseline - last > 2 * title_size:
                break
            last = baseline
        return [span for span in large if span["origin"][1] <= last + .1]

    def assert_mirrored_geometry(self, pdf, report, *, inner_mm, outer_mm=8, top_mm=15, bottom_mm=15):
        import pymupdf
        geometry = report["compiled_geometry_pt"]
        measured = {
            "paper_width": geometry["paper_width"],
            "paper_height": geometry["paper_height"],
            "odd_inner": geometry["odd_left"],
            "odd_outer": geometry["paper_width"] - geometry["odd_left"] - geometry["text_width"],
            "even_inner": geometry["paper_width"] - geometry["even_left"] - geometry["text_width"],
            "even_outer": geometry["even_left"],
            "top": geometry["top"],
            "bottom": geometry["paper_height"] - geometry["top"] - geometry["text_height"],
        }
        expected_mm = {"paper_width": 148, "paper_height": 210,
                       "odd_inner": inner_mm, "odd_outer": outer_mm,
                       "even_inner": inner_mm, "even_outer": outer_mm,
                       "top": top_mm, "bottom": bottom_mm}
        for name, expected in expected_mm.items():
            with self.subTest(margin=name):
                self.assertAlmostEqual(measured[name] / render.PT_PER_MM, expected, delta=.07)
        rule_width = .4 * (148 - inner_mm - outer_mm) * render.PT_PER_MM
        footer_parities = set()
        with pymupdf.open(pdf) as document:
            self.assertEqual(len(document), len(report["pages"]))
            for page in document:
                self.assertAlmostEqual(page.rect.width / render.PT_PER_MM, 148, delta=.1)
                self.assertAlmostEqual(page.rect.height / render.PT_PER_MM, 210, delta=.1)
            for footer in report["footnote_pages"]:
                number = footer["page"]
                page = document[number - 1]
                left_mm = inner_mm if number % 2 else outer_mm
                rules = [drawing["rect"] for drawing in page.get_drawings()
                         if drawing["rect"].height < .8
                         and abs(drawing["rect"].width - rule_width) < 1
                         and drawing["rect"].y0 > page.rect.height / 2]
                self.assertEqual(len(rules), 1, f"Expected one visible footer separator on page {number}")
                self.assertAlmostEqual(rules[0].x0 / render.PT_PER_MM, left_mm, delta=.1)
                footer_parities.add(number % 2)
        self.assertEqual(footer_parities, {0, 1})

    def glossary_cell(self, job, document, identifier, column):
        """Read the actual four-column row from saved physical PDF coordinates."""
        import pymupdf
        positions = render._positions((job / "build/book.aux").read_text())
        row = positions["glossary:" + identifier]
        page = document[row["page"] - 1]
        layout = core.load_json(job / "job.json")["layout"]
        left = (layout["inner_min_mm"] if row["page"] % 2 else layout["outer_mm"]) * render.PT_PER_MM
        width = (148 - layout["inner_min_mm"] - layout["outer_mm"]) * render.PT_PER_MM
        padding = 6 * 72 / 72.27
        table_width = width - 6 * padding
        fractions = (.08, .32, .34, .26)
        x = left + sum(fractions[:column]) * table_width + column * 2 * padding
        baseline = page.rect.height - row["y_from_bottom_pt"]
        following = [point for key, point in positions.items() if key.startswith("glossary:") and
                     key != "glossary:start" and point["page"] == row["page"] and point["y_from_bottom_pt"] < row["y_from_bottom_pt"] - .5]
        last = min((page.rect.height - point["y_from_bottom_pt"] - 12 for point in following), default=page.rect.height - layout["bottom_mm"] * render.PT_PER_MM)
        cell = pymupdf.Rect(x - .3, baseline - 12, x + fractions[column] * table_width + .3, last)
        lines = [line for block in page.get_text("rawdict", clip=cell)["blocks"] for line in block.get("lines", [])
                 if line["spans"][0]["origin"][1] >= baseline - .2]
        actual = "".join(char["c"] for line in lines for span in line["spans"] for char in span["chars"])
        return actual, lines, cell


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for exact metadata glyph evidence")
    def test_compiled_data_fields_keep_quotes_dashes_and_specials_without_changing_prose(self):
        import pymupdf
        terms = core.load_json(self.job / "terms.json")
        term = terms["terms"][1]
        alias = "Writer's -- \"Rule\""
        term.update(source=alias, target="Owner's ``rule'' --- test",
                    authority="Literal 'single' \"double\" `tick` -- --- \u2018curly\u2019 \u2013 \u2014.",
                    authority_locator=r"https://example.test/a--b?q='x'&v=\"y\"#part_1%20z",
                    rationale=r"Keep 100% & # _ { } $ ~ ^ \input{not-a-file} and ``double'' quotes.")
        core.save_json(self.job / "terms.json", terms)
        title = alias + " | ``Label'' --- END"
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(self.job / filename)
            manuscript["title"] = title
            manuscript["source_pages"][1]["printed_label"] = "A--7"
            if filename == "book.json":
                manuscript["title_terms"] = [{"term": "Footer", "start": 0, "end": len(alias)}]
                manuscript["blocks"][5]["target"] += [{"text": " Ordinary -- prose 'quoted'."}]
            core.save_json(self.job / filename, manuscript)
        core.seal_source(self.job)
        inputs = {name: (self.job / name).read_bytes() for name in
                  ("book.json", "book-source.json", "terms.json", "source.sha256")}
        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertTrue(all(report["checks"].values()), report["errors"])
        self.assertEqual(inputs, {name: (self.job / name).read_bytes() for name in inputs})
        self.assertEqual(report["term_first_pages"]["Footer"], 1)
        with pymupdf.open(pdf) as document:
            title_spans = self.title_glyphs(document[0])
            actual_title = "".join(span["text"] for span in title_spans)
            self.assertEqual(re.sub(r"\s+", "", actual_title), re.sub(r"\s+", "", title))
            text = "\n".join(page.get_text() for page in document)
            self.assertIn("Ordinary\u2013prose\u2019quoted\u2019.", re.sub(r"\s+", "", text))
            appendix = document[-1]
            for header in ("\u5e8f\u53f7", "\u539f\u6587", "\u8bd1\u6587", "\u9996\u6b21\u51fa\u73b0\u9875"):
                self.assertIn(header, "".join(appendix.get_text().split()))
            for field, column in (("source", 1), ("target", 2)):
                actual, lines, _ = self.glossary_cell(self.job, document, "Footer", column)
                self.assertEqual("".join(actual.split()), "".join(term[field].split()))
                for line in lines:
                    for span in line["spans"]:
                        self.assertAlmostEqual(span["size"], 9 * 72 / 72.27, delta=.05)
            for field in ("authority", "authority_locator", "rationale"):
                self.assertNotIn("".join(term[field].split()), "".join(text.split()))
                self.assertEqual(core.load_json(self.job / "terms.json")["terms"][1][field], term[field])


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for graphic-start geometry")
    def test_compiled_graphic_starts_follow_page_fit_and_keep_internal_caption_boundaries(self):
        from unittest.mock import patch
        import pymupdf
        original = render._Renderer.body
        def move_group(renderer):
            carrier = (r"\noindent\begin{minipage}[t][.86\textheight][t]{\linewidth}"
                       r"Synthetic page-fit carrier.\end{minipage}\par" + "\n")
            tex = original(renderer)
            return tex.replace(r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:InlineBody:start}",
                               carrier + r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:InlineBody:start}")
        for relation in (None, "row", "column", "text-left", "text-right"):
            for moved in (False, True):
                with self.subTest(relation=relation, moved=moved):
                    job = make_graphic_boundary_job(self.job / ((relation or "image") + str(moved)), relation)
                    inputs = {name: (job / name).read_bytes() for name in
                              ("book.json", "book-source.json", "terms.json", "source.sha256")}
                    with patch.object(render._Renderer, "body", move_group if moved else original):
                        pdf = render.build(job)
                    report = core.load_json(job / "build/verification.json")
                    manifest = core.load_json(job / "build/render-manifest.json")
                    self.assertTrue(all(report["checks"].values()), report["errors"])
                    self.assertEqual(inputs, {name: (job / name).read_bytes() for name in inputs})
                    self.assertEqual([mark["source_page"] for mark in report["source_marks"]],
                                     ["InlineSource", "GraphicStart", "CaptionNext"])
                    graphic = report["graphic_boundaries"][0]
                    leading, internal = report["source_marks"][1:]
                    canvas = report["images"][0]
                    self.assertEqual(leading["page"], canvas["page"])
                    self.assertEqual(canvas["page"], report["agent_preface_pages"][-1] + 1 + int(moved))
                    self.assertEqual(internal["page"], canvas["page"])
                    for top in graphic["expected_top_pt"]:
                        self.assertAlmostEqual(leading["baseline_from_top_pt"], top, delta=.05)
                    self.assertGreater(internal["baseline_from_top_pt"], leading["baseline_from_top_pt"] + 6)
                    self.assertEqual([image["location"] for image in manifest["inline_images"]
                                      if image["container"] == "blocks.InlineBody.target"],
                                     ["blocks.InlineBody.target[2].image", "blocks.InlineBody.target[5].image"])
                    self.assertEqual(report["notes"][0]["start"]["page"], report["notes"][0]["callout"]["page"])
                    with pymupdf.open(pdf) as document:
                        page = document[canvas["page"] - 1]
                        self.assertTrue(page.search_for("BodyBefore"))
                        self.assertTrue(page.search_for("BodyAfter"))

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for boundary-negative evidence")
    def test_correct_outer_label_at_caption_baseline_fails_graphic_geometry(self):
        from unittest.mock import patch
        original = render._Renderer.image_block
        for relation in (None, "text-left", "text-right"):
            with self.subTest(relation=relation):
                job = make_graphic_boundary_job(self.job / (relation or "caption-mutation"), relation)
                for filename in ("book-source.json", "book.json"):
                    manuscript = core.load_json(job / filename)
                    manuscript["source_pages"] = [page for page in manuscript["source_pages"] if page["id"] != "CaptionNext"]
                    block = manuscript["blocks"][1]
                    block["source_pages"] = ["GraphicStart"]
                    for field in (("source", "target") if filename == "book.json" else ("source",)):
                        block[field] = [token for token in block[field] if token.get("page") != "CaptionNext"]
                    core.save_json(job / filename, manuscript)
                core.seal_source(job)
                def misplaced(renderer, block, caption, page_prefix, note_count):
                    return original(renderer, block, page_prefix + caption, "", note_count)
                with patch.object(render._Renderer, "image_block", misplaced):
                    with self.assertRaisesRegex(ValueError, "not at graphic start"):
                        render.build(job)
                report = core.load_json(job / "build/verification.json")
                self.assertFalse(report["checks"]["source_boundaries"])
                self.assertTrue(all(value for key, value in report["checks"].items() if key != "source_boundaries"), report["errors"])
                self.assertTrue(all("not at graphic start" in error for error in report["errors"]), report["errors"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for implicit graphic-start evidence")
    def test_implicit_graphic_start_and_later_page_at_caption_start_remain_distinct(self):
        job = make_graphic_boundary_job(self.job / "implicit-caption", "row", implicit=True)
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(job / filename)
            block = manuscript["blocks"][1]
            for field in (("source", "target") if filename == "book.json" else ("source",)):
                boundary = next(token for token in block[field] if "page" in token)
                block[field] = [boundary] + [token for token in block[field] if "page" not in token]
            core.save_json(job / filename, manuscript)
        core.seal_source(job)
        render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(all(report["checks"].values()), report["errors"])
        self.assertEqual([item["source_page"] for item in report["graphic_boundaries"]], ["GraphicStart"])
        leading, internal = report["source_marks"][1:]
        self.assertGreater(internal["baseline_from_top_pt"], leading["baseline_from_top_pt"] + 6)
        manifest = core.load_json(job / "build/render-manifest.json")
        self.assertIn("blocks.InlineBody.target[2].image", [image["location"] for image in manifest["inline_images"]])

    def test_inconsistent_leading_graphic_page_tokens_are_rejected_without_rewriting(self):
        job = make_graphic_boundary_job(self.job / "inconsistent-start", "column")
        manuscript = core.load_json(job / "book.json")
        tokens = manuscript["blocks"][1]["target"]
        tokens[0], tokens[1] = tokens[1], tokens[0]
        core.save_json(job / "book.json", manuscript)
        before = (job / "book.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "inconsistent leading source/target page tokens"):
            render.render(job)
        self.assertEqual((job / "book.json").read_bytes(), before)


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real inline geometry evidence")
    def test_compiled_inline_math_pixels_font_em_baseline_and_surrounding_text(self):
        import pymupdf
        job = make_inline_job(Path(self.temporary.name) / "inline")
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        manifest = core.load_json(job / "build/render-manifest.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual([item["location"] for item in manifest["inline_images"]], [
            "blocks.InlineHeading.target[1].image", "blocks.InlineBody.target[1].image",
            "blocks.InlineBody.target[3].image", "notes.InlineNote.target[1].image"])
        self.assertEqual(len(report["inline_images"]), 4)
        ems = {}
        with pymupdf.open(pdf) as document:
            for image in report["inline_images"]:
                location = image["location"]
                context = "Heading" if "InlineHeading" in location else "Body" if "InlineBody" in location else "Note"
                page = document[image["start"]["page"] - 1]
                before = page.search_for(context + ("Middle" if "target[3]" in location else "Before"))[0]
                after = page.search_for(context + ("Middle" if context == "Body" and "target[1]" in location else "After"))[0]
                rect = pymupdf.Rect(image["pdf_rect_pt"])
                self.assertLess(before[2], rect.x0)
                self.assertLess(rect.x1, after[0])
                spans = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]
                surrounding = next(span for span in spans if context + "Before" in span["text"])
                self.assertAlmostEqual(surrounding["size"], image["font_em_pt"], delta=.05)
                self.assertAlmostEqual(surrounding["origin"][1], image["baseline_from_top_pt"], delta=.05)
                self.assertAlmostEqual(rect.width, image["width_em"] * image["font_em_pt"], delta=.02)
                self.assertAlmostEqual(rect.height, image["height_em"] * image["font_em_pt"], delta=.02)
                self.assertAlmostEqual(rect.y1, image["baseline_from_top_pt"] - image["raise_em"] * image["font_em_pt"], delta=.02)
                self.assertEqual(image["start"]["page"], image["end"]["page"])
                ems[context] = image["font_em_pt"]
            self.assertGreater(ems["Heading"], ems["Body"])
            self.assertGreater(ems["Body"], ems["Note"])
            note = report["notes"][0]
            self.assertEqual(note["start"]["page"], note["callout"]["page"])
        from PIL import Image
        for image in manifest["inline_images"]:
            with Image.open(job / image["asset"]) as original:
                self.assertEqual(hashlib.sha256(original.convert("RGB").tobytes()).hexdigest(), image["rgb_sha256"])
                self.assertEqual(hashlib.sha256(original.convert("RGBA").getchannel("A").tobytes()).hexdigest(), image["alpha_sha256"])
        self.assertNotIn(r"\input", (job / "build/book.tex").read_text())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real boxed caption evidence")
    def test_compiled_inline_images_in_below_image_and_group_captions(self):
        import pymupdf
        for relation in (None, "row"):
            with self.subTest(relation=relation):
                job = make_inline_caption_job(Path(self.temporary.name) / (relation or "image-caption"), relation)
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                self.assertTrue(report["passed"], report["errors"])
                self.assertTrue(all(report["checks"].values()))
                caption = [image for image in report["inline_images"] if image["container"] == "blocks.InlineBody.target"]
                self.assertEqual(len(caption), 2)
                canvas = report["images"][0]
                outer = next(block for block in report["block_boundaries"] if block["id"] == "InlineBody")
                self.assertGreater(outer["end"]["y_from_bottom_pt"], caption[-1]["end"]["y_from_bottom_pt"] + .2)
                with pymupdf.open(pdf) as document:
                    for index, image in enumerate(caption):
                        page = document[image["start"]["page"] - 1]
                        self.assertEqual(image["start"]["page"], canvas["page"])
                        rect = pymupdf.Rect(image["pdf_rect_pt"])
                        self.assertLess(max(item["pdf_rect_pt"][3] for item in canvas["rectangles"]), rect.y0)
                        before = page.search_for("BodyBefore" if index == 0 else "BodyMiddle")[0]
                        after = page.search_for("BodyMiddle" if index == 0 else "BodyAfter")[0]
                        self.assertLess(before.x1, rect.x0)
                        self.assertLess(rect.x1, after.x0)
                        spans = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]
                        text = next(span for span in spans if "BodyBefore" in span["text"])
                        self.assertAlmostEqual(text["origin"][1], image["baseline_from_top_pt"], delta=.05)
                        self.assertAlmostEqual(text["size"], image["font_em_pt"], delta=.05)
                        self.assertAlmostEqual(rect.width, image["width_em"] * image["font_em_pt"], delta=.02)
                        self.assertAlmostEqual(rect.height, image["height_em"] * image["font_em_pt"], delta=.02)
                        self.assertAlmostEqual(rect.y1, image["baseline_from_top_pt"] - image["raise_em"] * image["font_em_pt"], delta=.02)
                        for actual, expected in zip(image["pdf_rect_pt"], image["expected_rect_pt"]):
                            self.assertAlmostEqual(actual, expected, delta=.02)
                    self.assertLess(caption[0]["end"]["x_pt"], caption[1]["start"]["x_pt"])
                    self.assertIn("NoteBefore", document[report["notes"][0]["start"]["page"] - 1].get_text())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_compiled_inline_images_stay_beside_side_text_group_canvas(self):
        import pymupdf
        for relation in ("text-left", "text-right"):
            with self.subTest(relation=relation):
                job = make_inline_caption_job(Path(self.temporary.name) / relation, relation)
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                self.assertTrue(report["passed"], report["errors"])
                self.assertTrue(all(report["checks"].values()))
                canvas = report["images"][0]
                with pymupdf.open(pdf) as document:
                    page = document[canvas["page"] - 1]
                    for text in ("BodyBefore", "BodyMiddle", "BodyAfter"):
                        self.assertTrue(page.search_for(text))
                    caption = [image for image in report["inline_images"] if image["container"] == "blocks.InlineBody.target"]
                    self.assertEqual(len(caption), 2)
                    for image in caption:
                        self.assertEqual(image["start"]["page"], canvas["page"])
                        rect = pymupdf.Rect(image["pdf_rect_pt"])
                        if relation == "text-left":
                            self.assertLess(rect.x1, min(item["pdf_rect_pt"][0] for item in canvas["rectangles"]))
                        else:
                            self.assertGreater(rect.x0, max(item["pdf_rect_pt"][2] for item in canvas["rectangles"]))
                        for actual, expected in zip(rect, image["expected_rect_pt"]):
                            self.assertAlmostEqual(actual, expected, delta=.02)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_compiled_caption_escape_and_inline_reading_order_are_rejected(self):
        from unittest.mock import patch
        original = render._Renderer.image_block
        pattern = re.compile(r"\\BTInlineImage\{inline:\d+\}(?:\{[^{}]*\}){4}")
        for relation in (None, "row"):
            for mutation in ("escape-before", "escape-after", "reorder"):
                with self.subTest(relation=relation, mutation=mutation):
                    job = make_inline_caption_job(Path(self.temporary.name) / ((relation or "image") + mutation), relation)
                    def tampered(renderer, block, caption, page_prefix, note_count):
                        first, second = pattern.findall(caption)
                        if mutation == "reorder":
                            caption = pattern.sub(lambda match: second if match[0] == first else first, caption)
                        else:
                            caption = pattern.sub("", caption)
                            caption = first + second + caption if mutation == "escape-before" else caption + first + second
                        return original(renderer, block, caption, page_prefix, note_count)
                    expected = "reading order differs" if mutation == "reorder" else "escaped its compiled"
                    with patch.object(render._Renderer, "image_block", tampered):
                        with self.assertRaisesRegex(ValueError, expected):
                            render.build(job)
                    report = core.load_json(job / "build/verification.json")
                    self.assertFalse(report["passed"])
                    self.assertFalse(report["checks"]["inline_images"])
                    self.assertTrue(all(value for key, value in report["checks"].items() if key != "inline_images"), report["errors"])
                    self.assertTrue(all(expected in error for error in report["errors"]), report["errors"])
                    caption = [image for image in report["inline_images"] if image["container"] == "blocks.InlineBody.target"]
                    self.assertEqual(len(caption), 2)
                    for image in caption:
                        for actual, expected_coordinate in zip(image["pdf_rect_pt"], image["expected_rect_pt"]):
                            self.assertAlmostEqual(actual, expected_coordinate, delta=.02)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_actual_pdf_inline_omission_reordering_distortion_and_raise_are_rejected(self):
        import pymupdf
        job = make_inline_job(Path(self.temporary.name) / "inline-tampering")
        pdf = render.build(job)
        original = pdf.read_bytes()
        manifest = core.load_json(job / "build/render-manifest.json")
        good = core.load_json(job / "build/verification.json")
        log = (job / "build/book.log").read_text()
        aux = (job / "build/book.aux").read_text()
        body = next(image for image in good["inline_images"] if image["location"] == "blocks.InlineBody.target[1].image")
        for mutation in ("omit", "reorder", "distort", "raise"):
            with self.subTest(mutation=mutation):
                pdf.write_bytes(original)
                with pymupdf.open(pdf) as document:
                    page = document[body["start"]["page"] - 1]
                    info = page.get_image_info(xrefs=True)
                    glyphs = [item for item in info if max(abs(a - b) for a, b in zip(item["bbox"], body["pdf_rect_pt"])) < .05]
                    self.assertEqual(len(glyphs), 1)
                    xref = glyphs[0]["xref"]
                    names = {row[0]: row[7].encode() for row in page.get_images(full=True)}
                    name = names[xref]
                    page.clean_contents()
                    stream = page.read_contents()
                    if mutation == "reorder":
                        other = next(item for item in info if item["xref"] != xref)
                        other_name = names[other["xref"]]
                        stream = re.sub(rb"/(" + re.escape(name) + b"|" + re.escape(other_name) + rb")\s+Do\b",
                                        lambda match: b"/" + (other_name if match[1] == name else name) + b" Do", stream)
                    else:
                        stream = re.sub(rb"/" + re.escape(name) + rb"\s+Do\b", b"", stream)
                    document.update_stream(page.get_contents()[0], stream)
                    if mutation in ("distort", "raise"):
                        rect = pymupdf.Rect(body["pdf_rect_pt"])
                        if mutation == "distort":
                            rect.x1 += 2
                        else:
                            rect.y0 -= 2
                            rect.y1 -= 2
                        page.insert_image(rect, xref=xref, keep_proportion=False)
                    document.saveIncr()
                report = render._verify(job / "build", manifest, log, aux)
                self.assertFalse(report["passed"])
                self.assertFalse(report["checks"]["inline_images"])
                self.assertTrue(any(body["location"] in error for error in report["errors"]), report["errors"])
                if mutation == "reorder":
                    self.assertTrue(any("raster pixels differ" in error for error in report["errors"]), report["errors"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_compiled_inline_images_cannot_exceed_the_text_area(self):
        job = make_inline_job(Path(self.temporary.name) / "inline-outside")
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(job / filename)
            body = manuscript["blocks"][1]
            body["source"][1]["image"].update(width_em=40, height_em=20)
            if filename == "book.json":
                body["target"][1]["image"].update(width_em=40, height_em=20)
            core.save_json(job / filename, manuscript)
        core.seal_source(job)
        with self.assertRaisesRegex(ValueError, "exceeds the A5 text area"):
            render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertFalse(report["checks"]["inline_images"])
        self.assertTrue(any("blocks.InlineBody.target[1].image" in error and "exceeds" in error for error in report["errors"]))


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real compiled layout evidence")
    def test_compiled_representative_book(self):
        import pymupdf
        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["content_digest"], core.content_digest(self.job))
        self.assertTrue(all(report["checks"].values()))
        self.assert_mirrored_geometry(pdf, report, inner_mm=20)
        self.assertLessEqual(len(report["agent_preface_pages"]), 2)
        self.assertEqual([item["printed_label"] for item in report["source_marks"]], ["xii", "A-7", None])
        long_note = next(item for item in report["notes"] if item["id"] == "LongNote")
        self.assertGreater(long_note["end"]["page"], long_note["start"]["page"])
        self.assertTrue(set(range(long_note["start"]["page"], long_note["end"]["page"] + 1))
                        <= {footer["page"] for footer in report["footnote_pages"]})
        self.assertEqual(report["term_first_pages"]["Footer"], long_note["start"]["page"])
        self.assertGreaterEqual(len(report["footnote_pages"]), 2)
        with pymupdf.open(pdf) as document:
            text = "\n".join(page.get_text() for page in document)
            self.assertIn("FOOTNOTE-END", text)
            self.assertIn("# Keep this comment exactly: 100% & _", text)
            self.assertIn("value = 3", text)
            self.assertIn("\u4e2d\u6587", text)
            self.assertIn("100% & # _", text)
            for literal in ("{", "}", "$", "~", "^", "\\"):
                self.assertIn(literal, text)
            self.assertNotIn("unn.", text)
            spans = [span for page in document for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]]
            first = next(span for span in spans if "Fourier" in span["text"])
            self.assertTrue(first["flags"] & 2 and first["flags"] & 16, first)
            self.assertTrue(any("Fourier" in span["text"] and not span["flags"] & 16 for span in spans[spans.index(first) + 1:]))
            self.assertTrue(any(span["text"] == "1" and span["size"] < first["size"] and span["origin"][1] < first["origin"][1] and first["bbox"][2] < span["origin"][0] < first["bbox"][2] + 70 for span in spans))
            cjk = [span for span in spans if "\u65b9\u6cd5" in span["text"]]
            self.assertIn("Bold", cjk[0]["font"])
            self.assertTrue(any("Regular" in span["font"] for span in cjk[1:]))
            term_page = document[report["term_first_pages"]["Method"] - 1]
            resource = next(font[4] for font in term_page.get_fonts() if "FandolSong-Bold" in font[3])
            slant = rf"/{resource}\s+[\d.]+\s+Tf(?:(?!/[A-Za-z0-9]+\s+[\d.]+\s+Tf).)*?1\s+0\s+\.2\s+1\s+[-\d.]+\s+[-\d.]+\s+Tm"
            self.assertRegex(term_page.read_contents().decode("latin1"), re.compile(slant, re.S))
            for identifier in ("Method", "Footer"):
                actual, _, _ = self.glossary_cell(self.job, document, identifier, 3)
                expected = report["term_first_references"][identifier]["display"]
                self.assertEqual("".join(actual.split()), "".join(expected.split()))
        self.assertFalse((self.job / "output.pdf").exists())
        literal = self.job / "build/assets/code-CodeBlock.txt"
        self.assertEqual(literal.read_bytes(), core.load_json(self.job / "book.json")["protected"][2]["value"].encode())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real title-first evidence")
    def test_compiled_explicit_title_terms_preserve_aliases_and_first_use_order(self):
        import pymupdf
        target = "\u5e95\u90e8\u6ce8\u91ca"
        literals = ("Fourier method", target, "Fourier method", target)
        title = " | ".join(literals)
        spans = []
        cursor = 0
        for identifier, literal in zip(("Method", "Footer", "Method", "Footer"), literals):
            start = title.index(literal, cursor)
            spans.append({"term": identifier, "start": start, "end": start + len(literal)})
            cursor = start + len(literal)
        for selected in (spans, []):
            with self.subTest(explicit=bool(selected)):
                job = make_job(self.job / ("title-spans" if selected else "title-plain"))
                terms = core.load_json(job / "terms.json")
                terms["terms"][1]["target"] = target
                core.save_json(job / "terms.json", terms)
                for filename in ("book-source.json", "book.json"):
                    manuscript = core.load_json(job / filename)
                    manuscript["title"] = title
                    if filename == "book.json":
                        manuscript["title_terms"] = selected
                        if selected:
                            manuscript["agent_preface"] += [{"text": " Later ordinary terms: "},
                                                            {"term": "Method"}, {"text": " / "}, {"term": "Footer"}]
                    core.save_json(job / filename, manuscript)
                core.seal_source(job)
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                self.assertTrue(all(report["checks"].values()), report["errors"])
                expected_page = 1 if selected else 3
                self.assertEqual(report["term_first_pages"], {"Method": expected_page, "Footer": expected_page})
                with pymupdf.open(pdf) as document:
                    page_text = document[0].get_text("dict")
                    title_spans = [span for block in page_text["blocks"]
                                   for line in block.get("lines", []) for span in line["spans"]]
                    title_glyphs = self.title_glyphs(document[0])
                    title_size = max(span["size"] for span in title_glyphs)
                    large_text = "".join(span["text"] for span in title_glyphs if abs(span["size"] - title_size) < .1)
                    self.assertEqual(re.sub(r"\s+", "", large_text), re.sub(r"\s+", "", title))
                    aliases = [span for span in title_glyphs if "Fourier" in span["text"]]
                    self.assertEqual(len(aliases), 2)
                    self.assertTrue(aliases[0]["flags"] & 16)
                    self.assertEqual(bool(aliases[0]["flags"] & 2), bool(selected))
                    self.assertFalse(aliases[1]["flags"] & 2)
                    title_targets = [span for span in title_glyphs if target in span["text"]]
                    self.assertEqual(large_text.count(target), 2)
                    if selected:
                        self.assertIn("Bold", title_targets[0]["font"])
                        ordinary = [span for span in title_spans if target in span["text"] and span["size"] < title_size - .3]
                        self.assertTrue(ordinary)
                        self.assertTrue(all("Regular" in span["font"] for span in ordinary))
                    for identifier in ("Method", "Footer"):
                        actual, _, _ = self.glossary_cell(job, document, identifier, 3)
                        expected = report["term_first_references"][identifier]["display"]
                        self.assertEqual("".join(actual.split()), "".join(expected.split()))
                        self.assertEqual(report["term_first_references"][identifier]["printed_page"], None if selected else 1)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real missing-capability evidence")
    def test_compiler_fails_clearly_without_baseline_attachment_capability(self):
        import subprocess
        cases = {
            "api": (r"\makeatletter\let\IfSocketExistsTF\@undefined\makeatother",
                    "Required LaTeX socket API is unavailable"),
            "socket": (r"\ExplSyntaxOn\cs_undefine:c{l__socket_build/column/baselineattach_plug_str}\ExplSyntaxOff",
                       "Required LaTeX baseline-attachment socket is unavailable"),
        }
        for name, (disable, expected) in cases.items():
            with self.subTest(capability=name):
                root = self.job / ("missing-" + name)
                root.mkdir()
                shutil.copyfile(render.TEMPLATE.with_name("translator.sty"), root / "translator.sty")
                tex = (r"\documentclass[a5paper,twoside,openany,10pt,fontset=fandol]{ctexbook}" + "\n" +
                       r"\newcommand{\BTInner}{20}\newcommand{\BTOuter}{8}\newcommand{\BTTop}{15}\newcommand{\BTBottom}{15}\newcommand{\BTMarkEdge}{3}" + "\n" +
                       disable + "\n" + r"\usepackage{translator}\begin{document}Capability check.\end{document}")
                (root / "book.tex").write_text(tex)
                result = subprocess.run([shutil.which("xelatex"), "-no-shell-escape", "-halt-on-error",
                                         "-interaction=batchmode", "book.tex"], cwd=root,
                                        capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                log = (root / "book.log").read_text()
                self.assertIn(re.sub(r"\s+", "", expected), re.sub(r"\s+", "", log))
                self.assertNotIn("Undefined control sequence", log)


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real glossary cell evidence")
    def test_compiled_glossary_source_and_target_cells_wrap_literal_runs(self):
        import pymupdf
        terms = core.load_json(self.job / "terms.json")
        term = terms["terms"][1]
        term.update(source="approximation " + "R7a90B2cD4eF6gH8jK0mN2pQ4sT6uV8wX0yZ2" * 2,
                    target="approximations \u4e2d\u6587 " + r"100%&_#{}$~^\input{never-read-this-file}")
        core.save_json(self.job / "terms.json", terms)
        inputs = {name: (self.job / name).read_bytes() for name in
                  ("job.json", "book.json", "book-source.json", "terms.json", "source.sha256")}
        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertTrue(all(report["checks"].values()), report["errors"])
        self.assertEqual(inputs, {name: (self.job / name).read_bytes() for name in inputs})
        self.assertNotIn(r"\input", (self.job / "build/book.tex").read_text())
        self.assert_mirrored_geometry(pdf, report, inner_mm=20)
        with pymupdf.open(pdf) as document:
            appendix = document[-1]
            words = appendix.get_text("words")
            for field, column in (("source", 1), ("target", 2)):
                actual, lines, cell = self.glossary_cell(self.job, document, "Footer", column)
                self.assertEqual("".join(actual.split()), "".join(term[field].split()), field)
                self.assertGreater(len(lines), 1)
                for line in lines:
                    for span in line["spans"]:
                        self.assertAlmostEqual(span["size"], 9 * 72 / 72.27, delta=.05)
                        for char in span["chars"]:
                            self.assertTrue(cell.contains(pymupdf.Rect(char["bbox"])), (field, char))

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real baseline-depth evidence")
    def test_compiled_bottom_footer_accounts_for_final_body_depth(self):
        import subprocess
        import pymupdf
        from PIL import Image
        root = self.job / "baseline-depth"
        root.mkdir()
        shutil.copyfile(render.TEMPLATE.with_name("translator.sty"), root / "translator.sty")
        shutil.copyfile(self.job / "first.png", root / "note.png")
        # The first line fills exactly the page-builder's measured body height.
        # Its real strut depth must not be counted again when attaching a footer.
        tex = r"""\documentclass[a5paper,twoside,openany,10pt,fontset=fandol]{ctexbook}
\newcommand{\BTInner}{20}\newcommand{\BTOuter}{8}\newcommand{\BTTop}{15}\newcommand{\BTBottom}{15}\newcommand{\BTMarkEdge}{3}
\usepackage{translator}
\AddToHook{shipout/foreground}{\typeout{BTPAGE|\number\value{page}|\thepage|\leftmark|\rightmark}}
\newlength{\BTFixtureNoteDepth}
\begin{document}
\BTMainBody
{\footnotesize\global\BTFixtureNoteDepth=\dp\strutbox}
\indent\rule[-\dp\strutbox]{0pt}{\dimexpr\textheight-\skip\footins-\footnotesep-\BTFixtureNoteDepth+\dp\strutbox\relax}%
\typeout{BTTYPE|preface|paragraph|\number\dimexpr1em\relax}%
\BTPosition{mainbody:start}\BTPosition{block:Depth:start}\BTPosition{preface:start}Body gy\BTPosition{preface:end}\BTPosition{block:Depth:end}\BTPosition{callout:DepthNote}\footnote{\BTPosition{note:DepthNote:start}\BTInlineImage{inline:1}{15.6960021973}{1.2}{0}{note.png}\BTPosition{note:DepthNote:end}}\par
\end{document}
"""
        (root / "book.tex").write_text(tex)
        for _ in range(2):
            result = subprocess.run([shutil.which("xelatex"), "-no-shell-escape", "-halt-on-error",
                                     "-interaction=batchmode", "book.tex"], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = (root / "book.log").read_text()
        self.assertNotRegex(log, r"Overfull \\[hv]box")
        with Image.open(root / "note.png") as image:
            pixels = {"width_px": image.width, "height_px": image.height,
                      "rgb_sha256": hashlib.sha256(image.convert("RGB").tobytes()).hexdigest(),
                      "alpha_sha256": hashlib.sha256(image.convert("RGBA").getchannel("A").tobytes()).hexdigest()}
        manifest = {"layout": core.load_json(self.job / "job.json")["layout"], "source_marks": [],
                    "graphic_boundaries": [], "main_body_start": "Depth", "heading_text": {},
                    "images": [], "blocks": [], "term_ids": [], "note_ids": ["DepthNote"],
                    "note_metadata": [{"id": "DepthNote", "content_type": "literal", "literal_reason": "Synthetic nonprose image tests baseline depth."}],
                    "inline_images": [{"key": "inline:1", "location": "notes.DepthNote.target[0].image",
                                       "container": "notes.DepthNote.target", "asset": "note.png",
                                       "width_em": 15.6960021973, "height_em": 1.2, "raise_em": 0, **pixels}]}
        aux = (root / "book.aux").read_text()
        report = render._verify(root, manifest, log, aux)
        self.assertTrue(all(report["checks"].values()), report["errors"])
        self.assertEqual(report["notes"][0]["start"]["page"], report["notes"][0]["callout"]["page"])
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 1)
            self.assertIn("Body gy", document[0].get_text())
            self.assertEqual(len(report["inline_images"]), 1)
            raster = report["inline_images"][0]
            for actual, expected in zip(raster["pdf_rect_pt"], raster["expected_rect_pt"]):
                self.assertAlmostEqual(actual, expected, delta=.02)




    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_overlong_agent_preface_rejected(self):
        book = core.load_json(self.job / "book.json")
        book["agent_preface"] = [{"text": "This machine translation discloses its terminology, limitations and unapproved review. " * 900}]
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "Agent preface occupies"):
            render.build(self.job)
        self.assertFalse(core.load_json(self.job / "build/verification.json")["passed"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_unreadable_side_text_fails_actual_compiler(self):
        book = core.load_json(self.job / "book.json")
        next(item for item in book["blocks"] if item["id"] == "SideGroup")["target"] = [{"text": "Side text cannot be shrunk into an unreadable image. " * 90}]
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(RuntimeError, "XeLaTeX compilation failed"):
            render.build(self.job)
        self.assertIn("Side-text group", (self.job / "build/compiler.log").read_text())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_current_layout_and_separate_human_preface(self):
        job = core.load_json(self.job / "job.json")
        job["layout"].update(inner_min_mm=32, outer_mm=9, source_mark_edge_mm=4)
        core.save_json(self.job / "job.json", job)
        book = core.load_json(self.job / "book.json")
        book["human_preface"] = [{"text": "This is an independent human-preface slot with its own pagination. " * 200}]
        book["agent_preface"] += [{"text": " The first selected term is "}, {"term": "Method"}, {"text": ", introduced here before the translated body."}]
        core.save_json(self.job / "book.json", book)
        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["pdf_sha256"], hashlib.sha256(pdf.read_bytes()).hexdigest())
        self.assertEqual(len(report["agent_preface_pages"]), 1)
        self.assertGreater(report["source_marks"][0]["page"], 3)
        self.assert_mirrored_geometry(pdf, report, inner_mm=32, outer_mm=9)
        self.assertTrue(all(mark["outer_edge_mm"] == 4 for mark in report["source_marks"]))
        self.assertEqual(report["term_first_pages"]["Method"], 1)
        import pymupdf
        with pymupdf.open(pdf) as document:
            preface_cjk = [span for block in document[0].get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"] if "\u65b9\u6cd5" in span["text"]]
            self.assertTrue(preface_cjk and "Bold" in preface_cjk[0]["font"])
            body_page = document[report["source_marks"][0]["page"] - 1]
            body_cjk = [span for block in body_page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"] if "\u65b9\u6cd5" in span["text"]]
            self.assertTrue(body_cjk and all("Regular" in span["font"] for span in body_cjk))

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_overfull_prose_fails_acceptance(self):
        book = core.load_json(self.job / "book.json")
        book["blocks"][5]["target"] = [{"text": "X" * 400}]
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "overfull output"):
            render.build(self.job)
        self.assertFalse(core.load_json(self.job / "build/verification.json")["checks"]["overflow"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_missing_font_glyph_fails_acceptance(self):
        book = core.load_json(self.job / "book.json")
        book["blocks"][5]["target"] = [{"text": "A missing glyph must be rejected: \U0010ffff"}]
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "missing font glyphs"):
            render.build(self.job)

    def test_palette_image_alpha_survives_normalization(self):
        from PIL import Image
        image = Image.new("P", (160, 80), 0)
        image.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762)
        image.paste(1, (80, 0, 160, 80))
        image.save(self.job / "first.png", transparency=bytes([0, 128] + [255] * 254))
        core.seal_source(self.job)
        render.render(self.job)
        with Image.open(self.job / "first.png") as original, Image.open(self.job / "build/assets/image-1.png") as normalized:
            self.assertEqual(original.convert("RGBA").tobytes(), normalized.convert("RGBA").tobytes())

    def test_ambiguous_source_page_boundary_is_not_invented(self):
        book = core.load_json(self.job / "book.json")
        source = core.load_json(self.job / "book-source.json")
        for manuscript in (book, source):
            intro = next(block for block in manuscript["blocks"] if block["id"] == "Intro")
            intro["source"] = [item for item in intro["source"] if "page" not in item]
            intro["target"] = [item for item in intro["target"] if "page" not in item]
        core.save_json(self.job / "book-source.json", source)
        core.seal_source(self.job)
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "ambiguous source-page boundaries"):
            render.build(self.job)
        self.assertFalse(core.load_json(self.job / "build/verification.json")["passed"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_source_label_collisions_are_not_silently_shifted(self):
        book = core.load_json(self.job / "book.json")
        source = core.load_json(self.job / "book-source.json")
        boundary = [{"page": "P1"}, {"text": "First boundary "}, {"page": "P2"}, {"text": "second boundary"}]
        for manuscript in (book, source):
            heading = manuscript["blocks"][0]
            heading["source_pages"] = ["P1", "P2"]
            heading["source"] = copy.deepcopy(boundary)
            if manuscript is book:
                heading["target"] = copy.deepcopy(boundary)
            intro = manuscript["blocks"][1]
            intro["source_pages"] = ["P2"]
            intro["source"] = [item for item in intro["source"] if "page" not in item]
            intro["target"] = [item for item in intro["target"] if "page" not in item]
        core.save_json(self.job / "book-source.json", source)
        core.seal_source(self.job)
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "collide"):
            render.build(self.job)
        self.assertFalse(core.load_json(self.job / "build/verification.json")["checks"]["source_boundaries"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real marker-fit evidence")
    def test_compiled_source_markers_fit_mirrored_gutters_without_changing_labels(self):
        import pymupdf
        for parity in (0, 1):
            for labels in (("xxviii", "A-123456789"), ("xii", "A-7")):
                with self.subTest(parity=parity, labels=labels):
                    job = make_job(self.job / (str(parity) + labels[0]))
                    for filename in ("book-source.json", "book.json"):
                        manuscript = core.load_json(job / filename)
                        for page, label in zip(manuscript["source_pages"], labels):
                            page["printed_label"] = label
                        if parity == 0 and filename == "book.json":
                            manuscript["human_preface"] = None
                        core.save_json(job / filename, manuscript)
                    core.seal_source(job)
                    pdf = render.build(job)
                    report = core.load_json(job / "build/verification.json")
                    self.assertTrue(all(report["checks"].values()), report["errors"])
                    with pymupdf.open(pdf) as document:
                        for mark, expected in zip(report["source_marks"], labels):
                            self.assertEqual(mark["page"] % 2, parity)
                            page = document[mark["page"] - 1]
                            baseline = mark["baseline_from_top_pt"]
                            spans = [span for block in page.get_text("dict")["blocks"]
                                     for line in block.get("lines", []) for span in line["spans"]
                                     if abs(span["origin"][1] - baseline) < .05 and
                                     ((span["bbox"][0] > page.rect.width - 8 * render.PT_PER_MM - .05)
                                      if parity else (span["bbox"][2] < 8 * render.PT_PER_MM + .05))]
                            self.assertEqual("".join(span["text"] for span in spans), expected)
                            rect = pymupdf.Rect(spans[0]["bbox"])
                            for span in spans[1:]:
                                rect.include_rect(span["bbox"])
                            if parity:
                                self.assertGreaterEqual(rect.x0, page.rect.width - 8 * render.PT_PER_MM - .05)
                                self.assertAlmostEqual(rect.x1, page.rect.width - 3 * render.PT_PER_MM, delta=.05)
                            else:
                                self.assertLessEqual(rect.x1, 8 * render.PT_PER_MM + .05)
                                self.assertAlmostEqual(rect.x0, 3 * render.PT_PER_MM, delta=.05)
                            natural_size = 5 * 72 / 72.27
                            for span in spans:
                                if labels[0] == "xii":
                                    self.assertAlmostEqual(span["size"], natural_size, delta=.01)
                                else:
                                    self.assertLess(span["size"], natural_size)


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required")
    def test_even_page_source_marks_use_left_outer_edge(self):
        book = core.load_json(self.job / "book.json")
        book["human_preface"] = None
        core.save_json(self.job / "book.json", book)
        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertEqual(report["source_marks"][0]["page"], 2)
        import pymupdf
        with pymupdf.open(pdf) as document:
            for mark in report["source_marks"][:2]:
                page = document[mark["page"] - 1]
                label = next(word for word in page.get_text("words") if word[4] == mark["printed_label"])
                self.assertAlmostEqual(label[0], 3 * render.PT_PER_MM, delta=.7)


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for physical-side evidence")
    def test_body_epoch_physical_headers_and_nested_hanging_lists(self):
        import pymupdf
        for front_heading, physical_start in ((False, 2), (True, 3)):
            with self.subTest(front_heading=front_heading):
                job = make_flow_job(self.job / ("front-headings" if front_heading else "left-body"), front_heading=front_heading)
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                self.assertEqual(len(report["checks"]), 11)
                body = [row for row in report["pagination"] if row["printed_page"] is not None]
                self.assertEqual(body[0]["physical_pdf_page"], physical_start)
                epoch = next(block for block in report["block_boundaries"] if block["id"] == "BodyChapter")["start"]
                self.assertEqual(epoch["physical_pdf_page"], physical_start)
                self.assertEqual(epoch["printed_page"], 1)
                self.assertEqual(body[0]["printed_page"], 1)
                self.assertEqual(body[0]["side"], "left" if physical_start % 2 == 0 else "right")
                self.assertEqual([row["printed_page"] for row in body], list(range(1, len(body) + 1)))
                self.assertTrue(all(row["printed_page"] is None for row in report["pagination"][:physical_start - 1]))
                for row in body:
                    self.assertEqual(row["headers"]["outer"]["text"].strip(), str(row["printed_page"]))
                    expected = "First section" if row["physical_pdf_page"] % 2 else "Body chapter"
                    if row["chapter"] == "BodyChapter":
                        self.assertEqual(row["headers"]["inner"]["text"].strip(), expected)
                    if row["chapter"] in ("NextChapter", "glossary"):
                        self.assertEqual(row["section"], "")
                typography = {row["id"]: row for row in report["typography"]}
                self.assertAlmostEqual(typography["AfterHeading"]["initial_indent_pt"], 2 * typography["AfterHeading"]["font_em_pt"], delta=.05)
                with pymupdf.open(pdf) as document:
                    for identifier, depth, marker in (("Ordered", 0, "7."), ("Bullet", 1, "\u2022"), ("Nested", 2, "(iv)")):
                        row = typography[identifier]
                        self.assertTrue(row["continuation_x_pt"])
                        self.assertTrue(all(abs(x - row["start"]["x_pt"]) < .5 for x in row["continuation_x_pt"]))
                        number = row["start"]["page"]
                        left = (20 if number % 2 else 8) * render.PT_PER_MM
                        self.assertAlmostEqual(row["label"]["x_pt"] - left, (2 + depth * 2) * row["font_em_pt"], delta=.1)
                        page = document[number - 1]
                        baseline = page.rect.height - row["start"]["y_from_bottom_pt"]
                        line = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"] if abs(span["origin"][1] - baseline) < .2]
                        self.assertEqual("".join(span["text"] for span in line).count(marker), 1)
                        self.assertGreater(len(row["line_boxes_pt"]), 1)
                        self.assertTrue(all(following[1] >= previous[3] - .5 for previous, following in zip(row["line_boxes_pt"], row["line_boxes_pt"][1:])))

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for inline-limit line geometry")
    def test_inline_math_limits_preserve_paragraph_spacing_and_hanging_lines(self):
        import pymupdf
        job = make_inline_job(self.job / "math-line-geometry")
        book = core.load_json(job / "book.json")
        formula = {"id": "Limits", "kind": "math",
                   "value": r"|x_i - x_j| \le W,\quad C_{store}/\beta_n V_{max},\quad W = \sum_{i=1}^{p+q+r} w_i"}
        content = [{"text": "The bounds "}, {"protected": "Limits"},
                   {"text": " remain readable within the surrounding explanation. "}] * 3
        book.update(protected=[formula], notes=[], blocks=[
            {"id": "MathHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Inline mathematical limits"}], "target": [{"text": "Inline mathematical limits"}]},
            {"id": "MathParagraph", "kind": "paragraph", "source_pages": ["InlineSource"],
             "source": copy.deepcopy(content), "target": copy.deepcopy(content)},
            {"id": "MathList", "kind": "list_item", "list_type": "ordered", "list_level": 0, "label": "1.",
             "source_pages": ["InlineSource"], "source": copy.deepcopy(content), "target": copy.deepcopy(content)}],
                    main_body_start="MathHeading")
        source = copy.deepcopy(book)
        source["agent_preface"] = []
        for block in source["blocks"]:
            block["target"] = []
        core.save_json(job / "book-source.json", source)
        core.save_json(job / "book.json", book)
        core.seal_source(job)
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        typography = {row["id"]: row for row in report["typography"]}
        for identifier in ("MathParagraph", "MathList"):
            row = typography[identifier]
            self.assertEqual(row["start"]["page"], row["end"]["page"])
            self.assertGreater(len(row["line_boxes_pt"]), 2)
            self.assertTrue(all(following[1] >= previous[3] - .5
                                for previous, following in zip(row["line_boxes_pt"], row["line_boxes_pt"][1:])))
        row = typography["MathList"]
        self.assertEqual(len(row["continuation_x_pt"]), len(row["line_boxes_pt"]) - 1)
        self.assertTrue(all(abs(x - row["start"]["x_pt"]) < .5 for x in row["continuation_x_pt"]))
        with pymupdf.open(pdf) as document:
            text = "".join(page.get_text() for page in document)
            self.assertEqual(text.count("∑"), 6)
            self.assertIn("surrounding explanation", text)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for blank omission evidence")
    def test_blank_source_page_remains_sealed_without_output_or_marker(self):
        job = make_inline_job(self.job / "blank-page")
        baseline_pdf = render.build(job)
        baseline_count = len(core.load_json(job / "build/verification.json")["pages"])
        for filename in ("book-source.json", "book.json"):
            book = core.load_json(job / filename)
            book["source_pages"].insert(0, {"id": "BlankSource", "locator": "synthetic:blank", "printed_label": "BLANK-17", "label_verified": True, "evidence": "Synthetic blank source leaf with an original folio only."})
            book["blocks"].insert(0, {"id": "BlankLeaf", "kind": "blank", "source_pages": ["BlankSource"],
                                      "source": [{"page": "BlankSource"}], "target": [{"page": "BlankSource"}] if filename == "book.json" else [],
                                      "blank_evidence": "Reviewed synthetic source page contains no body content."})
            core.save_json(job / filename, book)
        core.seal_source(job)
        render.build(job)
        report = core.load_json(job / "build/verification.json")
        manifest = core.load_json(job / "build/render-manifest.json")
        self.assertEqual(len(report["pages"]), baseline_count)
        self.assertNotIn("BlankLeaf", [block["id"] for block in manifest["blocks"]])
        self.assertNotIn("BlankSource", [mark["source_page"] for mark in manifest["source_marks"]])
        self.assertNotIn("BLANK-17", (job / "build/book.tex").read_text())
        self.assertEqual(core.validate_book(job, translated=True)["blocks"][0]["kind"], "blank")

    def test_graphic_fit_is_bounded_output_metadata_not_source_calibration(self):
        job = make_graphic_fit_job(self.job / "fit-contract")
        book = core.load_json(job / "book.json")
        fit = book["blocks"][1]["fit"]
        seal = (job / "source.sha256").read_bytes()
        self.assertEqual(core.validate_book(job), book)
        digest = core.content_digest(job)
        changed = copy.deepcopy(book)
        changed["blocks"][1]["fit"].update(scale=.75)
        core.save_json(job / "book.json", changed)
        self.assertNotEqual(core.content_digest(job), digest)
        self.assertEqual((job / "source.sha256").read_bytes(), seal)
        invalid = [dict(fit, **{field: value}) for field in ("scale", "min_scale")
                   for value in (0, -1, 1.01, True, "0.7", None, float("inf"), float("nan"))]
        invalid += [dict(fit, scale=.6), dict(fit, legibility_evidence=" \n"),
                    {key: value for key, value in fit.items() if key != "legibility_evidence"}]
        for value in invalid:
            with self.subTest(fit=value):
                changed = copy.deepcopy(book)
                changed["blocks"][1]["fit"] = value
                if any(isinstance(number, float) and not math.isfinite(number)
                       for number in value.values()):
                    with self.assertRaisesRegex(ValueError, "non-finite"):
                        core.validate_document("book", changed)
                else:
                    core.save_json(job / "book.json", changed)
                    with self.assertRaises(ValueError):
                        core.validate_book(job)
        changed = copy.deepcopy(book)
        changed["blocks"][1]["source_em"] *= 2
        core.save_json(job / "book.json", changed)
        with self.assertRaisesRegex(ValueError, "immutable"):
            core.validate_book(job)
        source = core.load_json(job / "book-source.json")
        source["blocks"][1]["fit"] = fit
        core.save_json(job / "book-source.json", source)
        with self.assertRaisesRegex(ValueError, "output-only"):
            core.seal_source(job)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for reviewed artwork fit evidence")
    def test_reviewed_graphic_fit_preserves_complete_canvas_and_normal_caption_font(self):
        import pymupdf
        for relation in (None, "row", "column", "text-left", "text-right"):
            with self.subTest(relation=relation):
                job = make_graphic_fit_job(self.job / ("fit-" + str(relation)), relation)
                source_bytes = {name: (job / name).read_bytes() for name in ("book-source.json", "source.sha256")}
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                manifest = core.load_json(job / "build/render-manifest.json")
                canvas = report["images"][0]
                fit = manifest["images"][0]["fit"]
                self.assertTrue(all(report["checks"].values()), report["errors"])
                self.assertEqual(canvas["scale"], fit["scale"])
                self.assertAlmostEqual(canvas["width_pt"], canvas["natural_width_pt"] * fit["scale"], delta=.08)
                self.assertAlmostEqual(canvas["height_pt"], canvas["natural_height_pt"] * fit["scale"], delta=.08)
                boundary = next(item for item in report["block_boundaries"] if item["id"] == "InlineBody")
                self.assertEqual(boundary["start"]["page"], boundary["end"]["page"])
                self.assertEqual(report["graphic_boundaries"][0]["page"], canvas["page"])
                self.assertEqual(source_bytes, {name: (job / name).read_bytes() for name in source_bytes})
                with pymupdf.open(pdf) as document:
                    page = document[canvas["page"] - 1]
                    spans = [span for block in page.get_text("dict")["blocks"]
                             for line in block.get("lines", []) for span in line["spans"]]
                    caption = next(span for span in spans if "BodyBefore" in span["text"])
                    self.assertAlmostEqual(caption["size"], 10 * 72 / 72.27, delta=.01)
                    self.assertTrue(all(rect["pdf_rect_pt"] for rect in canvas["rectangles"]))
                    self.assertAlmostEqual(page.rect.width / render.PT_PER_MM, 148, delta=.1)
                    self.assertAlmostEqual(page.rect.height / render.PT_PER_MM, 210, delta=.1)
                if relation == "row":
                    altered = copy.deepcopy(manifest)
                    altered["images"][0]["fit"].update(scale=.75)
                    rejected = render._verify(job / "build", altered,
                                              (job / "build/book.log").read_text(),
                                              (job / "build/book.aux").read_text())
                    self.assertFalse(rejected["checks"]["image_relations"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for intact fitted-page movement")
    def test_reviewed_graphic_fit_moves_intact_without_shrinking_to_page_remainder(self):
        from unittest.mock import patch
        job = make_graphic_fit_job(self.job / "fit-next-page", "row")
        original = render._Renderer.body
        def move_group(renderer):
            carrier = (r"\noindent\begin{minipage}[t][.86\textheight][t]{\linewidth}"
                       r"Synthetic page-fit carrier.\end{minipage}\par" + "\n")
            return original(renderer).replace(
                r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:InlineBody:start}",
                carrier + r"\par\noindent\begin{minipage}{\linewidth}\BTPosition{block:InlineBody:start}")
        with patch.object(render._Renderer, "body", move_group):
            render.build(job)
        report = core.load_json(job / "build/verification.json")
        canvas = report["images"][0]
        self.assertEqual(canvas["scale"], .7)
        self.assertEqual(canvas["page"], report["agent_preface_pages"][-1] + 2)
        boundary = next(item for item in report["block_boundaries"] if item["id"] == "InlineBody")
        self.assertEqual(boundary["start"]["page"], boundary["end"]["page"])
        self.assertEqual(report["notes"][0]["start"]["page"], report["notes"][0]["callout"]["page"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for height-limited artwork with notes")
    def test_reviewed_height_fit_keeps_caption_and_bottom_note_outside_artwork(self):
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(self.job / filename)
            block = next(item for item in manuscript["blocks"] if item["id"] == "TallImage")
            block.update(source_em=12, scale_evidence="Synthetic source body font is 12 source units.")
            if filename == "book.json":
                block["fit"] = {"scale": .5, "min_scale": .5,
                                "legibility_evidence": "Synthetic solid-color plate at a fixture-only threshold; no real artwork legibility is asserted."}
            core.save_json(self.job / filename, manuscript)
        core.seal_source(self.job)
        render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        canvas = next(item for item in report["images"] if item["id"] == "TallImage")
        self.assertAlmostEqual(canvas["height_pt"], canvas["natural_height_pt"] * .5, delta=.08)
        self.assertGreater(canvas["natural_height_pt"], report["compiled_geometry_pt"]["text_height"])
        note = next(item for item in report["notes"] if item["id"] == "TallNote")
        self.assertEqual(note["callout"]["page"], note["start"]["page"])
        self.assertEqual(note["start"]["page"], canvas["page"])
        self.assertTrue(all(report["checks"].values()), report["errors"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for readable-floor rejection")
    def test_graphic_still_oversized_at_reviewed_floor_blocks_without_paper_change(self):
        job = make_graphic_fit_job(self.job / "fit-impossible", "row")
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(job / filename)
            manuscript["blocks"][1]["source_em"] = 1
            manuscript["blocks"][1]["scale_evidence"] = "Synthetic source body font is 1 source unit."
            core.save_json(job / filename, manuscript)
        core.seal_source(job)
        inputs = {name: (job / name).read_bytes() for name in
                  ("book-source.json", "book.json", "source.sha256", "job.json")}
        with self.assertRaises(RuntimeError):
            render.build(job)
        self.assertEqual(inputs, {name: (job / name).read_bytes() for name in inputs})
        self.assertEqual(core.load_json(job / "job.json")["layout"]["paper"], "a5")
        self.assertFalse(core.load_json(job / "build/verification.json")["passed"])
        self.assertFalse((job / "output.pdf").exists())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for natural graphic scale evidence")
    def test_canvas_size_tracks_source_body_font_without_fit_resizing(self):
        import pymupdf
        for factor in (.25, 2):
            with self.subTest(factor=factor):
                job = make_inline_caption_job(self.job / ("natural-" + str(factor)), "row")
                for filename in ("book-source.json", "book.json"):
                    book = core.load_json(job / filename)
                    block = book["blocks"][1]
                    for field in ("canvas_width", "canvas_height"):
                        block[field] *= factor
                    for image in block["images"]:
                        for field in ("x", "y", "width", "height"):
                            image[field] *= factor
                    core.save_json(job / filename, book)
                core.seal_source(job)
                pdf = render.build(job)
                report = core.load_json(job / "build/verification.json")
                canvas = report["images"][0]
                em = 10 * 72 / 72.27
                self.assertAlmostEqual(canvas["width_pt"], 220 * factor / 16 * em, delta=.08)
                with pymupdf.open(pdf) as document:
                    info = document[canvas["page"] - 1].get_image_info()
                    actual = next(item for item in info if abs((item["bbox"][2] - item["bbox"][0]) - 80 * factor / 16 * em) < .1)
                    self.assertAlmostEqual(actual["bbox"][3] - actual["bbox"][1], 40 * factor / 16 * em, delta=.08)
        for relation, source_em in ((None, .5), ("text-left", 8)):
            with self.subTest(overflow=relation):
                job = make_inline_caption_job(self.job / ("overflow-" + str(relation)), relation)
                for filename in ("book-source.json", "book.json"):
                    book = core.load_json(job / filename)
                    book["blocks"][1]["source_em"] = source_em
                    core.save_json(job / filename, book)
                core.seal_source(job)
                inputs = {name: (job / name).read_bytes() for name in
                          ("book-source.json", "book.json", "source.sha256", "job.json")}
                with self.assertRaises(RuntimeError):
                    render.build(job)
                self.assertEqual(inputs, {name: (job / name).read_bytes() for name in inputs})
                self.assertFalse(core.load_json(job / "build/verification.json")["passed"])
                self.assertFalse((job / "output.pdf").exists())

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for note evidence consumption")
    def test_prose_note_source_raster_is_audit_only_not_output(self):
        job = make_inline_job(self.job / "note-evidence")
        for filename in ("book-source.json", "book.json"):
            book = core.load_json(job / filename)
            book["notes"][0]["source_evidence"] = [{"asset": "first.png", "source_page": "InlineSource", "description": "Original raster note crop associated with the body callout at source coordinates 90,100; prose is transcribed in source tokens."}]
            core.save_json(job / filename, book)
        core.seal_source(job)
        render.build(job)
        manifest = core.load_json(job / "build/render-manifest.json")
        self.assertEqual(manifest["note_metadata"][0]["content_type"], "prose")
        self.assertEqual(manifest["note_metadata"][0]["source_evidence"][0]["asset"], "first.png")
        self.assertNotIn("first.png", [image["asset"] for image in manifest["inline_images"]])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for actual restoration crop output")
    def test_minimal_restoration_notice_excerpt_and_original_pixels_reach_pdf(self):
        import pymupdf
        job = make_restoration_job(self.job / "minimal-restoration")
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        manifest = core.load_json(job / "build/render-manifest.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual([image["asset"] for image in manifest["inline_images"]], ["damage.png"])
        note = core.load_json(job / "book.json")["notes"][0]
        with pymupdf.open(pdf) as document:
            text = "\n".join(page.get_text() for page in document)
            visible = "".join(text.split())
            self.assertIn("".join(note["target"][0]["text"].split()), visible)
            self.assertIn("".join(note["restoration"]["original_fragment"].split()), visible)
            for field in ("source_page", "replacement", "status", "evidence"):
                self.assertNotIn(note["restoration"][field], text)
        image = report["inline_images"][0]
        self.assertEqual(image["start"]["page"], report["notes"][0]["callout"]["page"])
        self.assertEqual(image["width_px"], 280)
        self.assertEqual(image["height_px"], 40)
        self.assertAlmostEqual(image["width_pt"], 14 * image["font_em_pt"], delta=.02)
        self.assertAlmostEqual(image["height_pt"], 2 * image["font_em_pt"], delta=.02)
        self.assertEqual(report["notes"][0]["start"]["page"], report["notes"][0]["callout"]["page"])

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for restoration raster identity rejection")
    def test_restoration_pdf_crop_pixel_substitution_is_rejected(self):
        import io
        import pymupdf
        from PIL import Image
        job = make_restoration_job(self.job / "restoration-tampering")
        pdf = render.build(job)
        good = core.load_json(job / "build/verification.json")
        image = good["inline_images"][0]
        with pymupdf.open(pdf) as document:
            page = document[image["start"]["page"] - 1]
            xref = page.get_image_info(xrefs=True)[0]["xref"]
            buffer = io.BytesIO()
            Image.new("RGB", (280, 40), "red").save(buffer, format="PNG")
            page.replace_image(xref, stream=buffer.getvalue())
            document.saveIncr()
        report = render._verify(job / "build", core.load_json(job / "build/render-manifest.json"),
                                (job / "build/book.log").read_text(), (job / "build/book.aux").read_text())
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["inline_images"])
        self.assertTrue(any("raster pixels differ" in error for error in report["errors"]), report["errors"])


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for negative layout evidence")
    def test_actual_compiler_rejects_paragraph_and_hanging_indent_regressions(self):
        from unittest.mock import patch
        original = shutil.copyfile
        for old, new, expected in ((r"\parindent=2em", r"\parindent=1em", "required two-em"),
                                   (r"\hangindent=\BTListLabelWidth", r"\hangindent=0pt", "continuation does not hang"),
                                   (r"\parindent=2em\indent", r"\parindent=2em\baselineskip=0pt\lineskip=-3pt\indent", "actual PDF glyph lines overlap")):
            with self.subTest(expected=expected):
                job = make_flow_job(self.job / expected.replace(" ", "-"))
                def changed_style(source, destination, *args, **kwargs):
                    result = original(source, destination, *args, **kwargs)
                    if Path(destination).name == "translator.sty":
                        destination = Path(destination)
                        destination.write_text(destination.read_text().replace(old, new))
                    return result
                with patch.object(render.shutil, "copyfile", changed_style):
                    with self.assertRaisesRegex(ValueError, expected):
                        render.build(job)
                self.assertFalse(core.load_json(job / "build/verification.json")["checks"]["typography"])


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for actual PDF folio checks")
    def test_actual_pdf_wrong_outer_folio_and_footer_number_fail_pagination(self):
        import pymupdf
        job = make_inline_job(self.job / "folio-tampering")
        pdf = render.build(job)
        original = pdf.read_bytes()
        good = core.load_json(job / "build/verification.json")
        manifest = core.load_json(job / "build/render-manifest.json")
        log = (job / "build/book.log").read_text()
        aux = (job / "build/book.aux").read_text()
        body = next(row for row in good["pagination"] if row["printed_page"] == 1)
        for mutation in ("outer-folio", "footer-number"):
            with self.subTest(mutation=mutation):
                pdf.write_bytes(original)
                with pymupdf.open(pdf) as document:
                    page = document[body["physical_pdf_page"] - 1]
                    if mutation == "outer-folio":
                        header = body["headers"]["outer"]
                        baseline = page.rect.height - header["start"]["y_from_bottom_pt"]
                        rect = pymupdf.Rect(header["start"]["x_pt"] - .2, baseline - 12,
                                            header["end"]["x_pt"] + .2, baseline + 3)
                        page.add_redact_annot(rect)
                        page.apply_redactions(images=0, graphics=0)
                        page.insert_text((rect.x0, baseline), "9", fontsize=9)
                    else:
                        page.insert_text((page.rect.width / 2, page.rect.height - 12), "99", fontsize=9)
                    document.saveIncr()
                report = render._verify(job / "build", manifest, log, aux)
                self.assertFalse(report["checks"]["pagination"])
                self.assertTrue(any("outer header folio" in message or "footer text" in message for message in report["errors"]), report["errors"])


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for real glossary row alignment")
    def test_compiled_glossary_four_columns_share_the_first_text_baseline(self):
        import pymupdf
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                job = make_job(self.job / ("aligned-wrapped" if wrapped else "aligned-normal"))
                terms = core.load_json(job / "terms.json")
                if wrapped:
                    terms["terms"][1].update(source="Original field content wraps without body paragraph indentation. " * 4,
                                             target="Wrapped translation stays readable with aligned first baselines. " * 4)
                    core.save_json(job / "terms.json", terms)
                pdf = render.build(job)
                with pymupdf.open(pdf) as document:
                    for term in terms["terms"]:
                        baselines = []
                        cells = []
                        for column in range(4):
                            actual, lines, cell = self.glossary_cell(job, document, term["id"], column)
                            self.assertTrue(lines, (term["id"], column, actual))
                            baselines.append(min(span["origin"][1] for line in lines for span in line["spans"]))
                            cells.append((actual, lines, cell))
                        self.assertLess(max(baselines) - min(baselines), .1, (term["id"], baselines))
                        self.assertEqual("".join(cells[0][0].split()), str(term["number"]))
                        for column, field in ((1, "source"), (2, "target")):
                            actual, lines, cell = cells[column]
                            self.assertEqual("".join(actual.split()), "".join(term[field].split()))
                            self.assertAlmostEqual(min(span["origin"][0] for span in lines[0]["spans"]), cell.x0 + .3, delta=.1)
                            if wrapped and term["id"] == "Footer":
                                self.assertGreater(len(lines), 1)
                                self.assertTrue(all(abs(min(span["origin"][0] for span in line["spans"]) - cell.x0 - .3) < .2 for line in lines))


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for glossary alignment rejection")
    def test_compiled_glossary_alignment_gate_rejects_implicit_cell_paragraphs(self):
        from unittest.mock import patch
        original = shutil.copyfile
        def implicit_cells(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(destination).name == "translator.sty":
                destination = Path(destination)
                destination.write_text(destination.read_text().replace(
                    r"\newcommand{\BTTableCell}{\setlength{\parindent}{0pt}\noindent}",
                    r"\newcommand{\BTTableCell}{\setlength{\parindent}{0pt}}"))
            return result
        with patch.object(render.shutil, "copyfile", implicit_cells):
            with self.assertRaisesRegex(ValueError, "Glossary row .* baselines do not align"):
                render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertFalse(report["checks"]["typography"])
        self.assertTrue(all(value for name, value in report["checks"].items() if name != "typography"), report["errors"])
        self.assertTrue(any(max(row["first_text_baselines_pt"]) - min(row["first_text_baselines_pt"]) > 9
                            for row in report["glossary_rows"]))


if __name__ == "__main__":
    unittest.main()
