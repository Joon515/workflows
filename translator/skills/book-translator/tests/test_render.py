"""Real compiler and PDF layout tests; fixtures never claim model approval."""
from __future__ import annotations

import copy
import hashlib
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
          relation="row", images=group_images, canvas_width=220, canvas_height=110, text_fraction=.5)
    block("SideGroup", "group", ["P3"], [{"text": "Source side text."}],
          [{"text": "Side text stays beside the entire source canvas. " * 4}],
          relation="text-left", images=copy.deepcopy(group_images), canvas_width=220, canvas_height=110, text_fraction=.5)
    block("TallImage", "image", ["P3"], [{"text": "Source tall image."}, {"note": "TallNote"}],
          [{"text": "The tall source image is scaled, never cropped or split."}, {"note": "TallNote"}], asset="tall.png", width=100, height=900)
    notes = [{"id": "LongNote", "source": [{"text": "A long source note. " * 100}],
              "target": [{"term": "Footer"}, {"text": ". " + "The long note continues in the following bottom footer without truncation. " * 100 + " FOOTNOTE-END"}]},
             {"id": "CaptionNote", "source": [{"text": "Caption note."}],
              "target": [{"text": "A caption note belongs at the real page bottom, not inside the image canvas."}]},
             {"id": "TallNote", "source": [{"text": "Tall source image note."}],
              "target": [{"text": "The oversized image leaves room for this bottom footer."}]}]
    book = {"version": 1, "title": "Synthetic layout evidence", "source_pages": [
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


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-render-test-")
        self.job = make_job(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

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
            appendix = document[-1]
            for term in ("Method", "Footer"):
                row = "Fourier" if term == "Method" else "footer"
                words = appendix.get_text("words")
                target = next(word for word in words if word[4] == row)
                self.assertTrue(any(word[4] == str(report["term_first_pages"][term]) and word[0] > appendix.rect.width - 30 * render.PT_PER_MM and abs(word[1] - target[1]) < 1 for word in words))
        self.assertFalse((self.job / "output.pdf").exists())
        literal = self.job / "build/assets/code-CodeBlock.txt"
        self.assertEqual(literal.read_bytes(), core.load_json(self.job / "book.json")["protected"][2]["value"].encode())

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


if __name__ == "__main__":
    unittest.main()
