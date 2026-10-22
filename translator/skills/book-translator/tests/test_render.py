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
import unicodedata
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


def make_layout_regression_job(root: Path, blocks: list[dict], *, protected=()) -> Path:
    """Seal a small native-text manuscript using the normal rendering fixture."""
    root = make_inline_job(root)
    book = core.load_json(root / "book.json")
    book.update(blocks=blocks, protected=list(protected), notes=[], main_body_start=blocks[0]["id"])
    source = copy.deepcopy(book)
    source["agent_preface"] = []
    for block in source["blocks"]:
        block["target"] = []
    core.save_json(root / "book-source.json", source)
    core.save_json(root / "book.json", book)
    core.seal_source(root)
    return root


def pdf_ink_bounds(page, clip, scale=10):
    """Measure painted grayscale ink, independently of PDF glyph advance boxes."""
    import pymupdf
    from PIL import Image
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY,
                             clip=clip, alpha=False)
    mask = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples).point(
        lambda value: 255 if value < 128 else 0)
    bounds = mask.getbbox()
    if bounds is None:
        return None
    return ((pixmap.x + bounds[0]) / scale, (pixmap.y + bounds[1]) / scale,
            (pixmap.x + bounds[2]) / scale, (pixmap.y + bounds[3]) / scale)


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
        report = core.load_json(self.job / "build/verification.json")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["compiler"])
        self.assertIn("Missing character:", (self.job / "build/book.log").read_text(encoding="utf-8"))

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


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for fullwidth continuation ink")
    def test_fullwidth_leading_list_continuation_uses_visible_ink_not_advance_origin(self):
        import pymupdf
        content = ("金属层协同：一些制造商对金属层进行了协同设计。例如，DEC 的 CMOS-7 工艺中，"
                   "两层较低金属层与三层较高金属层之间的比例为（1:2）。类似地，TI 的 CO7 中，"
                   "前四层与最后一层的比例为（1:3）。Intel 的工艺则侧重于 M2 与 M3 之间的协同，"
                   "而这些层与更高层之间保持联系。")
        blocks = [
            {"id": "InkHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Continuation ink"}], "target": [{"text": "Continuation ink"}]},
            {"id": "FullwidthList", "kind": "list_item", "list_type": "ordered", "list_level": 0,
             "label": "1.", "source_pages": ["InlineSource"],
             "source": [{"text": content}], "target": [{"text": content}]}]
        job = make_layout_regression_job(self.job / "fullwidth-continuation", blocks)
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        row = next(item for item in report["typography"] if item["id"] == "FullwidthList")
        self.assertEqual(row["start"]["page"], row["end"]["page"])
        self.assertGreater(len(row["continuation_x_pt"]), 1)
        self.assertTrue(all(abs(x - row["start"]["x_pt"]) < .5 for x in row["continuation_x_pt"]))
        with pymupdf.open(pdf) as document:
            page = document[row["start"]["page"] - 1]
            first = page.rect.height - row["start"]["y_from_bottom_pt"]
            last = page.rect.height - row["end"]["y_from_bottom_pt"]
            raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT | pymupdf.TEXT_ACCURATE_BBOXES)
            chars = [char for block in raw["blocks"] for line in block.get("lines", [])
                     for span in line["spans"] for char in span["chars"]
                     if first - .1 <= char["origin"][1] <= last + .1]
            self.assertEqual("".join("".join(char["c"] for char in chars).split()),
                             "1." + "".join(content.split()))
            leading = [char for char in chars if char["c"] == "（" and
                       char["origin"][1] > first + .7 * row["font_em_pt"] and
                       char["origin"][0] < row["start"]["x_pt"] - .5 * row["font_em_pt"]]
            self.assertTrue(leading, "The fixture must retain a compressed opening parenthesis at a continuation edge")
            for char in leading:
                clip = pymupdf.Rect(char["origin"][0] - 1, char["bbox"][1] - 1,
                                    char["origin"][0] + row["font_em_pt"], char["bbox"][3] + 1)
                ink = pdf_ink_bounds(page, clip)
                self.assertIsNotNone(ink)
                self.assertAlmostEqual(ink[0], row["start"]["x_pt"], delta=.3,
                                       msg="Visible parenthesis ink, not its advance origin, must align with hanging text")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for sub-em continuation rejection")
    def test_actual_compiler_rejects_shifted_ordinary_continuation_even_when_ink_is_near_edge(self):
        import pymupdf
        from unittest.mock import patch
        content = "Continuation " * 18
        blocks = [
            {"id": "ShiftHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Continuation boundary"}], "target": [{"text": "Continuation boundary"}]},
            {"id": "ShiftedList", "kind": "list_item", "list_type": "ordered", "list_level": 0,
             "label": "1.", "source_pages": ["InlineSource"],
             "source": [{"text": content}], "target": [{"text": content}]}]
        job = make_layout_regression_job(self.job / "ordinary-continuation-shift", blocks)
        original = shutil.copyfile
        def shifted_style(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(destination).name == "translator.sty":
                destination = Path(destination)
                # This isolated negative controls an ordinary glyph's sidebearing,
                # not the production BODY family or its incidental hyphenation.
                # Latin Modern is already required by the native math-text profile.
                style = destination.read_text().replace(
                    r"\hangindent=\BTListLabelWidth", r"\hangindent=\dimexpr\BTListLabelWidth-1pt\relax")
                destination.write_text(style + "\n" +
                    r"\setmainfont{lmroman10-regular.otf}[BoldFont=lmroman10-bold.otf,"
                    r"ItalicFont=lmroman10-italic.otf,BoldItalicFont=lmroman10-bolditalic.otf]" + "\n")
            return result
        with patch.object(render.shutil, "copyfile", shifted_style):
            with self.assertRaisesRegex(ValueError, "continuation does not hang"):
                render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["typography"])
        self.assertFalse((job / "output.pdf").exists())
        row = next(item for item in report["typography"] if item["id"] == "ShiftedList")
        self.assertEqual(row["start"]["page"], row["end"]["page"])
        self.assertTrue(row["continuation_x_pt"])
        self.assertTrue(all(row["start"]["x_pt"] - x > .5 for x in row["continuation_x_pt"]))
        with pymupdf.open(job / "build/book.pdf") as document:
            page = document[row["start"]["page"] - 1]
            first = page.rect.height - row["start"]["y_from_bottom_pt"]
            last = page.rect.height - row["end"]["y_from_bottom_pt"]
            raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT | pymupdf.TEXT_ACCURATE_BBOXES)
            chars = [char for block in raw["blocks"] for line in block.get("lines", [])
                     for span in line["spans"] for char in span["chars"]
                     if first - .1 <= char["origin"][1] <= last + .1 and char["c"].strip()]
            baseline = min(char["origin"][1] for char in chars if char["origin"][1] > first + .7 * row["font_em_pt"])
            leading = min((char for char in chars if abs(char["origin"][1] - baseline) < .1),
                          key=lambda char: char["origin"][0])
            self.assertEqual(leading["c"], "C")
            self.assertGreater(row["start"]["x_pt"] - leading["origin"][0], .5)
            ink = pdf_ink_bounds(page, pymupdf.Rect(leading["origin"][0] - .2, leading["bbox"][1] - 1,
                                                   leading["bbox"][2], leading["bbox"][3] + 1))
            self.assertIsNotNone(ink)
            self.assertAlmostEqual(ink[0], row["start"]["x_pt"], delta=.5,
                                   msg="Ink alone would wrongly accept this displaced ordinary-text continuation")


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for inline radical baseline ownership")
    def test_inline_sqrt_radical_ink_belongs_to_its_prose_baseline(self):
        import pymupdf
        content = [{"text": "该操作如图 4.27 所示。最坏情况下，此算法会遍历版图中的所有瓦片。不过，平均而言，会访问 "},
                   {"protected": "RootN"},
                   {"text": " 个瓦片。此算法通过在搜索过程中重新调整出现的错位，处理设计固有的不对称性。"}]
        blocks = [
            {"id": "RadicalHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Inline radical ownership"}], "target": [{"text": "Inline radical ownership"}]},
            {"id": "RadicalParagraph", "kind": "paragraph", "source_pages": ["InlineSource"],
             "source": copy.deepcopy(content), "target": copy.deepcopy(content)}]
        job = make_layout_regression_job(self.job / "inline-radical", blocks,
                                         protected=[{"id": "RootN", "kind": "math", "value": r"\sqrt{N}"}])
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        row = next(item for item in report["typography"] if item["id"] == "RadicalParagraph")
        self.assertEqual(row["start"]["page"], row["end"]["page"])
        with pymupdf.open(pdf) as document:
            page = document[row["start"]["page"] - 1]
            first = page.rect.height - row["start"]["y_from_bottom_pt"]
            last = page.rect.height - row["end"]["y_from_bottom_pt"]
            chars = [char for trace in page.get_texttrace() for char in trace["chars"]
                     if first - row["font_em_pt"] <= char[2][1] <= last + .1]
            radical, = [char for char in chars if chr(char[0]) == "√"]
            radicand, = [char for char in chars if unicodedata.normalize("NFKC", chr(char[0])) == "N"]
            self.assertGreater(radical[1], 0)
            self.assertGreater(radicand[1], 0)
            self.assertGreater(radicand[2][1] - radical[2][1], .7 * row["font_em_pt"])
            prose_baselines = sorted({round(char[2][1], 2) for char in chars if "\u4e00" <= chr(char[0]) <= "\u9fff"})
            self.assertGreater(len(prose_baselines), 1)
            self.assertEqual(len(row["line_boxes_pt"]), len(prose_baselines),
                             "The raised radical must not create a phantom prose line")
            owner = min(range(len(prose_baselines)), key=lambda index: abs(prose_baselines[index] - radicand[2][1]))
            self.assertAlmostEqual(prose_baselines[owner], radicand[2][1], delta=.1)
            self.assertGreater(owner, 0, "The radical must follow an earlier real prose line")
            clip = pymupdf.Rect(radical[2][0] - .2, radicand[2][1] - 1.2 * row["font_em_pt"],
                                radicand[2][0] - .1, radicand[2][1] + 2)
            ink = pdf_ink_bounds(page, clip)
            self.assertIsNotNone(ink, "The radical outline must remain visibly painted")
            box = row["line_boxes_pt"][owner]
            self.assertLessEqual(box[1], ink[1] + .2)
            self.assertGreaterEqual(box[3], ink[3] - .2)
            self.assertLessEqual(row["line_boxes_pt"][owner - 1][3], ink[1] + .5)
            self.assertTrue(all(following[1] >= previous[3] - .5
                                for previous, following in zip(row["line_boxes_pt"], row["line_boxes_pt"][1:])))
            expected = content[0]["text"] + "√N" + content[2]["text"]
            visible = unicodedata.normalize("NFKC", page.get_text(clip=pymupdf.Rect(
                0, first - row["font_em_pt"], page.rect.width, last + 3)))
            self.assertEqual("".join(visible.split()), "".join(unicodedata.normalize("NFKC", expected).split()))

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for section-mark page ownership")
    def test_breaking_section_heading_owns_next_page_mark_and_preserves_header_parity(self):
        import pymupdf
        from unittest.mock import patch
        blocks = []
        def add(identifier, kind, text, **fields):
            blocks.append({"id": identifier, "kind": kind, "source_pages": ["InlineSource"],
                           "source": [{"text": text}], "target": [{"text": text}], **fields})
        add("MarkChapter", "heading", "Chapter mark", level=1)
        add("ChapterOpening", "paragraph", "The body begins on a physical left page, with logical folio one.")
        add("SamePageEarly", "heading", "Earlier section", level=2)
        add("SamePageLast", "heading", "Outgoing section", level=2)
        add("OutgoingText", "paragraph", "Outgoing content belongs to the last section actually printed on this page.")
        add("IncomingSection", "heading", "Incoming section", level=2)
        add("IncomingText", "paragraph", "The incoming heading and its first paragraph move together to the next page.")
        add("IncomingFollow", "paragraph", "The incoming section also owns the following physical right-page header.")
        add("ResetChapter", "heading", "Reset chapter", level=1)
        add("ResetText", "paragraph", "A new chapter must clear the previous section mark.")
        add("NoSectionFollow", "paragraph", "This right page has real chapter text but no section heading or section header.")
        job = make_layout_regression_job(self.job / "section-mark-ownership", blocks)
        original = render._Renderer.body
        def paginated_body(renderer):
            body = original(renderer)
            # Only arrange page capacity, as in the existing real-compiler fit fixtures.
            # BTHeading itself must choose the break and carry its own mark with it.
            body = body.replace(r"\BTHeading{2}{SamePageEarly}", r"\clearpage\BTHeading{2}{SamePageEarly}")
            body = body.replace(r"\BTHeading{2}{IncomingSection}",
                                r"\par\vspace*{.78\textheight}\par"
                                r"\BTHeading{2}{IncomingSection}")
            for identifier in ("IncomingFollow", "NoSectionFollow"):
                body = body.replace(r"\BTParagraph{block:" + identifier + "}",
                                    r"\clearpage\BTParagraph{block:" + identifier + "}")
            return body
        with patch.object(render._Renderer, "body", paginated_body):
            pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        boundaries = {row["id"]: row for row in report["block_boundaries"]}
        pages = {identifier: row["start"]["page"] for identifier, row in boundaries.items()}
        self.assertEqual(pages["MarkChapter"], 2)
        self.assertEqual(pages["SamePageEarly"], pages["SamePageLast"])
        self.assertEqual(pages["SamePageLast"], pages["OutgoingText"])
        self.assertEqual(pages["SamePageLast"] % 2, 1)
        self.assertEqual(pages["IncomingSection"], pages["OutgoingText"] + 1)
        self.assertEqual(pages["IncomingSection"], pages["IncomingText"])
        self.assertEqual(pages["IncomingFollow"], pages["IncomingSection"] + 1)
        self.assertEqual(pages["ResetChapter"], pages["IncomingFollow"] + 1)
        self.assertEqual(pages["NoSectionFollow"], pages["ResetChapter"] + 1)
        pagination = {row["physical_pdf_page"]: row for row in report["pagination"]}
        self.assertEqual(pagination[pages["SamePageLast"]]["section"], "SamePageLast")
        self.assertEqual(pagination[pages["IncomingSection"]]["section"], "IncomingSection")
        for identifier in ("ResetChapter", "NoSectionFollow"):
            self.assertEqual(pagination[pages[identifier]]["section"], "")
        expected_labels = {pages["MarkChapter"]: "Chapter mark", pages["SamePageLast"]: "Outgoing section",
                           pages["IncomingSection"]: "Chapter mark", pages["IncomingFollow"]: "Incoming section",
                           pages["ResetChapter"]: "Reset chapter", pages["NoSectionFollow"]: ""}
        with pymupdf.open(pdf) as document:
            for number, label in expected_labels.items():
                with self.subTest(physical_page=number):
                    page = document[number - 1]
                    row = pagination[number]
                    self.assertEqual(row["printed_page"], number - 1)
                    self.assertEqual(row["side"], "right" if number % 2 else "left")
                    top = 15 * render.PT_PER_MM
                    spans = [span for block in page.get_text("dict")["blocks"]
                             for line in block.get("lines", []) for span in line["spans"]
                             if span["origin"][1] < top - 2]
                    actual_header = "".join(span["text"] for span in spans)
                    self.assertEqual("".join(actual_header.split()),
                                     (label + str(number - 1) if number % 2 else str(number - 1) + label).replace(" ", ""))
                    self.assertEqual(row["headers"]["inner"]["text"].strip(), label)
                    self.assertEqual(row["headers"]["outer"]["text"].strip(), str(number - 1))
                    left = (20 if number % 2 else 8) * render.PT_PER_MM
                    right = left + report["compiled_geometry_pt"]["text_width"]
                    folio = next(span for span in spans if span["text"].strip() == str(number - 1))
                    self.assertAlmostEqual(folio["bbox"][2 if number % 2 else 0], right if number % 2 else left, delta=.2)
                    for block in blocks:
                        if pages[block["id"]] == number:
                            actual_body = page.get_text(clip=pymupdf.Rect(0, top - 1, page.rect.width, page.rect.height))
                            self.assertIn("".join(block["target"][0]["text"].split()), "".join(actual_body.split()))
            outgoing = document[pages["OutgoingText"] - 1]
            incoming = document[pages["IncomingSection"] - 1]
            self.assertFalse(outgoing.search_for("Incoming section"))
            heading, = incoming.search_for("Incoming section")
            paragraph, = incoming.search_for("The incoming heading")
            self.assertLess(heading.y1, paragraph.y0)


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

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for local inline composition evidence")
    def test_local_inline_breaks_keep_math_url_and_compound_inside_native_measure(self):
        import pymupdf
        math_content = [{"text": "EvidenceBefore"}, {"page": "After"}, {"text": ""},
                        {"protected": "LongMath"}, {"text": "。"}]
        url = "这是一段用于说明本地网址换行位置的普通中文文本：www.computer.org/tab/DATC。"
        bibliography = ("X. Hong, T. Xue, E. Kuh, C. Cheng, and J. Huang. An example. Performance-driven "
                        "steiner tree algorithms for global routing. Proceedings of 30th Design "
                        "Automation Conference, pages 177–181, June 1993.")
        blocks = [
            {"id": "InlineHeading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
             "source": [{"text": "Local inline composition"}], "target": [{"text": "Local inline composition"}]},
            {"id": "BeforeMath", "kind": "paragraph", "source_pages": ["InlineSource", "After"],
             "source": copy.deepcopy(math_content), "target": copy.deepcopy(math_content)},
            {"id": "Url", "kind": "paragraph", "source_pages": ["After"],
             "source": [{"text": url}], "target": [{"text": url}]},
            {"id": "Compound", "kind": "list_item", "list_type": "ordered", "list_level": 0,
             "label": "[HXK+93]", "source_pages": ["After"],
             "source": [{"text": bibliography}], "target": [{"text": bibliography}]}]
        job = make_inline_job(self.job / "local-inline-breaks")
        for filename in ("book-source.json", "book.json"):
            book = core.load_json(job / filename)
            book.update(blocks=copy.deepcopy(blocks), notes=[], main_body_start="InlineHeading",
                        protected=[{"id": "LongMath", "kind": "math", "value": r"\mathrm{" + "M" * 32 + "}"}])
            if filename == "book-source.json":
                for block in book["blocks"]:
                    block["target"] = []
            book["source_pages"].append({"id": "After", "locator": "inline-source.pdf:1",
                                         "printed_label": "S2", "label_verified": True,
                                         "evidence": "Synthetic internal source boundary."})
            core.save_json(job / filename, book)
        core.seal_source(job)
        pdf = render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        geometry = report["compiled_geometry_pt"]
        for key, expected_mm in (("paper_width", 148), ("paper_height", 210), ("text_width", 120),
                                 ("text_height", 180), ("odd_left", 20), ("even_left", 8), ("top", 15)):
            self.assertAlmostEqual(geometry[key] / render.PT_PER_MM, expected_mm, delta=.07)
        log = (job / "build/book.log").read_text(encoding="utf-8")
        self.assertNotRegex(log, r"Overfull \\[hv]box|Underfull \\hbox|Missing character:")
        typography = {row["id"]: row for row in report["typography"]}
        evidence = {}
        with pymupdf.open(pdf) as document:
            for identifier in ("BeforeMath", "Url", "Compound"):
                row = typography[identifier]
                page = document[row["start"]["page"] - 1]
                first = page.rect.height - row["start"]["y_from_bottom_pt"]
                last = page.rect.height - row["end"]["y_from_bottom_pt"]
                left = (20 if row["start"]["page"] % 2 else 8) * render.PT_PER_MM
                right = left + geometry["text_width"]
                # Source labels occupy the outer margin; the prose region is measured separately.
                chars = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"]
                         if first - .2 <= c[2][1] <= last + .2 and left - .2 <= c[2][0] <= right + .2]
                baselines = sorted({round(c[2][1], 2) for s, _, c in chars if s.strip()})
                lines = ["".join(s for s, _, c in chars if abs(c[2][1] - y) < .05) for y in baselines]
                self.assertGreater(len(lines), 1, identifier)
                self.assertTrue(all(left - .2 <= c[2][0] < right for s, _, c in chars if s.strip()))
                self.assertTrue(all(not line.rstrip().endswith(tuple("（([{“‘")) and
                                    not line.lstrip().startswith(tuple("，。；：、）)]}”’")) for line in lines), lines)
                evidence[identifier] = {"lines": lines, "baselines_pdf_pt": baselines}
                if identifier == "BeforeMath":
                    prefix = [c for s, _, c in chars if s in "EvidenceBefore"]
                    formula = [(t, c) for s, t, c in chars if s == "M"]
                    self.assertEqual(len(formula), 32)
                    self.assertEqual("".join(s for s, _, _ in chars), "EvidenceBefore" + "M" * 32 + "。")
                    self.assertEqual({t["font"] for t, _ in formula}, {"LMRoman10-Regular"})
                    self.assertTrue(all(abs(t["size"] - 10 * 72 / 72.27) < .02 for t, _ in formula))
                    self.assertEqual(len({round(c[2][1], 2) for _, c in formula}), 1)
                    self.assertGreater(formula[0][1][2][1], prefix[-1][2][1] + 5)
                    self.assertLess(formula[-1][1][3][2] - formula[0][1][2][0], report["compiled_geometry_pt"]["text_width"])
                    mark, = [mark for mark in report["source_marks"] if mark["source_page"] == "After"]
                    self.assertEqual(mark["page"], row["start"]["page"])
                    self.assertAlmostEqual(page.rect.height - mark["y_from_bottom_pt"], prefix[-1][2][1], delta=.1)
                    self.assertAlmostEqual(mark["x_pt"], prefix[-1][3][2], delta=.1)
                elif identifier == "Url":
                    self.assertEqual("".join("".join(lines).split()), "".join(url.split()))
                    self.assertTrue(any(line.rstrip().endswith((".", "/")) for line in lines[:-1]), lines)
                else:
                    expected = "[HXK+93]" + "".join(bibliography.split())
                    remaining = expected
                    compound_start = expected.index("Performance-driven")
                    compound_breaks = []
                    for line in lines:
                        text = "".join(line.split())
                        if not remaining.startswith(text) and text.endswith("-"):
                            text = text[:-1]
                            break_at = len(expected) - len(remaining) + len(text)
                            if compound_start < break_at < compound_start + len("Performance"):
                                compound_breaks.append(break_at)
                        self.assertTrue(remaining.startswith(text), (line, remaining))
                        remaining = remaining[len(text):]
                    self.assertEqual(remaining, "")
                    self.assertTrue(compound_breaks, "A break inside the compound's first word is required: " + repr(lines))
                    self.assertTrue(all(abs(x - row["start"]["x_pt"]) < .5 for x in row["continuation_x_pt"]))
        core.save_json(job / "inline-evidence.json", evidence)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for unbroken inline glyph conservation")
    def test_unbroken_inline_policy_preserves_native_glue_first_term_and_emphasis(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        formula = r"x_1+\mathrm{M}"
        book["protected"] = [{"id": "Math", "kind": "math", "value": formula}]
        terms = {"terms": [{"id": "First", "number": 1, "target": "方法"}]}
        native_math = r"\(" + formula + r"\)"
        literal = r"A pre-post www.a.org/a-b%20/#_{x}\input{BAD} & $ ~ ^ Z"
        rows = [
            ("Cjk", [{"text": "前"}, {"protected": "Math"}, {"text": "后"}], "前" + native_math + "后"),
            ("Space", [{"text": "前 "}, {"protected": "Math"}, {"text": " 后"}], "前 " + native_math + " 后"),
            ("Term", [{"term": "First"}, {"protected": "Math"}, {"text": "后"}],
             r"\BTFirstTerm{方法}{1}" + native_math + "后"),
            ("Data", [{"text": literal}], render.escape(literal))]
        body = [r"\begin{document}\pagestyle{empty}"]
        for style, command in enumerate((r"\normalfont", r"\normalfont\bfseries",
                                         r"\normalfont\itshape", r"\normalfont\bfseries\itshape")):
            if style:
                body.append(r"\clearpage")
            body.append("{" + command)
            for label, tokens, native in rows:
                actual = render._Renderer(self.job, book, terms).inline(tokens)
                # Measure real shaping and native delimiters, not generated-source spelling.
                for suffix, tex in (("N", native), ("P", actual)):
                    key = label + suffix
                    body.append(r"\BTTestMetric{" + str(style) + key + "}{" + tex + "}")
                    body.append(r"\noindent\makebox[50pt][l]{" + key + r"}\hbox{" + tex + r"}\par\vspace{8pt}")
            actual = render._Renderer(self.job, book, terms).inline(rows[0][1])
            for suffix, tex in (("N", rows[0][2]), ("P", actual)):
                body.append(r"\noindent\makebox[50pt][l]{Emph" + suffix + r"}A\emph{" + tex + r"B}Z\par\vspace{8pt}")
            body.append("}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture("inline-conservation", body)
        self.assertNotIn("Missing character:", log)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            for style, page in enumerate(document):
                def glyphs(label):
                    word, = [word for word in page.get_text("words") if word[4] == label]
                    baseline = next(c[2][1] for t in page.get_texttrace() for c in t["chars"]
                                    if chr(c[0]) == label[0] and abs(c[2][0] - word[0]) < .1
                                    and word[1] <= c[2][1] <= word[3])
                    return [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"]
                            if c[2][0] > word[2] + .5 and abs(c[2][1] - baseline) < 9]
                for label in [row[0] for row in rows] + ["Emph"]:
                    native, actual = glyphs(label + "N"), glyphs(label + "P")
                    self.assertEqual([(s, t["font"], c[1], t["size"]) for s, t, c in actual],
                                     [(s, t["font"], c[1], t["size"]) for s, t, c in native], (style, label))
                    self.assertTrue(all(c[1] > 0 and t["type"] == 0 for _, t, c in actual))
                    for (_, _, a), (_, _, n) in zip(actual, native):
                        for axis in (0, 1):
                            self.assertAlmostEqual(a[2][axis] - actual[0][2][2][axis],
                                                   n[2][axis] - native[0][2][2][axis], delta=.02)
                    if label != "Emph":
                        self.assertAlmostEqual(metrics[str(style) + label + "P"], metrics[str(style) + label + "N"], delta=2)
                    if label == "Data":
                        self.assertEqual("".join(s for s, _, _ in actual).replace(" ", ""), literal.replace(" ", ""))
                    if label == "Term":
                        marker, = [(t, c) for s, t, c in actual if s == "1" and c[2][1] < actual[0][2][2][1] - 1]
                        self.assertLess(marker[0]["size"], actual[0][1]["size"])
                    if label == "Emph":
                        self.assertEqual(actual[0][1]["font"], actual[-1][1]["font"])
                        # Compare Latin text outside emphasis with the alternate style's Latin control.
                        self.assertNotEqual(actual[0][1]["font"], actual[-2][1]["font"])
                    evidence.append({"style": style, "case": label,
                                     "glyphs": [(s, t["font"], c[1], t["size"], c[2]) for s, t, c in actual]})
        core.save_json(root / "inline-evidence.json", {"cases": evidence})

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for native internal math break evidence")
    def test_inline_policy_retains_original_internal_math_breaks_and_punctuation(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        formula = "+".join(f"a_{{{index}}}" for index in range(1, 41))
        book["protected"] = [{"id": "Sum", "kind": "math", "value": formula}]
        tokens = [{"text": "原样公式："}, {"protected": "Sum"}, {"text": "。后文继续。"}]
        actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
        native = "原样公式：" + r"\(" + formula + r"\)" + "。后文继续。"
        body = [r"\begin{document}\pagestyle{empty}"]
        for tex in (native, actual):
            body.append(r"\BTParagraph{sum}{" + tex + r"}\clearpage")
        # Pressure the opening/closing boundary without changing paper, measure, or fonts.
        short = r"\mathrm{" + "M" * 16 + "}"
        book["protected"] = [{"id": "Sum", "kind": "math", "value": short}]
        punct = [{"text": "中文边界" * 10 + "（"}, {"protected": "Sum"}, {"text": "）" + "后文继续" * 6 + "。"}]
        actual_punct = render._Renderer(self.job, book, {"terms": []}).inline(punct)
        native_punct = punct[0]["text"] + r"\(" + short + r"\)" + punct[2]["text"]
        for tex in (native_punct, actual_punct):
            body.append(r"\BTParagraph{punct}{" + tex + r"}\clearpage")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture("inline-native-breaks", body)
        self.assertNotRegex(log, r"Underfull \\hbox|Missing character:")
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            for start in (0, 2):
                signatures = []
                for page in (document[start], document[start + 1]):
                    chars = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"] if chr(c[0]).strip()]
                    self.assertTrue(all(c[1] > 0 for _, _, c in chars))
                    signatures.append([(s, t["font"], c[1], round(c[2][0] - chars[0][2][2][0], 2),
                                        round(c[2][1] - chars[0][2][2][1], 2)) for s, t, c in chars])
                    lines = [line for line in page.get_text().splitlines() if line.strip()]
                    self.assertGreaterEqual(len(lines), 3)
                    self.assertTrue(all(not line.rstrip().endswith("（") and not line.lstrip().startswith(("）", "。")) for line in lines), lines)
                    evidence.append(lines)
                    if start == 0:
                        a = [(t, c) for s, t, c in chars if unicodedata.normalize("NFKC", s) == "a"]
                        self.assertEqual(len(a), 40)
                        self.assertEqual({t["font"] for t, _ in a}, {"LatinModernMath-Regular"})
                        self.assertGreaterEqual(len({round(c[2][1], 1) for _, c in a}), 3)
                self.assertEqual([entry[:3] for entry in signatures[0]], [entry[:3] for entry in signatures[1]])
                for native_glyph, policy_glyph in zip(*signatures):
                    self.assertAlmostEqual(native_glyph[3], policy_glyph[3], delta=.02)
                    self.assertAlmostEqual(native_glyph[4], policy_glyph[4], delta=.02)
        core.save_json(root / "inline-evidence.json", {"cases": evidence})

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for two-sided closing-fragment evidence")
    def test_inline_closing_fragments_preserve_native_line_ownership_and_glue(self):
        import pymupdf
        prefix = "甲" * 8
        tail = "+" + "+".join(f"a_{{{index}}}" for index in range(1, 9))
        cases = (
            ("Escaped", r"\}", None),
            ("Alias", r"\rbrace", None),
            ("TransparentFont", r"{\mathrm{\rbrace}}", None),
            ("MathClose", r"\mathclose{\rbrace}", None),
            ("SizedClose", r"\bigr\rbrace", None),
            ("UnicodeClose", "⟩", None),
            ("LeadingSpace", r"\thinspace{\mathnormal{\rbrace}}", None),
            ("MathPunct", r"\mathpunct{;}", None),
            ("UnicodePunct", ",", None),
            ("InternalTail", r"\mathclose{\rbrace}" + tail, None),
            ("CjkTextClose", None, "）"),
            ("AsciiTextClose", None, ")"),
            ("AsciiTextPunct", None, ","),
            ("BareBar", "|", None),
            ("BareNorm", r"\Vert", None),
            ("UnmatchedBarTail", "|q", None),
            ("CompleteAbs", "|q|", None),
            ("CompleteNorm", r"\Vert r\Vert", None),
        )
        complete_fences = {"CompleteAbs": "q", "CompleteNorm": "r"}
        book = core.load_json(self.job / "book.json")
        body = [r"\newdimen\BTClosingMeasure\begin{document}\pagestyle{empty}"]
        labels = ("N0", "P0", "N1", "P1", "NU", "PU")
        for index, (name, fragment, ordinary) in enumerate(cases):
            if index:
                body.append(r"\clearpage")
            body.append(r"\noindent " + name + r"\par\vspace{4pt}")
            book["protected"] = [{"id": "Variable", "kind": "math", "value": "N_i"}]
            tokens = [{"text": prefix}, {"protected": "Variable"}]
            native = prefix + r"\(N_i\)"
            if fragment is not None:
                book["protected"].append({"id": "Fragment", "kind": "math", "value": fragment})
                tokens.append({"protected": "Fragment"})
                native += r"\(" + fragment + r"\)"
            else:
                tokens.append({"text": ordinary})
                native += render.escape(ordinary)
            actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
            # Measure the native predecessor, so the test pressures this boundary
            # without pinning BODY metrics or a book-specific capacity/value.
            body.append(r"\sbox{\BTTempBox}{" + prefix + r"\(N_i\)}\BTClosingMeasure=\wd\BTTempBox")
            for offset, suffix in ((0, "0"), (.5, "1")):
                for label, tex in (("N" + suffix, native), ("P" + suffix, actual)):
                    body.append(r"\noindent\makebox[50pt][l]{" + label +
                                r"}\begin{minipage}[t]{\dimexpr\BTClosingMeasure+" + str(offset) +
                                r"pt\relax}\parindent=0pt\noindent " + tex +
                                r"\par\end{minipage}\par\vspace{18pt}")
            for label, tex in (("NU", native), ("PU", actual)):
                body.append(r"\BTTestMetric{" + name + label + "}{" + tex + "}")
                body.append(r"\noindent\makebox[50pt][l]{" + label + r"}\hbox{" + tex + r"}\par\vspace{18pt}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture("inline-closing-fragments", body)
        self.assertNotIn("Missing character:", log)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), len(cases))
            for page, (name, _, _) in zip(document, cases):
                traces = page.get_texttrace()
                left = (20 if (page.number + 1) % 2 else 8) * render.PT_PER_MM
                baselines = []
                for label in labels:
                    word, = [word for word in page.get_text("words") if word[4] == label]
                    marker = next(char for trace in traces for char in trace["chars"]
                                  if chr(char[0]) == label[0] and abs(char[2][0] - word[0]) < .1
                                  and word[1] <= char[2][1] <= word[3])
                    baselines.append(marker[2][1])
                rows = {}
                for row_index, label in enumerate(labels):
                    end = baselines[row_index + 1] - 12 if row_index + 1 < len(labels) else page.rect.height
                    chars = [(chr(char[0]), trace, char) for trace in traces for char in trace["chars"]
                             if chr(char[0]).strip() and char[2][0] >= left + 50 * 72 / 72.27 - .2
                             and baselines[row_index] - 12 <= char[2][1] < end]
                    self.assertTrue(chars, (name, label))
                    self.assertTrue(all(char[1] > 0 and trace["type"] == 0 for _, trace, char in chars), (name, label))
                    self.assertEqual(sum(symbol == "甲" for symbol, _, _ in chars), len(prefix), (name, label))
                    rows[label] = chars
                for native_label, policy_label in (("N0", "P0"), ("N1", "P1"), ("NU", "PU")):
                    with self.subTest(fragment=name, row=policy_label):
                        native, actual = rows[native_label], rows[policy_label]
                        self.assertEqual([(s, t["font"], c[1], t["size"]) for s, t, c in actual],
                                         [(s, t["font"], c[1], t["size"]) for s, t, c in native])
                        if policy_label != "PU" and name in complete_fences:
                            # A complete leading abs/norm is a whole expression, not
                            # a closing fragment: its legitimate added edge may move
                            # it after Ni. Bare/unmatched bars below remain native-only.
                            keep = lambda symbol: unicodedata.normalize("NFKC", symbol) not in ("甲", "N", "i")
                            native_fence = [(s, t, c) for s, t, c in native if keep(s)]
                            actual_fence = [(s, t, c) for s, t, c in actual if keep(s)]
                            native_inner, = [c for s, _, c in native_fence
                                             if unicodedata.normalize("NFKC", s) == complete_fences[name]]
                            actual_inner, = [c for s, _, c in actual_fence
                                             if unicodedata.normalize("NFKC", s) == complete_fences[name]]
                            variable, = [c for s, _, c in actual if unicodedata.normalize("NFKC", s) == "N"]
                            self.assertGreaterEqual(len(actual_fence), 3)
                            self.assertGreater(actual_inner[2][1], variable[2][1] + 5,
                                               "A complete leading abs/norm must retain a usable before-expression edge")
                            for (_, _, produced), (_, _, original) in zip(actual_fence, native_fence):
                                for axis in (0, 1):
                                    self.assertAlmostEqual(produced[2][axis] - actual_inner[2][axis],
                                                           original[2][axis] - native_inner[2][axis], delta=.02,
                                                           msg="Opening fence, interior and closing fence must travel as a native-shaped unit")
                        else:
                            for (symbol, _, produced), (_, _, original) in zip(actual, native):
                                for axis in (0, 1):
                                    # A taken before-N opportunity changes preceding-line
                                    # justification, not glyph ownership or native math advances.
                                    # Unbroken rows still compare every horizontal coordinate.
                                    if axis == 0 and policy_label != "PU" and symbol == "甲":
                                        continue
                                    self.assertAlmostEqual(produced[2][axis] - actual[0][2][2][axis],
                                                           original[2][axis] - native[0][2][2][axis], delta=.02)
                        if name == "Escaped" and policy_label != "PU":
                            variable, = [char for symbol, _, char in actual if unicodedata.normalize("NFKC", symbol) == "N"]
                            closing, = [char for symbol, _, char in actual if symbol == "}"]
                            self.assertGreater(variable[2][1], actual[0][2][2][1] + 5)
                            self.assertAlmostEqual(closing[2][1], variable[2][1], delta=.02,
                                                   msg="A separately protected closing fragment must not become an orphan")
                        if name == "InternalTail" and policy_label != "PU":
                            terms = [char for symbol, _, char in actual if unicodedata.normalize("NFKC", symbol) == "a"]
                            self.assertEqual(len(terms), 8)
                            self.assertGreaterEqual(len({round(char[2][1], 1) for char in terms}), 2,
                                                    "Suppressing the leading close opportunity must not box internal math")
                        evidence.append({"case": name, "row": policy_label,
                                         "native_glyphs": [(s, t["font"], c[1], t["size"], c[2]) for s, t, c in native],
                                         "actual_glyphs": [(s, t["font"], c[1], t["size"], c[2]) for s, t, c in actual]})
                self.assertAlmostEqual(metrics[name + "NU"], metrics[name + "PU"], delta=2,
                                       msg="Unbroken native glue and advances must remain unchanged")
        core.save_json(root / "inline-evidence.json", {"cases": evidence})


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for indivisible overwide math rejection")
    def test_inline_policy_still_rejects_a_genuinely_indivisible_overwide_atom(self):
        import pymupdf
        content = [{"text": "原样公式："}, {"protected": "Overwide"}, {"text": "。"}]
        blocks = [{"id": "OverwideParagraph", "kind": "paragraph", "source_pages": ["InlineSource"],
                   "source": copy.deepcopy(content), "target": copy.deepcopy(content)}]
        job = make_layout_regression_job(self.job / "inline-overwide", blocks,
                                         protected=[{"id": "Overwide", "kind": "math",
                                                     "value": r"\mathrm{" + "W" * 80 + "}"}])
        with self.assertRaisesRegex(ValueError, "overfull output"):
            render.build(job)
        report = core.load_json(job / "build/verification.json")
        self.assertFalse(report["checks"]["overflow"])
        with pymupdf.open(job / "build/book.pdf") as document:
            glyphs = [(t, c) for page in document for t in page.get_texttrace()
                      for c in t["chars"] if chr(c[0]) == "W"]
            self.assertEqual(len(glyphs), 80)
            self.assertEqual({t["font"] for t, _ in glyphs}, {"LMRoman10-Regular"})
            self.assertTrue(all(abs(t["size"] - 10 * 72 / 72.27) < .02 for t, _ in glyphs))
            self.assertEqual(len({round(c[2][1], 2) for _, c in glyphs}), 1)
            self.assertGreater(max(c[3][2] for _, c in glyphs) - min(c[2][0] for _, c in glyphs),
                               report["compiled_geometry_pt"]["text_width"])
        self.assertFalse((job / "output.pdf").exists())

    def remaining_overflow_root(self, name):
        """Keep opt-in focused evidence outside the disposable unittest job."""
        import os
        evidence = os.environ.get("BT_REMAINING_OVERFLOW_EVIDENCE")
        return (Path(evidence).resolve() / (self._testMethodName + "-" + name)
                if evidence else self.job / name)

    def save_remaining_overflow_pdf(self, root, pdf):
        """Retain actual painted pages, glyph identities and per-glyph ink counts."""
        import pymupdf
        evidence = []
        with pymupdf.open(pdf) as document:
            for page in document:
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(
                    root / ("actual-page-%02d.png" % (page.number + 1)))
                glyphs = []
                for trace in page.get_texttrace():
                    for char in trace["chars"]:
                        symbol = chr(char[0])
                        if not symbol.strip():
                            continue
                        self.assertGreater(char[1], 0, symbol + " must not be .notdef")
                        self.assertEqual(trace["type"], 0)
                        self.assertGreater(trace["opacity"], 0)
                        ink = page.get_pixmap(matrix=pymupdf.Matrix(3, 3),
                                              clip=pymupdf.Rect(char[3]), colorspace=pymupdf.csGRAY,
                                              alpha=False)
                        painted = sum(value < 200 for value in ink.samples)
                        self.assertGreater(painted, 2, symbol + " must paint actual ink")
                        glyphs.append({"symbol": symbol, "font": trace["font"], "glyph": char[1],
                                       "size_pt": trace["size"], "origin_pt": char[2],
                                       "bounds_pt": char[3], "ink_pixels_at_216dpi": painted})
                evidence.append({"page": page.number + 1, "glyphs": glyphs})
        core.save_json(root / "actual-glyph-and-ink-evidence.json", {"pages": evidence})

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for actual slash seam evidence")
    def test_remaining_ordinary_slash_wraps_without_changing_literal_consumers(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        compound = "input/output"
        url = "https://www.example.org/input/output"
        book["protected"] = [{"id": "Literal", "kind": "name", "value": compound},
                             {"id": "Code", "kind": "code", "value": compound}]
        cases = [("Ordinary", [{"text": compound}], render.escape(compound)),
                 ("Literal", [{"protected": "Literal"}], render._literal_text(compound)),
                 ("Code", [{"protected": "Code"}], r"{\ttfamily " + compound + "}"),
                 ("Url", [{"text": url}], render._literal_text(url)),
                 ("NbspBefore", [{"text": "input\u00a0/output"}], "input\u00a0/output"),
                 ("NbspAfter", [{"text": "input/\u00a0output"}], "input/\u00a0output")]
        body = [r"\newdimen\BTSlashMeasure\begin{document}\pagestyle{empty}"]
        for style, command in enumerate((r"\normalfont", r"\normalfont\bfseries",
                                         r"\normalfont\itshape", r"\normalfont\bfseries\itshape")):
            if style:
                body.append(r"\clearpage")
            body.append("{" + command)
            for label, tokens, native in cases:
                actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
                for suffix, tex in (("N", native), ("P", actual)):
                    body.append(r"\BTTestMetric{" + str(style) + label + suffix + "}{" + tex + "}")
                    body.append(r"\noindent\makebox[80pt][l]{" + label + suffix + r"}\hbox{" + tex + r"}\par\vspace{5pt}")
            actual = render._Renderer(self.job, book, {"terms": []}).inline([{"text": compound}])
            body.append(r"\sbox{\BTTempBox}{output}\BTSlashMeasure=\wd\BTTempBox")
            body.append(r"\noindent\makebox[80pt][l]{Wrap}\begin{minipage}[t]{\dimexpr\BTSlashMeasure+1pt\relax}"
                        r"\parindent=0pt\noindent " + actual + r"\par\end{minipage}\par\vspace{15pt}")
            actual_url = render._Renderer(self.job, book, {"terms": []}).inline([{"text": url}])
            body.append(r"\BTSlashMeasure=0pt")
            for piece in re.findall(r"[^./]*[./]|[^./]+$", url):
                body.append(r"\sbox{\BTTempBox}{" + render._literal_text(piece) +
                            r"}\ifdim\wd\BTTempBox>\BTSlashMeasure\BTSlashMeasure=\wd\BTTempBox\fi")
            body.append(r"\noindent\makebox[80pt][l]{UrlWrap}\begin{minipage}[t]{\dimexpr\BTSlashMeasure+1pt\relax}"
                        r"\parindent=0pt\noindent " + actual_url + r"\par\end{minipage}\par}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture(self.remaining_overflow_root("slash"), body)
        self.assertNotIn("Missing character:", log)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            for style, page in enumerate(document):
                for label, _, _ in cases:
                    native = self.font_row_glyphs(page, label + "N")
                    actual = self.font_row_glyphs(page, label + "P")
                    self.assertEqual([(s, t["font"], c[1], t["size"]) for s, t, c in actual],
                                     [(s, t["font"], c[1], t["size"]) for s, t, c in native])
                    self.assertAlmostEqual(metrics[str(style) + label + "N"],
                                           metrics[str(style) + label + "P"], delta=2)
                    for (_, _, a), (_, _, n) in zip(actual, native):
                        self.assertAlmostEqual(a[2][0] - actual[0][2][2][0],
                                               n[2][0] - native[0][2][2][0], delta=.02)
                marker, = [word for word in page.get_text("words") if word[4] == "Wrap"]
                url_marker, = [word for word in page.get_text("words") if word[4] == "UrlWrap"]
                chars = [(chr(c[0]), c) for t in page.get_texttrace() for c in t["chars"]
                         if c[2][0] > marker[2] + .5 and marker[1] <= c[2][1] < url_marker[1] - 5 and chr(c[0]).strip()]
                lines = ["".join(s for s, c in chars if abs(c[2][1] - y) < .05)
                         for y in sorted({round(c[2][1], 2) for _, c in chars})]
                self.assertEqual(lines, ["input/", "output"])
                url_chars = [(chr(c[0]), c) for t in page.get_texttrace() for c in t["chars"]
                             if c[2][0] > url_marker[2] + .5 and c[2][1] >= url_marker[1] and chr(c[0]).strip()]
                url_lines = ["".join(s for s, c in url_chars if abs(c[2][1] - y) < .05)
                             for y in sorted({round(c[2][1], 2) for _, c in url_chars})]
                self.assertGreater(len(url_lines), 1)
                self.assertEqual("".join(url_lines), url)
                self.assertTrue(all(line.endswith((".", "/")) for line in url_lines[:-1]), url_lines)
                evidence.append({"style": style, "wrapped_lines": lines, "url_lines": url_lines})
        core.save_json(root / "slash-consumer-evidence.json", {"metrics_sp": metrics, "cases": evidence})
        self.save_remaining_overflow_pdf(root, root / "book.pdf")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for original-name seam evidence")
    def test_remaining_source_hyphen_names_wrap_only_at_original_seams_in_all_styles(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        names = ("Kernighan-Lin", "Fiduccia-Mattheyses", "Kernighan-Lin-Fiduccia")
        book["protected"] = [{"id": "Name" + str(i), "kind": "name", "value": name}
                             for i, name in enumerate(names)]
        body = [r"\newdimen\BTNameMeasure\begin{document}\pagestyle{empty}"]
        for style, command in enumerate((r"\normalfont", r"\normalfont\bfseries",
                                         r"\normalfont\itshape", r"\normalfont\bfseries\itshape")):
            if style:
                body.append(r"\clearpage")
            body.append("{" + command)
            for index, name in enumerate(names):
                native = render._literal_text(name)
                actual = render._Renderer(self.job, book, {"terms": []}).inline([{"protected": "Name" + str(index)}])
                for suffix, tex in (("N", native), ("P", actual)):
                    label = "Name" + str(index) + suffix
                    body.append(r"\BTTestMetric{" + str(style) + label + "}{" + tex + "}")
                    body.append(r"\noindent\makebox[60pt][l]{" + label + r"}\hbox{" + tex + r"}\par\vspace{5pt}")
                body.append(r"\BTNameMeasure=0pt")
                for constituent in name.split("-"):
                    body.append(r"\sbox{\BTTempBox}{" + render._literal_text(constituent + "-") +
                                r"}\ifdim\wd\BTTempBox>\BTNameMeasure\BTNameMeasure=\wd\BTTempBox\fi")
                body.append(r"\noindent\makebox[60pt][l]{Wrap" + str(index) +
                            r"}\begin{minipage}[t]{\dimexpr\BTNameMeasure+1pt\relax}\parindent=0pt\noindent " +
                            actual + r"\par\end{minipage}\par\vspace{16pt}")
            body.append("}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture(self.remaining_overflow_root("source-names"), body)
        self.assertNotIn("Missing character:", log)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            fonts = set()
            for style, page in enumerate(document):
                for index, name in enumerate(names):
                    native = self.font_row_glyphs(page, "Name" + str(index) + "N")
                    actual = self.font_row_glyphs(page, "Name" + str(index) + "P")
                    signature = lambda chars: [(s, t["font"], c[1], t["size"]) for s, t, c in chars if s.strip()]
                    self.assertEqual("".join(s for s, _, _ in native), name)
                    self.assertEqual(signature(actual), signature(native))
                    fonts.add(native[0][1]["font"])
                    self.assertAlmostEqual(metrics[str(style) + "Name" + str(index) + "N"],
                                           metrics[str(style) + "Name" + str(index) + "P"], delta=2)
                    for (_, _, a), (_, _, n) in zip(actual, native):
                        self.assertAlmostEqual(a[2][0] - actual[0][2][2][0],
                                               n[2][0] - native[0][2][2][0], delta=.02)
                    marker, = [word for word in page.get_text("words") if word[4] == "Wrap" + str(index)]
                    next_marker = page.search_for("Name" + str(index + 1) + "N") if index + 1 < len(names) else []
                    end = next_marker[0].y0 - 4 if next_marker else page.rect.height
                    wrapped = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"]
                               if c[2][0] > marker[2] + .5 and marker[1] <= c[2][1] < end and chr(c[0]).strip()]
                    self.assertEqual(signature(wrapped), signature(native), "No constituent hyphen may be invented")
                    lines = ["".join(s for s, _, c in wrapped if abs(c[2][1] - y) < .05)
                             for y in sorted({round(c[2][1], 2) for _, _, c in wrapped})]
                    self.assertGreater(len(lines), 1)
                    self.assertTrue(all(line.endswith("-") for line in lines[:-1]), lines)
                    self.assertEqual("".join(lines), name)
                    evidence.append({"style": style, "name": name, "lines": lines})
            self.assertEqual(fonts, {"FreeSerif", "FreeSerifBold", "FreeSerifItalic", "FreeSerifBoldItalic"})
        core.save_json(root / "source-name-consumer-evidence.json", {"metrics_sp": metrics, "cases": evidence})
        self.save_remaining_overflow_pdf(root, root / "book.pdf")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for native FullLeft glue and glyph evidence")
    def test_remaining_generated_opener_preserves_native_glue_glyphs_and_line_ownership(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        formula = r"\mathrm{M}+\mathrm{N}"
        book["protected"] = [{"id": "Math", "kind": "math", "value": formula}]
        cases = [("Cjk", [{"text": "甲（"}], "甲（"),
                 ("Default", [{"text": "A（"}], "A（"),
                 ("Boundary", [{"text": "甲"}, {"page": "P1"}, {"text": "（"}],
                  r"甲\BTPosition{native-boundary}（")]
        # Record actual dispatch, not a callback-identity acceptance rule.
        # Generated seams may use native Boundary predecessor recovery. The
        # consumer invariant is the complete natural/stretch/shrink geometry.
        # Observe only after compatibility setup; delegation adds no nodes.
        body = [r"\def\BTTestCase{setup}\ExplSyntaxOn"]
        for path in ("CJK", "Boundary", "Default"):
            body.append(r"\cs_new_eq:cc {bt_test_" + path + r":N}{__xeCJK_" + path + r"_and_FullLeft_glue:N}")
            body.append(r"\cs_set_protected:cpn {__xeCJK_" + path + r"_and_FullLeft_glue:N} #1"
                        r"{\typeout{BTOPENERPATH|" + path + r"|\BTTestCase|"
                        r"\bool_if:NTF\g__bt_math_opener_armed_bool{armed}{idle}}"
                        r"\use:c{bt_test_" + path + r":N}#1}")
        body.extend([r"\ExplSyntaxOff\begin{document}\pagestyle{empty}",
                     r"\xeCJKsetup{CJKglue={\hskip3pt plus2pt minus1pt},CJKecglue={\hskip4pt plus3pt minus2pt}}"])
        for style, command in enumerate((r"\normalfont", r"\normalfont\bfseries",
                                         r"\normalfont\itshape", r"\normalfont\bfseries\itshape")):
            if style:
                body.append(r"\clearpage")
            body.append("{" + command)
            for label, prefix, native_prefix in cases:
                tokens = prefix + [{"protected": "Math"}, {"text": "）后"}]
                actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
                native = native_prefix + r"\(" + formula + r"\)）后"
                for mode, adjustment in (("U", None), ("S", "+2pt"), ("C", "-1pt")):
                    for suffix, tex in (("N", native), ("P", actual)):
                        key = label + mode + suffix
                        body.append(r"\def\BTTestCase{" + str(style) + key + "}")
                        body.append(r"\BTTestMetric{" + str(style) + key + "}{" + tex + "}")
                        target = "" if adjustment is None else r" to \dimexpr\wd0" + adjustment + r"\relax"
                        body.append(r"\setbox0=\hbox{" + native + "}")
                        body.append(r"\noindent\makebox[80pt][l]{" + key + r"}\hbox" + target +
                                    "{" + tex + r"}\par\vspace{5pt}")
            body.append("}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture(self.remaining_overflow_root("opener-native-glue"), body)
        self.assertNotIn("Missing character:", log)
        paths = re.findall(r"BTOPENERPATH\|([^|]+)\|([^|]+)\|(armed|idle)", log)

        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            for style, page in enumerate(document):
                for label, _, _ in cases:
                    for mode in ("U", "S", "C"):
                        key = label + mode
                        native = self.font_row_glyphs(page, key + "N")
                        actual = self.font_row_glyphs(page, key + "P")
                        self.assertEqual([(s, t["font"], c[1], t["size"]) for s, t, c in actual],
                                         [(s, t["font"], c[1], t["size"]) for s, t, c in native])
                        self.assertAlmostEqual(metrics[str(style) + key + "N"],
                                               metrics[str(style) + key + "P"], delta=2)
                        for (_, _, a), (_, _, n) in zip(actual, native):
                            self.assertAlmostEqual(a[2][0] - actual[0][2][2][0],
                                                   n[2][0] - native[0][2][2][0], delta=.02,
                                                   msg="Native natural, stretch and shrink glue must all survive")
                        self.assertEqual({t["font"] for s, t, _ in actual if s in "MN"}, {"LMRoman10-Regular"})
                        evidence.append({"style": style, "path": label, "mode": mode,
                                         "native_width_sp": metrics[str(style) + key + "N"],
                                         "actual_width_sp": metrics[str(style) + key + "P"]})
        core.save_json(root / "native-glue-consumer-evidence.json", {"paths": paths, "cases": evidence})
        self.save_remaining_overflow_pdf(root, root / "book.pdf")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for typed opener fallback evidence")
    def test_remaining_opener_fallback_keeps_math_contiguous_and_internal_breaks_native(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        atom = r"\mathrm{" + "M" * 16 + "}"
        internal = "+".join(r"\mathrm{M}" for _ in range(48))
        book["protected"] = [{"id": "Atom", "kind": "math", "value": atom},
                             {"id": "Sum", "kind": "math", "value": internal}]
        body = [r"\newdimen\BTOpenerMeasure\begin{document}\pagestyle{empty}"]
        for label, prefix in (("Cjk", [{"text": "甲" * 8 + "（"}]), ("Default", [{"text": "A" * 12 + "（"}]),
                              ("Boundary", [{"text": "甲" * 8}, {"page": "P1"}, {"text": "（"}])):
            actual = render._Renderer(self.job, book, {"terms": []}).inline(
                prefix + [{"text": ""}, {"page": "P2"}, {"protected": "Atom"}, {"text": "）"}])
            self.assertIn(r"\(" + atom + r"\)", actual, "The exact math value must remain one contiguous native run")
            body.append(r"\sbox{\BTTempBox}{（\(" + atom + r"\)）}\BTOpenerMeasure=\wd\BTTempBox")
            body.append(r"\noindent\makebox[70pt][l]{" + label +
                        r"}\begin{minipage}[t]{\dimexpr\BTOpenerMeasure+1pt\relax}\parindent=0pt\noindent " +
                        actual + r"\par\end{minipage}\par\vspace{20pt}")
        body.append(r"\clearpage")
        for label, tex in (("Native", "甲（" + r"\(" + internal + r"\)）后文。"),
                           ("Policy", render._Renderer(self.job, book, {"terms": []}).inline(
                               [{"text": "甲（"}, {"protected": "Sum"}, {"text": "）后文。"}]))):
            if label == "Policy":
                body.append(r"\clearpage")
                self.assertIn(r"\(" + internal + r"\)", tex)
            body.append(r"\BTParagraph{" + label + "}{" + tex + "}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture(self.remaining_overflow_root("opener-fallback"), body)
        self.assertNotIn("Missing character:", log)
        evidence = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 3)
            page = document[0]
            markers = [next(word for word in page.get_text("words") if word[4] == label)
                       for label in ("Cjk", "Default", "Boundary")]
            for index, marker in enumerate(markers):
                end = markers[index + 1][1] - 5 if index < 2 else page.rect.height
                glyphs = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"]
                          if c[2][0] > marker[2] + .5 and marker[1] <= c[2][1] < end and chr(c[0]).strip()]
                self.assertEqual("".join(s for s, _, _ in glyphs), ("A" * 12 if index == 1 else "甲" * 8) + "（" + "M" * 16 + "）")
                opener, = [c for s, _, c in glyphs if s == "（"]
                math = [(t, c) for s, t, c in glyphs if s == "M"]
                self.assertGreater(opener[2][1], glyphs[0][2][2][1] + 5,
                                   "The pre-opener fallback must actually move the intact opener/math run")
                self.assertTrue(all(abs(c[2][1] - opener[2][1]) < .02 for _, c in math))
                self.assertEqual({t["font"] for t, _ in math}, {"LMRoman10-Regular"})
                lines = ["".join(s for s, _, c in glyphs if abs(c[2][1] - y) < .05)
                         for y in sorted({round(c[2][1], 2) for _, _, c in glyphs})]
                self.assertTrue(all(not line.endswith("（") for line in lines), lines)
                evidence.append({"path": marker[4], "lines": lines})
            signatures = []
            for page in (document[1], document[2]):
                chars = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"] if chr(c[0]).strip()]
                math = [(t, c) for s, t, c in chars if s == "M"]
                self.assertEqual(len(math), 48)
                self.assertGreater(len({round(c[2][1], 2) for _, c in math}), 2)
                signatures.append([(s, t["font"], c[1], round(c[2][0] - chars[0][2][2][0], 2),
                                    round(c[2][1] - chars[0][2][2][1], 2)) for s, t, c in chars])
            self.assertEqual([entry[:3] for entry in signatures[0]], [entry[:3] for entry in signatures[1]])
            for native, actual in zip(*signatures):
                for axis in (3, 4):
                    self.assertAlmostEqual(native[axis], actual[axis], delta=.02,
                                           msg="Native internal math breaks and glyph positions must survive")
        core.save_json(root / "opener-fallback-evidence.json", {"cases": evidence, "internal_signatures": signatures})
        self.save_remaining_overflow_pdf(root, root / "book.pdf")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for unchanged negative opener consumers")
    def test_remaining_unsupported_opener_neighbors_are_native_and_cannot_leak_an_arm(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        formula = r"\mathrm{M}"
        book["protected"] = [{"id": "Math", "kind": "math", "value": formula},
                             {"id": "Close", "kind": "math", "value": r"\mathclose{\rbrace}"},
                             {"id": "Literal", "kind": "name", "value": "甲（"}]
        cases = [("Ascii", [{"text": "A("}, {"protected": "Math"}, {"text": ")后"}],
                  r"A(\(" + formula + r"\))后"),
                 ("Nbsp", [{"text": "A\u00a0（"}, {"protected": "Math"}, {"text": "）后"}],
                  "A\u00a0（" + r"\(" + formula + r"\)）后"),
                 ("Space", [{"text": "甲（ "}, {"protected": "Math"}, {"text": "）后"}],
                  "甲（ " + r"\(" + formula + r"\)）后"),
                 ("Unsafe", [{"text": "甲（"}, {"protected": "Close"}, {"text": "）后"}],
                  r"甲（\(\mathclose{\rbrace}\)）后"),
                 ("Literal", [{"protected": "Literal"}, {"protected": "Math"}, {"text": "）后"}],
                  r"甲（\(" + formula + r"\)）后")]
        body = [r"\def\BTTestCase{setup}\ExplSyntaxOn",
                r"\cs_new_eq:NN\bt_test_emit:\__bt_emit_armed_math_opener:",
                r"\cs_set_protected:Npn\__bt_emit_armed_math_opener:"
                r"{\bool_if:NT\g__bt_math_opener_armed_bool{\typeout{BTUNEXPECTEDARM|\BTTestCase}}\bt_test_emit:}",
                r"\ExplSyntaxOff\begin{document}\pagestyle{empty}"]
        for label, tokens, native in cases:
            actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
            for suffix, tex in (("N", native), ("P", actual)):
                key = label + suffix
                body.append(r"\def\BTTestCase{" + key + "}")
                body.append(r"\BTTestMetric{" + key + "}{" + tex + "}")
                body.append(r"\noindent\makebox[65pt][l]{" + key + r"}\hbox{" + tex + r"}\par\vspace{8pt}")
        # A real non-hooked class transition must consume no later ordinary
        # opener's opportunity, even when the typed arm was initially eligible.
        body.append(r'\xeCJKDeclareCharClass{Default}{"201C}')
        tokens = [{"text": "A“"}, {"protected": "Math"}, {"text": "”甲（后）"}]
        actual = render._Renderer(self.job, book, {"terms": []}).inline(tokens)
        native = r"A“\(" + formula + r"\)”甲（后）"
        for suffix, tex in (("N", native), ("P", actual)):
            key = "Bypass" + suffix
            body.append(r"\def\BTTestCase{" + key + "}")
            body.append(r"\BTTestMetric{" + key + "}{" + tex + "}")
            body.append(r"\noindent\makebox[65pt][l]{" + key + r"}\hbox{" + tex + r"}\par\vspace{8pt}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture(self.remaining_overflow_root("opener-negatives"), body)
        self.assertNotIn("BTUNEXPECTEDARM|", log, "An unsupported seam must never arm an unrelated native opener")
        self.assertNotIn("Missing character:", log)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 1)
            for label in [case[0] for case in cases] + ["Bypass"]:
                native = self.font_row_glyphs(document[0], label + "N")
                actual = self.font_row_glyphs(document[0], label + "P")
                self.assertEqual([(s, t["font"], c[1], t["size"]) for s, t, c in actual],
                                 [(s, t["font"], c[1], t["size"]) for s, t, c in native])
                self.assertAlmostEqual(metrics[label + "N"], metrics[label + "P"], delta=2)
                for (_, _, a), (_, _, n) in zip(actual, native):
                    self.assertAlmostEqual(a[2][0] - actual[0][2][2][0],
                                           n[2][0] - native[0][2][2][0], delta=.02)
        core.save_json(root / "unsupported-consumer-evidence.json", {"metrics_sp": metrics, "unexpected_arms": 0})
        self.save_remaining_overflow_pdf(root, root / "book.pdf")

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for actual missing native callback rejection")
    def test_remaining_missing_native_opener_callbacks_fail_closed_in_the_compiler(self):
        import os
        import subprocess
        for path in ("CJK", "Boundary", "Default"):
            with self.subTest(native_callback=path):
                root = self.remaining_overflow_root("missing-" + path)
                root.mkdir()
                shutil.copyfile(render.TEMPLATE.with_name("translator.sty"), root / "translator.sty")
                tex = (r"\documentclass[a5paper,twoside,openany,10pt,fontset=fandol]{ctexbook}" + "\n" +
                       r"\newcommand{\BTInner}{20}\newcommand{\BTOuter}{8}\newcommand{\BTTop}{15}"
                       r"\newcommand{\BTBottom}{15}\newcommand{\BTMarkEdge}{3}" + "\n" +
                       r"\ExplSyntaxOn\cs_undefine:c{__xeCJK_" + path + r"_and_FullLeft_glue:N}\ExplSyntaxOff" + "\n" +
                       r"\usepackage{translator}\begin{document}甲（\(M\)）\end{document}")
                (root / "book.tex").write_text(tex, encoding="utf-8")
                result = subprocess.run([shutil.which("xelatex"), "-no-shell-escape", "-halt-on-error",
                                         "-interaction=batchmode", "book.tex"], cwd=root,
                                        env={**os.environ, "SOURCE_DATE_EPOCH": "1609459200", "FORCE_SOURCE_DATE": "1"},
                                        capture_output=True, text=True, timeout=30)
                (root / "compiler.log").write_text(result.stdout + result.stderr, encoding="utf-8")
                log = (root / "book.log").read_text(encoding="utf-8")
                self.assertNotEqual(result.returncode, 0)
                diagnostic = re.sub(r"\s+", "", log.replace("(book-translator)", ""))
                self.assertIn("UnsupportedxeCJKopenercallback" + path + ".", diagnostic)
                self.assertNotIn("Undefined control sequence", log)
                self.assertFalse((root / "book.pdf").exists())
                core.save_json(root / "failclosed-consumer-evidence.json",
                               {"missing_callback": path, "compiler_returncode": result.returncode,
                                "pdf_emitted": False})

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for complete typed source-anchor evidence")
    def test_remaining_opener_source_anchors_and_all_three_classes_pass_real_build_without_state_mutation(self):
        import pymupdf
        atom = r"\mathrm{" + "M" * 32 + "}"
        content = [{"text": "甲（"}, {"page": "After"}, {"text": ""},
                   {"protected": "Math"}, {"text": "）后文。"}]
        blocks = [{"id": "Heading", "kind": "heading", "level": 2, "source_pages": ["InlineSource"],
                   "source": [{"text": "Native composition consumers"}], "target": [{"text": "Native composition consumers"}]},
                  {"id": "Opener", "kind": "paragraph", "source_pages": ["InlineSource", "After"],
                   "source": copy.deepcopy(content), "target": copy.deepcopy(content)},
                  {"id": "Slash", "kind": "paragraph", "source_pages": ["After"],
                   "source": [{"text": "输入输出说明。" * 12 + "MOSIS/MCNC 的普通复合词保持原样。"}],
                   "target": [{"text": "输入输出说明。" * 12 + "MOSIS/MCNC 的普通复合词保持原样。"}]},
                  {"id": "NameParagraph", "kind": "paragraph", "source_pages": ["After"],
                   "source": [{"protected": "Name"}, {"text": " 方法保持原始姓名拼写与连字符。"}],
                   "target": [{"protected": "Name"}, {"text": " 方法保持原始姓名拼写与连字符。"}]}]
        root = make_inline_job(self.remaining_overflow_root("real-build"))
        for filename in ("book-source.json", "book.json"):
            manuscript = core.load_json(root / filename)
            manuscript.update(blocks=copy.deepcopy(blocks), notes=[], main_body_start="Heading",
                              protected=[{"id": "Math", "kind": "math", "value": atom},
                                         {"id": "Name", "kind": "name", "value": "Kernighan-Lin"}])
            if filename == "book-source.json":
                manuscript["agent_preface"] = []
                for block in manuscript["blocks"]:
                    block["target"] = []
            manuscript["source_pages"].append({"id": "After", "locator": "inline-source.pdf:1",
                                               "printed_label": "S2", "label_verified": True,
                                               "evidence": "Synthetic boundary between ordinary opener and exact math."})
            core.save_json(root / filename, manuscript)
        core.seal_source(root)
        names = ("job.json", "book-source.json", "book.json", "terms.json")
        before = {name: (root / name).read_bytes() for name in names}
        pdf = render.build(root)
        self.assertEqual({name: (root / name).read_bytes() for name in names}, before)
        report = core.load_json(root / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertNotRegex((root / "build/book.log").read_text(encoding="utf-8"),
                            r"Overfull \\[hv]box|Underfull \\hbox|Missing character:")
        row, = [row for row in report["typography"] if row["id"] == "Opener"]
        mark, = [mark for mark in report["source_marks"] if mark["source_page"] == "After"]
        self.assertEqual(mark["page"], row["start"]["page"])
        with pymupdf.open(pdf) as document:
            page = document[mark["page"] - 1]
            glyphs = [(chr(c[0]), t, c) for t in page.get_texttrace() for c in t["chars"]
                      if chr(c[0]) == "M" and t["font"] == "LMRoman10-Regular"]
            self.assertEqual(len(glyphs), 32)
            self.assertEqual({t["font"] for _, t, _ in glyphs}, {"LMRoman10-Regular"})
            self.assertEqual(len({round(c[2][1], 2) for _, _, c in glyphs}), 1)
            baseline = glyphs[0][2][2][1]
            self.assertGreater(baseline, page.rect.height - row["start"]["y_from_bottom_pt"] + 5)
            self.assertAlmostEqual(page.rect.height - mark["y_from_bottom_pt"], baseline, delta=.1)
            opener, = [c for t in page.get_texttrace() for c in t["chars"]
                       if chr(c[0]) == "（" and abs(c[2][1] - baseline) < .1]
            self.assertLessEqual(opener[2][0], mark["x_pt"])
            self.assertLessEqual(mark["x_pt"], glyphs[0][2][2][0] + .1)
        core.save_json(root / "unchanged-input-evidence.json",
                       {name: hashlib.sha256(value).hexdigest() for name, value in before.items()})
        self.save_remaining_overflow_pdf(root, pdf)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for genuine indivisibility controls")
    def test_remaining_indivisible_literal_nbsp_name_constituent_and_opener_math_still_fail_overflow(self):
        import pymupdf
        half = "M" * 25
        controls = [("LiteralSlash", [{"protected": "Value"}], "name", half + "/" + half),
                    ("CodeSlash", [{"protected": "Value"}], "code", "M" * 40 + "/" + "M" * 40),
                    ("NbspSlash", [{"text": half + "/\u00a0" + half}], None, None),
                    ("NameConstituent", [{"protected": "Value"}], "name", "W" * 80 + "-Lin"),
                    ("OpenerMath", [{"text": "甲（"}, {"protected": "Value"}, {"text": "）"}],
                     "math", r"\mathrm{" + "W" * 80 + "}")]
        for label, content, kind, value in controls:
            with self.subTest(indivisible=label):
                blocks = [{"id": "Control", "kind": "paragraph", "source_pages": ["InlineSource"],
                           "source": copy.deepcopy(content), "target": copy.deepcopy(content)}]
                root = make_layout_regression_job(self.remaining_overflow_root(label), blocks,
                                                  protected=([{"id": "Value", "kind": kind, "value": value}]
                                                             if kind else []))
                with self.assertRaisesRegex(ValueError, "overfull output"):
                    render.build(root)
                report = core.load_json(root / "build/verification.json")
                self.assertFalse(report["checks"]["overflow"])
                self.assertRegex((root / "build/book.log").read_text(encoding="utf-8"), r"Overfull \\hbox")
                self.assertFalse((root / "output.pdf").exists())
                with pymupdf.open(root / "build/book.pdf") as document:
                    chars = [(chr(c[0]), t["font"], c) for page in document for t in page.get_texttrace()
                             for c in t["chars"] if chr(c[0]) == ("W" if label in ("NameConstituent", "OpenerMath") else "M")]
                    self.assertEqual(len(chars), 80 if label in ("CodeSlash", "NameConstituent", "OpenerMath") else 50)
                    self.assertGreater(max(c[3][2] for _, _, c in chars) - min(c[2][0] for _, _, c in chars),
                                       report["compiled_geometry_pt"]["text_width"])
                    for page in document:
                        page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(
                            root / ("rejected-actual-page-%02d.png" % (page.number + 1)))
                core.save_json(root / "indivisible-consumer-evidence.json",
                               {"case": label, "painted_pdf_glyphs": [(s, f, c[1], c[2], c[3]) for s, f, c in chars],
                                "overflow_gate_passed": report["checks"]["overflow"]})

    def compile_font_fixture(self, name, body):
        """Compile an isolated copy of the production style, retaining real PDF evidence."""
        import os
        import subprocess
        root = self.job / name
        root.mkdir()
        shutil.copyfile(render.TEMPLATE.with_name("translator.sty"), root / "translator.sty")
        preamble = render.TEMPLATE.read_text(encoding="utf-8").split(r"\begin{document}", 1)[0]
        for key, value in {"INNER": "20", "OUTER": "8", "TOP": "15", "BOTTOM": "15",
                           "MARK_EDGE": "3", "BEFORE_BODY": "Before body", "SOURCE_OVERLAYS": ""}.items():
            preamble = preamble.replace("@@" + key + "@@", value)
        measure = r"\newcommand\BTTestMetric[2]{\setbox0=\hbox{#2}\typeout{BTFONTMETRIC|#1|\number\wd0}}"
        (root / "book.tex").write_text(preamble + measure + "\n" + "\n".join(body), encoding="utf-8")
        result = subprocess.run([shutil.which("xelatex"), "-no-shell-escape", "-halt-on-error",
                                 "-interaction=batchmode", "book.tex"], cwd=root,
                                env={**os.environ, "SOURCE_DATE_EPOCH": "1609459200", "FORCE_SOURCE_DATE": "1"},
                                capture_output=True, text=True, timeout=30)
        log = (root / "book.log").read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        self.assertNotRegex(log, r"Overfull \\[hv]box|end occurred inside a group")
        return root, log

    def font_row_glyphs(self, page, label, *, scripts=False):
        import pymupdf
        word, = [word for word in page.get_text("words") if word[4] == label]
        bounds = pymupdf.Rect(word[:4])
        traces = page.get_texttrace()
        marker = next(char for trace in traces for char in trace["chars"]
                      if chr(char[0]) == label[0] and abs(char[2][0] - bounds.x0) < .1
                      and bounds.y0 <= char[2][1] <= bounds.y1)
        return [(chr(char[0]), trace, char) for trace in traces for char in trace["chars"]
                if char[2][0] > bounds.x1 + .5
                and -.1 <= char[2][1] - marker[2][1] <= (9 if scripts else .1)]

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for native prime and EM-space evidence")
    def test_compiled_prime_and_em_space_keep_styles_widths_and_native_cjk_glue(self):
        import pymupdf
        styles = (
            (r"\normalfont", "JuliaMono-Regular", "FandolSong-Regular"),
            (r"\normalfont\bfseries", "JuliaMono-Bold", "FandolSong-Bold"),
            (r"\normalfont\itshape", "JuliaMono-RegularItalic", "FandolKai-Regular"),
            (r"\normalfont\bfseries\itshape", "JuliaMono-BoldItalic", "FandolSong-Bold"),
        )
        rows = (
            ("Base", "ABCD", "ABCD"),
            ("Prime", "A′B", render.escape("A′B")),
            ("Em", "A\u2003B", render.escape("A\u2003B")),
            ("Repeat", "A\u2003\u2003B", render.escape("A\u2003\u2003B")),
            ("Plain", "A′B\u2003CμD", render.escape("A′B\u2003CμD")),
            ("Macro", "A′B\u2003CμD", r"A{\mbox{′}}B{" + "\u2003" + r"}C{\mbox{μ}}D"),
            ("CjkA", "\u524dx\u540e", render.escape("\u524dx\u540e")),
            ("CjkP", "\u524d′\u540e", render.escape("\u524d′\u540e")),
            ("CjkEm", "\u524d\u2003\u540e", render.escape("\u524d\u2003\u540e")),
            ("Emph", "AB′μCD", r"A\emph{B′μC}D"),
        )
        units = {"X": "x", "PrimeUnit": "′", "EmUnit": "\u2003", "RepeatUnit": "\u2003\u2003",
                 "Left": "\u524d", "Right": "\u540e", "OneEm": r"\hspace*{1em}"}
        body = [r"\begin{document}\pagestyle{empty}"]
        for index, (command, _, _) in enumerate(styles):
            if index:
                body.append(r"\clearpage")
            body.append("{" + command)
            for label, _, tex in rows:
                body.append(r"\BTTestMetric{" + str(index) + "-" + label + "}{" + tex + "}")
                body.append(r"\noindent\makebox[7em][l]{" + label + "}" + tex + r"\par")
            for label, tex in units.items():
                body.append(r"\BTTestMetric{" + str(index) + "-" + label + "}{" + tex + "}")
            # A locally changed native glue is a behavioral control, not a production override.
            body.append(r"\begingroup\xeCJKsetup{CJKecglue={\hskip6pt}}")
            for label, _, tex in rows[6:9]:
                body.append(r"\BTTestMetric{" + str(index) + "-Forced" + label + "}{" + tex + "}")
            body.append(r"\endgroup}")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture("prime-em-space", body)
        metrics = {key: int(value) for key, value in re.findall(r"BTFONTMETRIC\|([^|\s]+)\|(\d+)", log)}
        sp_to_pdf = 72 / 72.27 / 65536
        observed = []
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 4)
            for index, (page, (_, fallback, chinese)) in enumerate(zip(document, styles)):
                actual = {label: self.font_row_glyphs(page, label) for label, _, _ in rows}
                observed.append(actual)
                baseline = {symbol: (trace["font"], char[1]) for symbol, trace, char in actual["Base"]}
                roman = baseline["A"][0]
                for label, expected, _ in rows:
                    with self.subTest(style=index, row=label):
                        glyphs = actual[label]
                        # XeTeX/PDF extraction may encode Unicode spacing as U+0020 plus advance.
                        # Preserve the count here; prove its EM width independently below.
                        self.assertEqual("".join(symbol for symbol, _, _ in glyphs).replace("\u2003", " "),
                                         expected.replace("\u2003", " "))
                        for symbol, trace, char in glyphs:
                            self.assertEqual(trace["type"], 0, (label, symbol))
                            self.assertGreater(trace["opacity"], 0, (label, symbol))
                            self.assertGreater(char[1], 0, (label, symbol, "not .notdef"))
                            if label != "Emph":
                                expected_font = chinese if symbol in "\u524d\u540e" else fallback if symbol == "μ" else roman
                                self.assertEqual(trace["font"], expected_font, (label, symbol))
                                if symbol in baseline:
                                    self.assertEqual((trace["font"], char[1]), baseline[symbol], (label, symbol))
                            if not symbol.isspace():
                                ink = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(char[3]),
                                                      colorspace=pymupdf.csGRAY, alpha=False)
                                self.assertGreater(sum(value < 200 for value in ink.samples), 2, (label, symbol))
                        if label in ("Em", "Repeat"):
                            count = 1 if label == "Em" else 2
                            delta = glyphs[-1][2][2][0] - glyphs[0][2][2][0]
                            base_delta = actual["Base"][1][2][2][0] - actual["Base"][0][2][2][0]
                            self.assertAlmostEqual(delta - base_delta, count * metrics[f"{index}-OneEm"] * sp_to_pdf, delta=.02)
                        if label in ("CjkA", "CjkP", "CjkEm"):
                            delta = glyphs[-1][2][2][0] - glyphs[0][2][2][0]
                            self.assertAlmostEqual(delta, (metrics[f"{index}-{label}"] - metrics[f"{index}-Right"]) * sp_to_pdf, delta=.02)
                with self.subTest(style=index, measurement="semantic EM advance"):
                    self.assertEqual(metrics[f"{index}-EmUnit"], metrics[f"{index}-OneEm"])
                    self.assertEqual(metrics[f"{index}-RepeatUnit"], 2 * metrics[f"{index}-OneEm"])
                with self.subTest(style=index, measurement="native CJK glue"):
                    residuals = []
                    for label, unit in (("CjkA", "X"), ("CjkP", "PrimeUnit"), ("CjkEm", "EmUnit")):
                        component_width = sum(metrics[f"{index}-{part}"] for part in ("Left", unit, "Right"))
                        residuals.append(metrics[f"{index}-{label}"] - component_width)
                        self.assertAlmostEqual(metrics[f"{index}-Forced{label}"] - component_width, 12 * 65536, delta=2)
                    self.assertGreater(residuals[0], 0)
                    self.assertTrue(all(abs(value - residuals[0]) <= 2 for value in residuals), residuals)
                with self.subTest(style=index, measurement="macro bounds"):
                    # Independent shaping runs round at scaled-point precision.
                    self.assertAlmostEqual(metrics[f"{index}-Macro"], metrics[f"{index}-Plain"], delta=2)
                    plain = actual["Plain"]
                    macro = actual["Macro"]
                    self.assertEqual([(symbol, trace["font"], char[1]) for symbol, trace, char in macro],
                                     [(symbol, trace["font"], char[1]) for symbol, trace, char in plain])
                    for (_, _, left), (_, _, right) in zip(macro, plain):
                        self.assertAlmostEqual(left[2][0] - macro[0][2][2][0], right[2][0] - plain[0][2][2][0], delta=.02)
            self.assertEqual(len({rows["Base"][0][1]["font"] for rows in observed}), 4)
            for index, actual in enumerate(observed):
                with self.subTest(style=index, measurement="emphasis restoration"):
                    toggled = observed[index ^ 2]
                    base = {symbol: trace["font"] for symbol, trace, _ in actual["Base"]}
                    for symbol, trace, char in actual["Emph"]:
                        expected = base[symbol] if symbol in "AD" else styles[index ^ 2][1] if symbol == "μ" else toggled["Base"][0][1]["font"]
                        self.assertEqual(trace["font"], expected, symbol)
                        self.assertGreater(char[1], 0, symbol)
        self.assertNotIn("Missing character:", log)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for preserved math optical glyph evidence")
    def test_compiled_math_lm_aliases_preserve_optical_faces_and_scripts(self):
        import pymupdf
        samples = ((5, 5, 7, 5), (6, 6, 7, 6), (7, 7, 7, 7), (8, 8, 8, 8),
                   (9, 9, 9, 9), (10, 10, 10, 10), (12, 12, 12, 12), (17, 17, 12, 12))
        body = [r"\begin{document}\pagestyle{empty}"]
        for size, _, _, _ in samples:
            body.append(r"{\fontsize{" + str(size) + r"}{24}\selectfont\noindent\makebox[60pt][l]{\normalsize S" + str(size) +
                        r"}\(\mathrm{M}+\mathit{I}+\mathbf{B}+\mu\leq\mathcal{N}\)\par}")
        for alias in ("mathrm", "mathit", "mathbf"):
            command = "\\" + alias
            body.append(r"\noindent\makebox[60pt][l]{" + alias + r"}\(" + command +
                        "{M}_{" + command + "{I}_{" + command + r"{B}}}\)\par")
        body.append(r"\end{document}")
        root, log = self.compile_font_fixture("math-optical-faces", body)
        self.assertNotIn("Missing character:", log)
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), 1)
            page = document[0]
            for size, regular, italic, bold in samples:
                with self.subTest(size=size):
                    glyphs = self.font_row_glyphs(page, "S" + str(size))
                    self.assertEqual("".join(unicodedata.normalize("NFKC", symbol) for symbol, _, _ in glyphs), "M+I+B+μ≤N")
                    for symbol, trace, char in glyphs:
                        normalized = unicodedata.normalize("NFKC", symbol)
                        expected = {"M": f"LMRoman{regular}-Regular", "I": f"LMRoman{italic}-Italic",
                                    "B": f"LMRoman{bold}-Bold"}.get(normalized, "LatinModernMath-Regular")
                        self.assertEqual(trace["font"], expected, (size, symbol))
                        self.assertGreater(char[1], 0, (size, symbol))
                        self.assertGreater(trace["opacity"], 0, (size, symbol))
                        ink = page.get_pixmap(matrix=pymupdf.Matrix(5, 5), clip=pymupdf.Rect(char[3]),
                                              colorspace=pymupdf.csGRAY, alpha=False)
                        self.assertGreater(sum(value < 200 for value in ink.samples), 2, (size, symbol))
            for alias, opticals, face in (("mathrm", (10, 7, 5), "Regular"),
                                          ("mathit", (10, 7, 7), "Italic"),
                                          ("mathbf", (10, 7, 5), "Bold")):
                with self.subTest(alias=alias, context="scripts"):
                    glyphs = self.font_row_glyphs(page, alias, scripts=True)
                    self.assertEqual("".join(unicodedata.normalize("NFKC", symbol) for symbol, _, _ in glyphs), "MIB")
                    self.assertEqual([trace["font"] for _, trace, _ in glyphs], [f"LMRoman{optical}-{face}" for optical in opticals])
                    self.assertTrue(all(char[1] > 0 for _, _, char in glyphs))
                    self.assertGreater(glyphs[1][2][2][1], glyphs[0][2][2][1])
                    self.assertGreater(glyphs[2][2][2][1], glyphs[1][2][2][1])


    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for ordinary TEXT glyph evidence")
    def test_compiled_body_text_glyphs_keep_styles_and_restore_surrounding_fonts(self):
        import os
        import subprocess
        import pymupdf
        root = self.job / "body-text-glyphs"
        root.mkdir()
        shutil.copyfile(render.TEMPLATE.with_name("translator.sty"), root / "translator.sty")
        preamble = render.TEMPLATE.read_text(encoding="utf-8").split(r"\begin{document}", 1)[0]
        for key, value in {"INNER": "20", "OUTER": "8", "TOP": "15", "BOTTOM": "15",
                           "MARK_EDGE": "3", "BEFORE_BODY": "Before body", "SOURCE_OVERLAYS": ""}.items():
            preamble = preamble.replace("@@" + key + "@@", value)
        # The 33 distinct ordinary-TEXT omissions observed in the admitted corpus.
        # Keep the characters here, not a dependency on the diagnostic job.
        corpus = "μᵐᵢ₀₁₂₃₄₅₆₇₈₉₋₌ₖₘₙₚℛ∅∈∑∩∪≤⌈⌉⌊⌋ⱼ𝒩𝒬"
        names = "kᵢⱼ Bᵢ/Bⱼ Rᵢ; μ/𝒩/𝒬/ℛ."
        cjk = "\u524d\u4e2d\u540e\uff0c\u3002"
        styles = (
            (r"\normalfont", "JuliaMono-Regular", "FandolSong-Regular"),
            (r"\normalfont\bfseries", "JuliaMono-Bold", "FandolSong-Bold"),
            (r"\normalfont\itshape", "JuliaMono-RegularItalic", "FandolKai-Regular"),
            (r"\normalfont\bfseries\itshape", "JuliaMono-BoldItalic", "FandolSong-Bold"),
        )
        rows = (
            ("Base", "AZ", "AZ"),
            ("FB", "AB CDE", r"\textsf{AB}\ \texttt{CD}E"),
            ("Corpus", "A" + corpus + "Z", render.escape("A" + corpus + "Z")),
            ("Names", names, render.escape(names)),
            ("CJK", "A\u524dμ\u4e2d𝒩\u540eⱼ\uff0cℛ\u3002Z", render.escape("A\u524dμ\u4e2d𝒩\u540eⱼ\uff0cℛ\u3002Z")),
            ("Edges", "AμBᵢC𝒩D", r"A{\mbox{μ}}B{ᵢ}C\textnormal{𝒩}D"),
            ("Families", "AμB C𝒬DE", r"\textsf{AμB}\ \texttt{C𝒬D}E"),
        )
        body = [r"\begin{document}\BTMainBody"]
        for index, (command, _, _) in enumerate(styles):
            if index:
                body.append(r"\clearpage")
            body.append("{" + command)
            for label, _, tex in rows:
                body.append(r"\noindent\makebox[5em][l]{" + label + "}" + tex + r"\par")
            body.append("}")
            if index == 0:
                # This separate control is math; none of the corpus rows is.
                body.append(r"\noindent\makebox[5em][l]{Math}A\(\mu\leq\mathcal{N}+\mathrm{M}+\mathit{I}+\mathbf{B}\)Z\par")
        body.append(r"\end{document}")
        (root / "book.tex").write_text(preamble + "\n".join(body), encoding="utf-8")
        result = subprocess.run([shutil.which("xelatex"), "-no-shell-escape", "-halt-on-error",
                                 "-interaction=batchmode", "book.tex"], cwd=root,
                                env={**os.environ, "SOURCE_DATE_EPOCH": "1609459200", "FORCE_SOURCE_DATE": "1"},
                                capture_output=True, text=True, timeout=30)
        log = (root / "book.log").read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        self.assertNotIn("Missing character:", log)
        self.assertNotRegex(log, r"Overfull \\[hv]box|end occurred inside a group")
        with pymupdf.open(root / "book.pdf") as document:
            self.assertEqual(len(document), len(styles))
            roman_fonts = []
            for page, (_, fallback, chinese) in zip(document, styles):
                traces = page.get_texttrace()
                extracted = page.get_text()
                baseline_fonts = {}
                for label, expected, _ in rows:
                    with self.subTest(style=fallback, boundary=label):
                        self.assertIn("".join(expected.split()), "".join(extracted.split()))
                        bounds, = page.search_for(label)
                        label_glyph = next(char for trace in traces for char in trace["chars"]
                                           if chr(char[0]) == label[0] and
                                           abs(char[2][0] - bounds.x0) < .1 and
                                           bounds.y0 <= char[2][1] <= bounds.y1)
                        glyphs = [(chr(char[0]), trace, char) for trace in traces for char in trace["chars"]
                                  if char[2][0] > bounds.x1 + .5 and
                                  abs(char[2][1] - label_glyph[2][1]) < .1 and not chr(char[0]).isspace()]
                        self.assertEqual("".join(symbol for symbol, _, _ in glyphs), "".join(expected.split()))
                        if label == "Base":
                            roman = glyphs[0][1]["font"]
                            roman_fonts.append(roman)
                            self.assertTrue(all(trace["font"] == roman for _, trace, _ in glyphs))
                        elif label == "FB":
                            baseline_fonts = {symbol: trace["font"] for symbol, trace, _ in glyphs}
                        if label == "Names":
                            # PDF extractors can omit spaces after encoded subscripts;
                            # require the actual word gaps as well as exact nonspace codepoints.
                            offset = 0
                            for symbol in expected:
                                if symbol.isspace():
                                    previous = glyphs[offset - 1][2]
                                    following = glyphs[offset][2]
                                    self.assertGreater(following[2][0] - previous[3][2], .5,
                                                       "An ordinary TEXT word space must retain visible advance")
                                else:
                                    offset += 1
                        if label == "Families":
                            fonts = [trace["font"] for _, trace, _ in glyphs]
                            self.assertEqual(fonts[0], baseline_fonts["A"], fonts)
                            self.assertEqual(fonts[0], fonts[2], "Sans family must survive TEXT fallback")
                            self.assertEqual(fonts[3], baseline_fonts["C"], fonts)
                            self.assertEqual(fonts[3], fonts[5], "Mono family must survive TEXT fallback")
                        for position, (symbol, trace, char) in enumerate(glyphs):
                            expected_font = chinese if symbol in cjk else fallback if symbol in corpus else roman
                            if label == "Edges" and symbol == "𝒩":
                                expected_font = "JuliaMono-Regular"
                            if label == "FB":
                                expected_font = baseline_fonts[symbol]
                            if label != "Families" or position in (1, 4, 6):
                                self.assertEqual(trace["font"], expected_font, (label, symbol))
                            self.assertEqual(trace["type"], 0, symbol)
                            self.assertGreater(trace["opacity"], 0, symbol)
                            self.assertGreater(char[1], 0, symbol + " must have a real glyph, not .notdef")
                            ink = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(char[3]),
                                                  colorspace=pymupdf.csGRAY, alpha=False)
                            self.assertGreater(sum(value < 200 for value in ink.samples), 2,
                                               symbol + " must have visible ink in its PDF glyph bounds")
            page = document[0]
            bounds, = page.search_for("Math")
            math_glyphs = [(unicodedata.normalize("NFKC", chr(char[0])), trace["font"], char[1])
                           for trace in page.get_texttrace() for char in trace["chars"]
                           if char[2][0] > bounds.x1 + .5 and bounds.y0 <= char[2][1] <= bounds.y1
                           and not chr(char[0]).isspace()]
            self.assertEqual("".join(symbol for symbol, _, _ in math_glyphs), "Aμ≤N+M+I+BZ")
            for symbol, font, glyph in math_glyphs:
                expected_font = {"A": roman_fonts[0], "Z": roman_fonts[0],
                                 "M": "LMRoman10-Regular", "I": "LMRoman10-Italic", "B": "LMRoman10-Bold"}.get(
                                     symbol, "LatinModernMath-Regular")
                self.assertEqual(font, expected_font, symbol)
                self.assertGreater(glyph, 0, symbol)

    @unittest.skipUnless(shutil.which("xelatex"), "XeLaTeX is required for Unicode math glyph evidence")
    def test_compiled_unicode_and_escaped_math_preserve_visible_glyphs(self):
        import pymupdf
        book = core.load_json(self.job / "book.json")
        expressions = {
            "Unicode": ("α ≤ β, x′", r"\begin{aligned} α &≤ β \\ x′ &≤ α + β \end{aligned}"),
            "Escaped": (r"\alpha \leq \beta, x^{\prime}",
                        r"\begin{aligned} \alpha &\leq \beta \\ x^{\prime} &\leq \alpha + \beta \end{aligned}"),
        }
        scenarios = []
        blocks = [copy.deepcopy(book["blocks"][0])]
        protected = []
        for context in ("Inline", "Display", "Aligned"):
            for spelling, values in expressions.items():
                identifier = context + spelling
                formula = identifier + "Formula"
                protected.append({"id": formula, "kind": "math",
                                  "value": values[1 if context == "Aligned" else 0]})
                content = [{"text": identifier + " "}]
                if context == "Inline":
                    content.append({"protected": formula})
                block = {"id": identifier, "kind": "paragraph" if context == "Inline" else "display_math",
                         "source_pages": ["P1"], "source": content, "target": copy.deepcopy(content)}
                if context != "Inline":
                    block["protected_id"] = formula
                blocks.append(block)
                scenarios.append((identifier, context, spelling))
        book.update(protected=protected, blocks=blocks, notes=[],
                    source_pages=book["source_pages"][:1], human_preface=None)
        source = copy.deepcopy(book)
        source["agent_preface"] = []
        for block in source["blocks"]:
            block["target"] = []
        core.save_json(self.job / "book-source.json", source)
        core.save_json(self.job / "book.json", book)
        core.save_json(self.job / "terms.json", {"version": 1, "terms": []})
        core.seal_source(self.job)

        pdf = render.build(self.job)
        report = core.load_json(self.job / "build/verification.json")
        self.assertTrue(report["passed"], report["errors"])
        self.assertTrue(report["checks"]["compiler"])
        for name in ("book.log", "compiler.log"):
            self.assertNotIn("Missing character:", (self.job / "build" / name).read_text(encoding="utf-8"))
        boundaries = {row["id"]: row for row in report["block_boundaries"]}
        normalize = lambda value: unicodedata.normalize("NFKC", value)
        with pymupdf.open(pdf) as document:
            extracted = "".join(normalize(page.get_text()) for page in document)
            extracted = "".join(extracted.split())
            outlines = {}
            for index, (identifier, context, spelling) in enumerate(scenarios):
                with self.subTest(context=context, spelling=spelling):
                    expected = "α≤βx′≤α+β" if context == "Aligned" else "α≤β,x′"
                    self.assertIn(identifier + expected, extracted)
                    boundary = boundaries[identifier]
                    self.assertEqual(boundary["start"]["page"], boundary["end"]["page"])
                    page = document[boundary["start"]["page"] - 1]
                    label, = page.search_for(identifier)
                    bottom = page.rect.height
                    if index + 1 < len(scenarios):
                        following = scenarios[index + 1][0]
                        if boundaries[following]["start"]["page"] == boundary["start"]["page"]:
                            next_label, = page.search_for(following)
                            bottom = next_label.y0
                    glyphs = [(normalize(chr(char[0])), trace, char)
                              for trace in page.get_texttrace() for char in trace["chars"]
                              if label.y0 <= char[2][1] < bottom
                              and normalize(chr(char[0])) in "≤′αβ"]
                    self.assertEqual("".join(symbol for symbol, _, _ in glyphs),
                                     "".join(symbol for symbol in expected if symbol in "≤′αβ"))
                    outlines[context, spelling] = [(symbol, trace["font"], char[1])
                                                   for symbol, trace, char in glyphs]
                    for symbol, trace, char in glyphs:
                        self.assertEqual(trace["type"], 0, symbol)
                        self.assertGreater(trace["opacity"], 0, symbol)
                        self.assertGreater(char[1], 0, symbol + " must not use the missing-glyph outline")
                        ink = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(char[3]),
                                              colorspace=pymupdf.csGRAY, alpha=False)
                        self.assertGreater(sum(value < 200 for value in ink.samples), 2,
                                           symbol + " must have actual visible ink in its PDF glyph bounds")
            for context in ("Inline", "Display", "Aligned"):
                self.assertEqual(outlines[context, "Unicode"], outlines[context, "Escaped"],
                                 context + " literal and escaped symbols must use identical glyph outlines")


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
