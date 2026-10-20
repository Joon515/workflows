"""Consumer-facing contract tests using isolated, real file and image fixtures."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "job"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "evidence").mkdir()
        (self.root / "evidence/source.pdf").write_bytes(b"Original source evidence\n")
        Image.new("RGB", (40, 20), "red").save(self.root / "assets/wide.png")
        Image.new("RGB", (20, 40), "blue").save(self.root / "assets/tall.png")
        (self.root / "assets/unused.txt").write_text("Retained extraction evidence", encoding="utf-8")
        self.job = {
            "version": 1, "title": "Source book", "source_language": "en", "target_language": "ko",
            "source_file": "evidence/source.pdf",
            "source_sha256": hashlib.sha256((self.root / "evidence/source.pdf").read_bytes()).hexdigest(),
            "max_rounds": 3, "round": 0, "state": "source_ready",
            "models": {"terminology": {"provider": "anthropic", "model": "claude-sonnet-4-6"}, "translation": {"provider": "google", "model": "gemini-2.5-pro"}},
            "layout": {"paper": "a5", "outer_mm": 8, "inner_min_mm": 20, "top_mm": 15, "bottom_mm": 15, "source_mark_edge_mm": 3},
            "history": [],
        }
        self.source = {
            "version": 2, "title": "Source book", "main_body_start": "heading",
            "source_pages": [
                {"id": "p1", "locator": "extraction:p0001", "printed_label": "iv", "label_verified": True, "evidence": "Original page image evidence/pages/p0001.png"},
                {"id": "p2", "locator": "extraction:p0002", "printed_label": None, "label_verified": False, "evidence": "Original unnumbered page image"},
            ],
            "protected": [
                {"id": "person", "kind": "name", "value": "Euler"},
                {"id": "variable", "kind": "variable", "value": "x_{1}"},
                {"id": "formula", "kind": "math", "value": r"E = \frac{m c^2}{2}"},
                {"id": "program", "kind": "code", "value": "# English comment\nvalue = 1\n\tprint(value)\n"},
            ],
            "blocks": [
                {"id": "heading", "kind": "heading", "level": 1, "source_pages": ["p1"], "source": [{"page": "p1"}, {"text": "Chapter"}], "target": []},
                {"id": "paragraph", "kind": "paragraph", "source_pages": ["p1"], "source": [{"text": "A method by "}, {"protected": "person"}, {"text": " uses "}, {"protected": "variable"}, {"note": "n1"}, {"protected": "variable"}], "target": []},
                {"id": "equation", "kind": "display_math", "source_pages": ["p1"], "source": [], "target": [], "protected_id": "formula"},
                {"id": "listing", "kind": "code", "source_pages": ["p1"], "source": [], "target": [], "protected_id": "program"},
                {"id": "figure", "kind": "image", "source_pages": ["p2"], "source": [{"page": "p2"}, {"text": "A wide image"}], "target": [], "asset": "assets/wide.png", "width": 40, "height": 20, "source_em": 5, "scale_evidence": "Synthetic source text em is 5 px in the image coordinate system."},
                {"id": "related", "kind": "group", "source_pages": ["p2"], "source": [{"text": "Related panels"}], "target": [], "relation": "text-left", "images": [{"asset": "assets/wide.png", "x": 0, "y": 10, "width": 40, "height": 20}, {"asset": "assets/tall.png", "x": 50, "y": 0, "width": 20, "height": 40}], "canvas_width": 70, "canvas_height": 40, "text_fraction": 0.4, "source_em": 5, "scale_evidence": "Synthetic source text em is 5 px in the shared canvas coordinate system."},
            ],
            "notes": [{"id": "n1", "content_type": "prose", "source": [{"text": "A small value "}, {"protected": "variable"}], "target": []}],
            "agent_preface": [], "human_preface": None,
        }
        self.terms = {"version": 1, "terms": [
            {"id": "euler", "number": 1, "source": "Euler", "target": "Euler method", "authority": "Field consensus", "authority_locator": "Reviewed field bibliography section 1", "rationale": "Keep the original personal name", "protected_ids": ["person"]},
            {"id": "small", "number": 2, "source": "small", "target": "small", "authority": "Domain standard", "authority_locator": "Section 2", "rationale": "Established usage", "protected_ids": []},
        ]}
        self.book = copy.deepcopy(self.source)
        self.book["title"] = "Translated book"
        for block in self.book["blocks"]:
            block["target"] = copy.deepcopy(block["source"])
        self.book["blocks"][1]["target"] = [{"text": "Method: "}, {"term": "euler"}, {"protected": "variable"}, {"note": "n1"}, {"protected": "variable"}]
        self.book["notes"][0]["target"] = [{"text": "Translated "}, {"term": "small"}, {"text": " value "}, {"protected": "variable"}]
        self.book["agent_preface"] = [{"text": "Machine translation. Terminology and source limitations were reviewed; review status is pending."}]
        self.write("job.json", self.job)
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.write("terms.json", self.terms)
        self.write("book.json", self.book)

    def write(self, name, value):
        core.save_json(self.root / name, value)

    def assert_bad_book(self, change, pattern=None):
        book = copy.deepcopy(self.book)
        change(book)
        self.write("book.json", book)
        if pattern:
            with self.assertRaisesRegex(ValueError, pattern):
                core.validate_book(self.root)
        else:
            with self.assertRaises(ValueError):
                core.validate_book(self.root)

    def assert_bad_source(self, change, pattern=None):
        source = copy.deepcopy(self.source)
        change(source)
        self.write("book-source.json", source)
        if pattern:
            with self.assertRaisesRegex(ValueError, pattern):
                core.seal_source(self.root)
        else:
            with self.assertRaises(ValueError):
                core.seal_source(self.root)

    def install_inline_images(self):
        for name in ("wide", "tall"):
            shutil.copyfile(self.root / f"assets/{name}.png", self.root / f"inline-{name}.png")
        images = [{"image": {"asset": "inline-wide.png", "width_em": 2, "height_em": 1, "raise_em": -.2}},
                  {"image": {"asset": "inline-tall.png", "width_em": .5, "height_em": 1, "raise_em": .1}}]
        for manuscript in (self.source, self.book):
            manuscript["blocks"][1]["source"][1:1] = copy.deepcopy(images + images[:1])
            manuscript["notes"][0]["source"][1:1] = copy.deepcopy(images)
        self.book["blocks"][1]["target"][1:1] = copy.deepcopy(images + images[:1])
        self.book["notes"][0]["target"][1:1] = copy.deepcopy(images)
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.write("book.json", self.book)
        return images

    def test_inline_image_tokens_conserve_values_order_and_multiplicity_in_body_and_notes(self):
        self.install_inline_images()
        self.assertEqual(core.validate_book(self.root), self.book)
        for category, index in (("blocks", 1), ("notes", 0)):
            changes = [lambda tokens: tokens.pop(1),
                       lambda tokens: tokens.insert(1, copy.deepcopy(tokens[1])),
                       lambda tokens: tokens.__setitem__(slice(1, 3), list(reversed(tokens[1:3])))]
            for field, value in (("asset", "inline-tall.png"), ("width_em", 3), ("height_em", 2), ("raise_em", .3)):
                changes.append(lambda tokens, field=field, value=value: tokens[1]["image"].update({field: value}))
            for change in changes:
                with self.subTest(category=category, change=change):
                    self.assert_bad_book(lambda book: change(book[category][index]["target"]), "preserve.*image")

    def test_inline_images_count_as_real_source_content(self):
        images = self.install_inline_images()
        self.source["blocks"][0]["source"] = images
        self.source["notes"][0].update(source=images, content_type="literal", literal_reason="Synthetic non-prose diagram fragments; no ordinary prose is present.")
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)

    def test_inline_image_schema_requires_exact_finite_numeric_geometry(self):
        valid = {"asset": "assets/wide.png", "width_em": 2, "height_em": 1, "raise_em": -.25}
        invalid = [dict(valid, **{field: value}) for field in ("width_em", "height_em") for value in (0, -1, True, "1", None)]
        invalid += [dict(valid, raise_em=value) for value in (True, "0", None, float("inf"), float("nan"))]
        invalid += [{key: value for key, value in valid.items() if key != field} for field in valid]
        invalid += [dict(valid, tex=r"\input{secret}"), dict(valid, asset="")]
        for image in invalid:
            book = copy.deepcopy(self.source)
            book["blocks"][0]["source"].append({"image": image})
            with self.subTest(image=image), self.assertRaises(ValueError):
                core.validate_document("book", book)

    def test_inline_images_are_not_new_preface_evidence(self):
        image = self.install_inline_images()[0]
        for field in ("agent_preface", "human_preface"):
            self.assert_bad_book(lambda book: book.update({field: [image]}), "prefaces permit")
            self.assert_bad_source(lambda book: book.update({field: [image]}), "prefaces permit")

    def test_inline_assets_reuse_containment_raster_and_aspect_checks(self):
        image = self.install_inline_images()[0]
        for asset, pattern in (("missing.png", "missing file"), ("assets/unused.txt", "readable raster"),
                               ("../outside.png", "path"), ("/tmp/outside.png", "path")):
            token = copy.deepcopy(image)
            token["image"]["asset"] = asset
            self.assert_bad_source(lambda book: book["notes"][0]["source"].append(token), r"notes.n1.source\[.*" + pattern)
        self.assert_bad_source(lambda book: book["blocks"][1]["source"][1]["image"].update(width_em=3), "aspect ratio")
        outside = Path(self.temporary.name) / "outside.png"
        shutil.copyfile(self.root / "inline-wide.png", outside)
        (self.root / "inline-outside.png").symlink_to(outside)
        self.assert_bad_source(lambda book: book["blocks"][1]["source"][1]["image"].update(asset="inline-outside.png"), "escapes")
        (self.root / "build").mkdir()
        shutil.copyfile(self.root / "inline-wide.png", self.root / "build/generated.png")
        (self.root / "inline-generated.png").symlink_to(self.root / "build/generated.png")
        (self.root / "build/reviewed-link.png").symlink_to(self.root / "inline-wide.png")
        for asset in ("build/generated.png", "inline-generated.png", "build/reviewed-link.png"):
            self.assert_bad_source(lambda book: book["blocks"][1]["source"][1]["image"].update(asset=asset), "Generated artifacts")

    def test_inline_asset_bytes_bind_source_seal_and_content_digest(self):
        self.install_inline_images()
        before = core.content_digest(self.root)
        Image.new("RGB", (40, 20), "green").save(self.root / "inline-wide.png")
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root)
        core.seal_source(self.root)
        self.assertNotEqual(core.content_digest(self.root), before)
        (self.root / "inline-tall.png").unlink()
        with self.assertRaisesRegex(ValueError, r"blocks.paragraph.source\[2\].*missing file"):
            core.validate_book(self.root)


    def publish_manuscripts(self):
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.write("terms.json", self.terms)
        self.write("book.json", self.book)

    def test_v2_requires_explicit_existing_nonblank_main_body_start(self):
        for value in (None, "", "missing", 1):
            with self.subTest(value=value):
                self.assert_bad_source(lambda book: book.update(main_body_start=value))
        self.assert_bad_source(lambda book: book.pop("main_body_start"), "main_body_start")
        self.assert_bad_source(lambda book: book.update(version=1), "2")
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book.update(main_body_start="paragraph"), "immutable")
        # A paragraph is a valid explicit boundary: heading wording is not an input.
        self.source["main_body_start"] = self.book["main_body_start"] = "paragraph"
        self.publish_manuscripts()
        self.assertEqual(core.validate_book(self.root)["main_body_start"], "paragraph")

    def install_blank_page(self):
        page = {"id": "p3", "locator": "synthetic:3", "printed_label": None,
                "label_verified": False, "evidence": "Original synthetic page has no printed content."}
        block = {"id": "blank3", "kind": "blank", "source_pages": ["p3"],
                 "source": [{"page": "p3"}], "target": [],
                 "blank_evidence": "Inspected the complete synthetic source page; no body text, figures or notes are present."}
        self.source["source_pages"].append(page)
        self.source["blocks"].append(block)
        self.book["source_pages"].append(copy.deepcopy(page))
        self.book["blocks"].append(dict(copy.deepcopy(block), target=[{"page": "p3"}]))
        self.publish_manuscripts()

    def test_blank_pages_retain_source_coverage_without_fabricated_prose(self):
        self.install_blank_page()
        self.assertEqual(core.validate_book(self.root)["blocks"][-1]["target"], [{"page": "p3"}])
        self.assert_bad_source(lambda book: book["blocks"].pop(), "coverage")
        self.assert_bad_source(lambda book: book.update(main_body_start="blank3"), "nonblank")
        self.assert_bad_source(lambda book: book["blocks"][-1].pop("blank_evidence"))
        self.assert_bad_source(lambda book: book["blocks"][-1].update(blank_evidence=" \n"))
        self.assert_bad_source(lambda book: book["blocks"][-1].update(source=[{"text": "Intentionally blank"}]))
        self.assert_bad_source(lambda book: book["blocks"][-1].update(source_pages=["p2", "p3"]))
        self.assert_bad_source(lambda book: book["blocks"][-1].update(source=[{"page": "p2"}]), "one source-page")
        self.assert_bad_source(lambda book: book["blocks"].append(dict(book["blocks"][-1], id="duplicateBlank")), "duplicate block coverage")
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book["blocks"].pop(), "immutable")
        self.assert_bad_book(lambda book: book["blocks"][-1].update(target=[]), "one source-page")
        self.assert_bad_book(lambda book: book["blocks"][-1].update(target=[{"page": "p3"}, {"text": "Blank"}]))

    def test_list_metadata_preserves_literal_marker_depth_and_content(self):
        for book in (self.source, self.book):
            book["blocks"][1].update(kind="list_item", list_type="ordered", list_level=2, label="(iv)")
        self.publish_manuscripts()
        self.assertEqual(core.validate_book(self.root)["blocks"][1]["label"], "(iv)")
        for field in ("list_type", "list_level", "label"):
            with self.subTest(field=field):
                self.assert_bad_source(lambda book: book["blocks"][1].pop(field))
        for field, values in (("list_type", ["number", "", None]),
                              ("list_level", [-1, 9, 1.5, 1.0, True, None]),
                              ("label", ["", " \n", None])):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_bad_source(lambda book: book["blocks"][1].update({field: value}))
        self.assert_bad_source(lambda book: book["blocks"][1]["source"].insert(0, {"text": "(iv) "}), "duplicated")
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book["blocks"][1].update(list_level=3), "immutable")
        self.assert_bad_book(lambda book: book["blocks"][1]["target"].insert(0, {"text": "(iv) "}), "duplicated")
        for book in (self.source, self.book):
            book["blocks"][1].update(list_type="unordered", list_level=8, label="\u2022")
        self.publish_manuscripts()
        self.assertEqual(core.validate_book(self.root)["blocks"][1]["list_level"], 8)

    def test_source_font_calibration_is_required_positive_finite_and_immutable(self):
        for index in (4, 5):
            for field in ("source_em", "scale_evidence"):
                with self.subTest(index=index, field=field):
                    self.assert_bad_source(lambda book: book["blocks"][index].pop(field))
            for value in (0, -1, True, "5", None):
                with self.subTest(index=index, value=value):
                    self.assert_bad_source(lambda book: book["blocks"][index].update(source_em=value))
            for value in (float("nan"), float("inf")):
                book = copy.deepcopy(self.source)
                book["blocks"][index]["source_em"] = value
                with self.subTest(index=index, value=value), self.assertRaisesRegex(ValueError, "non-finite"):
                    core.validate_document("book", book)
            self.assert_bad_source(lambda book: book["blocks"][index].update(scale_evidence=" \n"))
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book["blocks"][4].update(source_em=10), "immutable")
        self.assert_bad_book(lambda book: book["blocks"][5].update(scale_evidence="Different calibration"), "immutable")
        # Calibration never excuses contradictory source geometry.
        self.assert_bad_source(lambda book: book["blocks"][5]["images"][0].update(x=-1))
        self.assert_bad_source(lambda book: book["blocks"][5]["images"][0].update(x=40), "beyond")
        self.assert_bad_source(lambda book: book["blocks"][5]["images"][0].update(height=10), "aspect ratio")
        self.assert_bad_source(lambda book: book["blocks"][4].update(height=10), "aspect ratio")

    def install_note_evidence(self):
        shutil.copyfile(self.root / "assets/wide.png", self.root / "evidence/note.png")
        evidence = [{"asset": "evidence/note.png", "source_page": "p1",
                     "description": "Synthetic original raster at bbox [10,20,50,40]; asterisk at [10,20] associates it with the paragraph callout."}]
        for book in (self.source, self.book):
            book["notes"][0]["source_evidence"] = copy.deepcopy(evidence)
        self.publish_manuscripts()

    def test_raster_prose_note_uses_transcript_and_nonrendered_evidence(self):
        self.install_note_evidence()
        note = core.validate_book(self.root)["notes"][0]
        self.assertEqual(note["content_type"], "prose")
        self.assertTrue(any("text" in token for token in note["source"]))
        self.assertFalse(any("image" in token for token in note["target"]))
        self.assert_bad_book(lambda book: book["notes"][0]["source_evidence"][0].update(description="Changed association"), "immutable")
        self.assert_bad_source(lambda book: book["notes"][0]["source_evidence"][0].update(source_page="missing"), "unknown source page")
        self.assert_bad_source(lambda book: book["notes"][0]["source_evidence"][0].update(description=" "))
        image = {"image": {"asset": "evidence/note.png", "width_em": 2, "height_em": 1, "raise_em": 0}}
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append(image), "non-rendered")
        self.assert_bad_source(lambda book: book["notes"][0].update(source=[dict(image, image=dict(image["image"], asset="assets/wide.png"))]), "transcribed")

    def test_note_evidence_bytes_are_bound_by_source_seal_and_content_digest(self):
        self.install_note_evidence()
        before = core.content_digest(self.root)
        Image.new("RGB", (40, 20), "green").save(self.root / "evidence/note.png")
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root)
        core.seal_source(self.root)
        self.assertNotEqual(core.content_digest(self.root), before)
        (self.root / "evidence/note.png").write_bytes(b"Not an image")
        with self.assertRaisesRegex(ValueError, "readable raster"):
            core.validate_book(self.root, translated=False)

    def test_note_source_evidence_cannot_escape_or_use_generated_artifacts(self):
        self.install_note_evidence()
        outside = Path(self.temporary.name) / "outside.png"
        shutil.copyfile(self.root / "assets/wide.png", outside)
        (self.root / "evidence/escape.png").symlink_to(outside)
        (self.root / "build").mkdir()
        shutil.copyfile(outside, self.root / "build/note.png")
        for path in ("../outside.png", str(outside), "evidence/escape.png", "build/note.png", "missing.png"):
            with self.subTest(path=path):
                self.assert_bad_source(lambda book: book["notes"][0]["source_evidence"][0].update(asset=path))
        self.assertEqual(outside.read_bytes(), (self.root / "assets/wide.png").read_bytes())

    def test_prose_notes_require_real_transcription_and_translated_semantics(self):
        self.assert_bad_source(lambda book: book["notes"][0].pop("content_type"))
        self.assert_bad_source(lambda book: book["notes"][0].update(content_type="literal", literal_reason="Prose must not become literal"), "ordinary prose")
        for tokens in ([{"protected": "variable"}],
                       [{"image": {"asset": "assets/wide.png", "width_em": 2, "height_em": 1, "raise_em": 0}}]):
            with self.subTest(tokens=tokens):
                self.assert_bad_source(lambda book: book["notes"][0].update(source=tokens), "transcribed")
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book["notes"][0].update(target=[{"protected": "variable"}]), "ordinary text")
        unchanged = [{"text": " A "}, {"term": "small"}, {"text": " VALUE! "}, {"protected": "variable"}]
        self.assert_bad_book(lambda book: book["notes"][0].update(target=unchanged), "completely unchanged")
        self.assert_bad_book(lambda book: book["notes"][0].update(target=copy.deepcopy(book["notes"][0]["source"])), "completely unchanged")
        # Different-language translation is semantic, not a simplistic language-ID test.
        self.book["notes"][0]["target"][0]["text"] = "\u8bd1\u6ce8 "
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)
        self.job["target_language"] = self.job["source_language"]
        self.write("job.json", self.job)
        self.book["notes"][0]["target"] = unchanged
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_same_primary_language_tags_do_not_require_prose_translation(self):
        self.book["notes"][0]["target"] = [{"text": " A "}, {"term": "small"}, {"text": " VALUE! "}, {"protected": "variable"}]
        self.write("book.json", self.book)
        for source_language, target_language in (("en", "en-US"), ("EN_us", "en-GB"), ("zh-Hant", "zh-Hans")):
            with self.subTest(source=source_language, target=target_language):
                self.job.update(source_language=source_language, target_language=target_language)
                self.write("job.json", self.job)
                self.assertEqual(core.validate_book(self.root), self.book)


    def install_restoration_note(self):
        image = {"image": {"asset": "assets/wide.png", "width_em": 2, "height_em": 1, "raise_em": 0}}
        fragment = '"deve[gap]pment"'
        metadata = {"source_page": "p1", "original_fragment": fragment, "replacement": "development",
                    "status": "conjectural", "evidence": "Synthetic contextual reading; missing ink is not recovered.",
                    "damage_asset": "assets/wide.png"}
        evidence = [{"asset": "assets/wide.png", "source_page": "p1", "description": "Synthetic original damaged word crop at [10,20,50,40]."},
                    {"asset": "assets/tall.png", "source_page": "p1", "description": "Separate synthetic audit-only context raster."}]
        for manuscript in (self.source, self.book):
            block = manuscript["blocks"][1]
            index = next(index for index, token in enumerate(block["source"]) if token.get("note") == "n1")
            block["source"].insert(index, {"text": " development  "})
            manuscript["notes"][0].update(
                restoration=copy.deepcopy(metadata), source_evidence=copy.deepcopy(evidence),
                source=[{"text": "Editorial reconstruction (contextual conjecture, not recovered ink): development. Original fragment: "},
                        {"text": fragment}, {"text": " Original damage: "}, copy.deepcopy(image), {"protected": "variable"}])
        block = self.book["blocks"][1]
        index = next(index for index, token in enumerate(block["target"]) if token.get("note") == "n1")
        block["target"].insert(index, {"text": " \uac1c\ubc1c "})
        self.book["notes"][0]["target"] = [
            {"text": "\ubcf5\uc6d0 \uc124\uba85 (\ubb38\ub9e5\uc5d0 \ub530\ub978 \ucd94\uce21): "}, {"term": "small"}, {"text": ". \uc6d0\ubb38: "},
            {"text": fragment}, {"text": " \uc6d0\ub798 \uc190\uc0c1 \uc774\ubbf8\uc9c0: "}, copy.deepcopy(image), {"protected": "variable"}]
        self.publish_manuscripts()
        return image

    def test_restoration_conserves_repaired_body_excerpt_and_visible_crop(self):
        self.install_restoration_note()
        for status in ("confirmed", "conjectural"):
            with self.subTest(status=status):
                for manuscript in (self.source, self.book):
                    manuscript["notes"][0]["restoration"]["status"] = status
                self.publish_manuscripts()
                self.assertEqual(core.validate_book(self.root), self.book)
                self.assertNotIn("development", "".join(token.get("text", "") for token in self.book["blocks"][1]["target"]))
        # The repaired span may be a suffix of a damaged word, not only a whole word.
        for manuscript in (self.source, self.book):
            manuscript["notes"][0]["restoration"]["replacement"] = "ment"
        self.publish_manuscripts()
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_restoration_schema_requires_complete_known_metadata(self):
        self.install_restoration_note()
        metadata = self.source["notes"][0]["restoration"]
        for field in metadata:
            with self.subTest(missing=field):
                source = copy.deepcopy(self.source)
                source["notes"][0]["restoration"].pop(field)
                with self.assertRaises(ValueError):
                    core.validate_document("book", source)
        for change in ({"status": "scan_verified"}, {"evidence": " "}, {"replacement": ""}, {"fallback": True}):
            with self.subTest(change=change):
                source = copy.deepcopy(self.source)
                source["notes"][0]["restoration"].update(change)
                with self.assertRaises(ValueError):
                    core.validate_document("book", source)

    def test_restoration_is_linked_to_the_actual_source_reading_and_page(self):
        self.install_restoration_note()
        self.assert_bad_source(lambda book: book["notes"][0]["restoration"].update(replacement="unrelated"), "immediately precede")
        self.assert_bad_source(lambda book: book["notes"][0]["restoration"].update(replacement=" development "), "immediately precede")
        self.assert_bad_source(lambda book: book["notes"][0]["restoration"].update(source_page="p2"), "owning source block")
        self.assert_bad_source(lambda book: book["notes"][0]["restoration"].update(source_page="missing"), "owning source block")
        self.assert_bad_source(lambda book: book["notes"][0].update(content_type="literal", literal_reason="Not a prose exception"), "restoration requires a prose note")

    def test_restoration_requires_one_visible_original_crop_with_matching_evidence(self):
        image = self.install_restoration_note()
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append(copy.deepcopy(image)), "exactly one original damage image")
        self.assert_bad_source(lambda book: book["notes"][0]["source"].pop(3), "exactly one original damage image")
        self.assert_bad_source(lambda book: book["notes"][0]["restoration"].update(damage_asset="assets/tall.png"), "exactly one original damage image")
        self.assert_bad_source(lambda book: book["notes"][0].pop("source_evidence"), "matching original source-page evidence")
        self.assert_bad_source(lambda book: book["notes"][0]["source_evidence"][0].update(source_page="p2"), "matching original source-page evidence")
        self.assert_bad_source(lambda book: book["notes"][0]["source_evidence"].append(copy.deepcopy(book["notes"][0]["source_evidence"][0])), "matching original source-page evidence")
        other = {"image": {"asset": "assets/tall.png", "width_em": .5, "height_em": 1, "raise_em": 0}}
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append(other), "non-rendered")

    def test_restoration_excerpt_remains_verbatim_and_has_a_translated_explanation(self):
        image = self.install_restoration_note()
        fragment = self.source["notes"][0]["restoration"]["original_fragment"]
        self.assert_bad_source(lambda book: book["notes"][0]["source"][1].update(text="Changed excerpt"), "original_fragment")
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append({"text": fragment}), "original_fragment")
        self.assert_bad_source(lambda book: book["notes"][0].update(source=[{"text": fragment}, image, {"protected": "variable"}]), "semantic explanation")
        self.publish_manuscripts()
        self.assert_bad_book(lambda book: book["notes"][0]["target"][3].update(text="Translated away"), "original_fragment")
        self.assert_bad_book(lambda book: book["notes"][0]["target"].append({"text": fragment}), "original_fragment")
        self.assert_bad_book(lambda book: book["notes"][0]["target"].__setitem__(slice(3, 4), [{"text": fragment[:5]}, {"text": fragment[5:]}]), "original_fragment")
        self.assert_bad_book(lambda book: book["notes"][0].update(target=[{"text": fragment}, image, {"protected": "variable"}]), "semantic explanation")
        self.assert_bad_book(lambda book: book["notes"][0].update(target=copy.deepcopy(book["notes"][0]["source"])), "completely unchanged")

    def test_restoration_crop_tokens_metadata_and_bytes_remain_sealed(self):
        self.install_restoration_note()
        self.assert_bad_book(lambda book: book["notes"][0]["target"].pop(5), "preserve.*image")
        self.assert_bad_book(lambda book: book["notes"][0]["target"][5]["image"].update(width_em=3), "preserve.*image")
        for field, value in (("status", "confirmed"), ("original_fragment", "Other source"), ("evidence", "Other witness")):
            with self.subTest(field=field):
                self.assert_bad_book(lambda book: book["notes"][0]["restoration"].update({field: value}), "immutable")
        self.write("book.json", self.book)
        Image.new("RGB", (40, 20), "green").save(self.root / "assets/wide.png")
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root)


    def test_literal_notes_preserve_code_comments_names_math_and_images(self):
        self.install_inline_images()
        self.terms["terms"].append({"id": "nameOnly", "number": 3, "source": "Euler", "target": "Euler",
                                    "authority": "Synthetic name decision", "authority_locator": "Fixture",
                                    "rationale": "Literal personal name", "protected_ids": ["person"]})
        self.book["blocks"][0]["target"].append({"term": "small"})
        literal = [{"protected": "program"}, {"text": " ; "}, {"protected": "person"},
                   {"protected": "variable"}, {"protected": "formula"},
                   {"image": {"asset": "assets/wide.png", "width_em": 2, "height_em": 1, "raise_em": 0}}]
        for book in (self.source, self.book):
            book["notes"][0].update(content_type="literal", literal_reason="Original protected program including its English comments, personal name, formula, and non-prose image.", source=copy.deepcopy(literal))
        self.book["notes"][0]["target"] = copy.deepcopy(literal)
        self.book["notes"][0]["target"][2] = {"term": "nameOnly"}
        self.publish_manuscripts()
        checked = core.validate_book(self.root)
        self.assertEqual(next(value["value"] for value in checked["protected"] if value["id"] == "program"),
                         "# English comment\nvalue = 1\n\tprint(value)\n")
        self.assert_bad_source(lambda book: book["notes"][0].pop("literal_reason"))
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append({"text": "ordinary prose"}), "ordinary prose")
        self.write("book-source.json", self.source)
        self.assert_bad_book(lambda book: book["notes"][0]["target"].append({"text": "ordinary prose"}), "ordinary prose")
        self.assert_bad_book(lambda book: book["notes"][0]["target"].pop(0), "preserve")

    def test_valid_translated_book(self):
        self.assertEqual(core.validate_book(self.root), self.book)
        self.assertRegex(core.content_digest(self.root), r"^[a-f0-9]{64}$")

    def test_title_terms_are_optional_without_injecting_metadata(self):
        for metadata in ({}, {"title_terms": []}):
            book = dict(self.book, **metadata)
            expected = copy.deepcopy(book)
            with self.subTest(metadata=metadata):
                core.validate_document("book", book)
                self.assertEqual(book, expected)
                self.write("book.json", book)
                before = (self.root / "book.json").read_bytes()
                self.assertEqual(core.validate_book(self.root), expected)
                self.assertEqual((self.root / "book.json").read_bytes(), before)

    def test_source_stage_accepts_empty_title_terms_without_admitted_terms(self):
        self.source["title_terms"] = []
        self.write("book-source.json", self.source)
        for name in ("terms.json", "book.json", "source.sha256"):
            (self.root / name).unlink()
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)
        core.seal_source(self.root)
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)
        self.write("terms.json", self.terms)
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_source_stage_rejects_nonempty_title_terms(self):
        self.source.update(title="small", title_terms=[{"term": "small", "start": 0, "end": 5}])
        self.write("book-source.json", self.source)
        for name in ("terms.json", "book.json"):
            (self.root / name).unlink()
        with self.assertRaises(ValueError):
            core.validate_book(self.root, translated=False)
        with self.assertRaises(ValueError):
            core.seal_source(self.root)

    def test_title_term_schema_requires_only_reference_and_integer_offsets(self):
        span = {"term": "small", "start": 0, "end": 5}
        invalid = [None, {}, "small", [None], ["small"], [{}]]
        invalid += [[{key: value for key, value in span.items() if key != field}]
                    for field in span]
        invalid += [[dict(span, **{field: value})]
                    for field in ("start", "end")
                    for value in (-1, True, False, 1.5, 1.0, "1", None)]
        invalid += [[dict(span, term=value)] for value in ("", "1bad", "has space", None, 1)]
        invalid += [[dict(span, **{field: "small"})] for field in ("text", "title", "target", "unexpected")]
        for title_terms in invalid:
            with self.subTest(title_terms=title_terms), self.assertRaises(ValueError):
                core.validate_document("book", dict(self.book, title="small", title_terms=title_terms))

    def test_title_terms_require_nonempty_in_range_ordered_nonoverlapping_spans(self):
        invalid = [
            [(0, 0)], [(1, 1)], [(4, 3)], [(0, 11)], [(10, 11)],
            [(5, 10), (0, 5)], [(0, 5), (4, 9)], [(0, 5), (0, 5)],
            [(0, 10), (2, 5)],
        ]
        for ranges in invalid:
            spans = [{"term": "small", "start": start, "end": end} for start, end in ranges]
            with self.subTest(ranges=ranges):
                self.assert_bad_book(lambda book: book.update(title="smallsmall", title_terms=spans))
        self.book.update(title="smallsmall", title_terms=[
            {"term": "small", "start": 0, "end": 5},
            {"term": "small", "start": 5, "end": 10},
        ])
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_title_terms_require_known_ids(self):
        self.assert_bad_book(lambda book: book.update(
            title="small", title_terms=[{"term": "missing", "start": 0, "end": 5}]))

    def test_title_terms_accept_source_or_target_without_replacing_the_title(self):
        for literal in ("Euler", "Euler method"):
            book = dict(self.book, title="\U0001f4da " + literal,
                        title_terms=[{"term": "euler", "start": 2, "end": 2 + len(literal)}])
            self.write("book.json", book)
            with self.subTest(literal=literal):
                self.assertEqual(core.validate_book(self.root), book)
                self.assertEqual(core.load_json(self.root / "book.json"), book)
        for literal in ("Small", " small ", "smal"):
            with self.subTest(literal=literal):
                self.assert_bad_book(lambda book: book.update(
                    title=literal, title_terms=[{"term": "small", "start": 0, "end": len(literal)}]))

    def test_title_only_terms_allow_repeated_refs_with_unicode_codepoint_offsets(self):
        term = dict(self.terms["terms"][1], id="titleOnly", number=3,
                    source="physical design", target="\u7269\u7406\u8bbe\u8ba1")
        self.terms["terms"].append(term)
        self.write("terms.json", self.terms)
        self.book.update(title="\U0001f4da \u7269\u7406\u8bbe\u8ba1 / physical design", title_terms=[
            {"term": "titleOnly", "start": 2, "end": 6},
            {"term": "titleOnly", "start": 9, "end": 24},
        ])
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_title_terms_use_literal_codepoints_without_unicode_normalization(self):
        term = dict(self.terms["terms"][1], id="titleOnly", number=3,
                    source="caf\u00e9", target="coffee")
        self.terms["terms"].append(term)
        self.write("terms.json", self.terms)
        self.book.update(title="\U0001f4da cafe\u0301",
                         title_terms=[{"term": "titleOnly", "start": 2, "end": 7}])
        self.write("book.json", self.book)
        with self.assertRaises(ValueError):
            core.validate_book(self.root)
        term["target"] = "cafe\u0301"
        self.write("terms.json", self.terms)
        self.assertEqual(core.validate_book(self.root), self.book)
        self.assert_bad_book(lambda book: book["title_terms"][0].update(end=6))

    def test_unselected_or_different_title_references_do_not_infer_terminology_use(self):
        self.terms["terms"].append(dict(self.terms["terms"][1], id="titleOnly", number=3))
        self.write("terms.json", self.terms)
        for metadata in ({}, {"title_terms": []},
                         {"title_terms": [{"term": "small", "start": 0, "end": 5}]}):
            self.write("book.json", dict(self.book, title="small", **metadata))
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                core.validate_book(self.root)
        self.book.update(title="small", title_terms=[{"term": "titleOnly", "start": 0, "end": 5}])
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_translated_title_terms_preserve_source_bytes_and_existing_seal(self):
        source_before = (self.root / "book-source.json").read_bytes()
        seal_before = (self.root / "source.sha256").read_bytes()
        self.book["title"] = "small"
        self.write("book.json", self.book)
        digest_before = core.content_digest(self.root)
        self.book["title_terms"] = [{"term": "small", "start": 0, "end": 5}]
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)
        self.assertNotEqual(core.content_digest(self.root), digest_before)
        self.assertEqual((self.root / "book-source.json").read_bytes(), source_before)
        self.assertEqual((self.root / "source.sha256").read_bytes(), seal_before)


    def test_source_stage_needs_no_terms_targets_or_preface(self):
        (self.root / "terms.json").unlink()
        (self.root / "book.json").unlink()
        (self.root / "source.sha256").unlink()
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)
        self.assertRegex(core.seal_source(self.root), r"^[a-f0-9]{64}$")

    def test_source_stage_ignores_unfinished_targets(self):
        self.source["blocks"][1]["target"] = [{"term": "not_written_yet"}]
        self.write("book-source.json", self.source)
        (self.root / "source.sha256").unlink()
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)

    def test_schema_rejects_additional_fields_at_every_level(self):
        locations = [(), ("source_pages", 0), ("protected", 0), ("blocks", 0), ("blocks", 0, "source", 0), ("notes", 0), ("blocks", 5, "images", 0)]
        for location in locations:
            with self.subTest(location=location):
                value = copy.deepcopy(self.book)
                target = value
                for key in location:
                    target = target[key]
                target["unexpected"] = "ignored fields are dangerous"
                with self.assertRaises(ValueError):
                    core.validate_document("book", value)

    def test_schema_requires_every_document_field(self):
        for kind, document in [("book", self.book), ("terms", self.terms), ("job", self.job), ("review", self.review())]:
            for key in document:
                with self.subTest(kind=kind, key=key):
                    value = copy.deepcopy(document)
                    del value[key]
                    with self.assertRaises(ValueError):
                        core.validate_document(kind, value)

    def test_schema_blocks_cannot_mix_kind_fields(self):
        self.assert_bad_book(lambda book: book["blocks"][1].update(level=1))
        self.assert_bad_book(lambda book: book["blocks"][0].update(kind="paragraph"))

    def test_inline_must_have_exactly_one_known_key(self):
        for token in [{}, {"text": "text", "protected": "person"}, {"mystery": "person"}, {"protected": "1bad"}]:
            with self.subTest(token=token):
                self.assert_bad_book(lambda book: book["blocks"][0].update(target=[token]))

    def test_versions_and_numeric_types_are_strict(self):
        for version in [True, 1, "2", None]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                core.validate_document("book", dict(self.book, version=version))
        for number in [0, -1, True, 1.5]:
            terms = copy.deepcopy(self.terms)
            terms["terms"][0]["number"] = number
            with self.subTest(number=number), self.assertRaises(ValueError):
                core.validate_document("terms", terms)

    def test_duplicate_ids_and_term_numbers(self):
        for name in ("source_pages", "protected", "blocks", "notes"):
            with self.subTest(name=name):
                self.assert_bad_source(lambda book: book[name].append(copy.deepcopy(book[name][0])), "duplicate")
        terms = copy.deepcopy(self.terms)
        terms["terms"][1]["number"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate number"):
            core.validate_document("terms", terms)
        terms["terms"][1]["number"] = 2
        terms["terms"][1]["id"] = "euler"
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            core.validate_document("terms", terms)

    def test_cross_category_ids_are_unique(self):
        self.assert_bad_source(lambda book: book["blocks"][0].update(id="p1"), "unique across")

    def test_bad_ids_rejected(self):
        for value in ["1page", "has space", "a/b", "", "a.b"]:
            with self.subTest(value=value):
                self.assert_bad_source(lambda book: book["source_pages"][0].update(id=value))

    def test_source_rejects_term_tokens(self):
        self.assert_bad_source(lambda book: book["blocks"][0]["source"].append({"term": "euler"}), "source inline")
        self.assert_bad_source(lambda book: book["notes"][0]["source"].append({"term": "small"}), "source inline")

    def test_source_requires_real_content_not_page_only(self):
        for tokens in [[], [{"text": " \n"}], [{"page": "p1"}]]:
            with self.subTest(tokens=tokens):
                self.assert_bad_source(lambda book: book["blocks"][0].update(source=tokens), "source text/evidence")

    def test_present_printed_labels_require_review(self):
        self.assert_bad_source(lambda book: book["source_pages"][0].update(label_verified=False), "printed label")

    def test_null_repeated_roman_and_prefixed_page_labels(self):
        for label in [None, "iv", "A-12"]:
            with self.subTest(label=label):
                self.source["source_pages"][1].update(printed_label=label, label_verified=label is not None)
                self.write("book-source.json", self.source)
                core.seal_source(self.root)
                self.assertEqual(core.validate_book(self.root, translated=False), self.source)

    def test_pages_require_locator_and_evidence(self):
        for field in ["locator", "evidence"]:
            with self.subTest(field=field):
                self.assert_bad_source(lambda book: book["source_pages"][0].update({field: " "}))

    def test_page_coverage_and_reading_order(self):
        self.assert_bad_source(lambda book: book["source_pages"].append({"id": "p3", "locator": "p0003", "printed_label": None, "label_verified": False, "evidence": "page image"}), "coverage")
        self.assert_bad_source(lambda book: book["blocks"][1].update(source_pages=["missing"]), "unknown source page")
        self.assert_bad_source(lambda book: book["blocks"][0].update(source_pages=[]))
        self.assert_bad_source(lambda book: book["blocks"].reverse(), "reading order")

    def test_page_tokens_stay_with_block_and_occur_once(self):
        self.assert_bad_source(lambda book: book["blocks"][0]["source"].append({"page": "p2"}), "absent from block")
        self.assert_bad_source(lambda book: book["blocks"][1]["source"].append({"page": "p1"}), "once")

    def test_targets_preserve_every_protected_note_page_token(self):
        for index, key in [(0, "page"), (1, "protected"), (1, "note")]:
            with self.subTest(index=index, key=key):
                self.assert_bad_book(lambda book: book["blocks"][index].update(target=[token for token in book["blocks"][index]["target"] if key not in token]), "preserve")
        self.assert_bad_book(lambda book: book["blocks"][1]["target"].reverse(), "preserve")
        self.assert_bad_book(lambda book: book["blocks"][1]["target"].append({"protected": "variable"}), "multiplicity")

    def test_protected_names_expand_through_terms(self):
        self.assertEqual(core.validate_book(self.root), self.book)
        self.terms["terms"][0]["protected_ids"] = []
        self.write("terms.json", self.terms)
        with self.assertRaisesRegex(ValueError, "preserve"):
            core.validate_book(self.root)

    def test_terms_require_exact_protected_names_order_and_multiplicity(self):
        for target in ["euler method", "Euler Euler method", "Renamed method"]:
            with self.subTest(target=target):
                terms = copy.deepcopy(self.terms)
                terms["terms"][0]["target"] = target
                self.write("terms.json", terms)
                with self.assertRaisesRegex(ValueError, "protected name"):
                    core.validate_book(self.root)
        terms = copy.deepcopy(self.terms)
        terms["terms"][0]["protected_ids"] = ["variable"]
        self.write("terms.json", terms)
        with self.assertRaisesRegex(ValueError, "protected names"):
            core.validate_book(self.root)

    def test_terms_require_source_literal_and_known_protected_ids(self):
        for change in [lambda term: term.update(source="Renamed"), lambda term: term.update(protected_ids=["missing"])]:
            terms = copy.deepcopy(self.terms)
            change(terms["terms"][0])
            self.write("terms.json", terms)
            with self.assertRaises(ValueError):
                core.validate_book(self.root)

    def test_overlapping_protected_name_values_use_disjoint_spans(self):
        self.source["protected"][0]["value"] = "Ann"
        self.source["protected"].append({"id": "other", "kind": "name", "value": "Anna"})
        self.source["blocks"][1]["source"].insert(2, {"protected": "other"})
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.book["protected"] = copy.deepcopy(self.source["protected"])
        self.book["blocks"][1]["source"] = copy.deepcopy(self.source["blocks"][1]["source"])
        self.terms["terms"][0].update(source="Ann and Anna method", target="Ann and Anna method", protected_ids=["person", "other"])
        self.write("book.json", self.book)
        self.write("terms.json", self.terms)
        self.assertEqual(core.validate_book(self.root), self.book)
        for target in ["Ann and Anna method Ann", "Ann and Anna method Anna", "Anna and Ann method"]:
            self.terms["terms"][0]["target"] = target
            self.write("terms.json", self.terms)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "protected name"):
                core.validate_book(self.root)

    def test_unknown_and_unused_terms_rejected_only_on_translation(self):
        self.assert_bad_book(lambda book: book["blocks"][1]["target"].append({"term": "missing"}), "unknown term")
        self.write("book.json", self.book)
        terms = copy.deepcopy(self.terms)
        extra = copy.deepcopy(terms["terms"][1])
        extra.update(id="unused", number=3)
        terms["terms"].append(extra)
        core.validate_document("terms", terms)
        self.write("terms.json", terms)
        core.validate_book(self.root, translated=False)
        with self.assertRaisesRegex(ValueError, "Unused terminology"):
            core.validate_book(self.root)

    def test_terms_require_authority_locator_and_rationale(self):
        for field in ["authority", "authority_locator", "rationale", "source", "target"]:
            terms = copy.deepcopy(self.terms)
            terms["terms"][0][field] = " "
            with self.subTest(field=field), self.assertRaises(ValueError):
                core.validate_document("terms", terms)

    def test_notes_have_exactly_one_body_callout(self):
        self.assert_bad_source(lambda book: book["blocks"][1]["source"].append({"note": "n1"}), "exactly one")
        self.assert_bad_source(lambda book: book["blocks"][1].update(source=[token for token in book["blocks"][1]["source"] if "note" not in token]), "exactly one")
        self.assert_bad_source(lambda book: book["blocks"][1]["source"].append({"note": "missing"}), "unknown note")

    def test_note_nesting_and_page_tokens_are_forbidden(self):
        for token in [{"note": "n1"}, {"page": "p1"}]:
            with self.subTest(token=token):
                self.assert_bad_source(lambda book: book["notes"][0]["source"].append(token), "nested note or page")
                self.assert_bad_book(lambda book: book["notes"][0]["target"].append(token), "nested note or page")

    def test_note_targets_preserve_protected_values(self):
        self.assert_bad_book(lambda book: book["notes"][0].update(target=[{"text": "Removed variable"}]), "preserve")
        self.assert_bad_book(lambda book: book["notes"][0].update(target=[]), "preserve")

    def test_unknown_and_unused_protected_values_are_rejected(self):
        self.assert_bad_source(lambda book: book["blocks"][0]["source"].append({"protected": "missing"}), "unknown protected")
        self.assert_bad_source(lambda book: book["protected"].append({"id": "unused", "kind": "name", "value": "Unused"}), "all be used")

    def test_direct_math_and_code_references_have_correct_kind(self):
        self.assert_bad_source(lambda book: book["blocks"][2].update(protected_id="program"), "protected math")
        self.assert_bad_source(lambda book: book["blocks"][3].update(protected_id="formula"), "protected code")

    def test_translated_targets_and_agent_preface_are_required(self):
        self.assert_bad_book(lambda book: book["blocks"][0].update(target=[]), "preserve")
        for preface in [[], [{"text": " \n"}]]:
            with self.subTest(preface=preface):
                self.assert_bad_book(lambda book: book.update(agent_preface=preface), "nonempty agent_preface")

    def test_prefaces_allow_text_protected_and_terms_but_not_note_page(self):
        for field in ["agent_preface", "human_preface"]:
            for token in [{"note": "n1"}, {"page": "p1"}]:
                with self.subTest(field=field, token=token):
                    self.assert_bad_book(lambda book: book.update({field: [token]}), "prefaces permit")
        self.book["human_preface"] = [{"text": "Human note "}, {"protected": "person"}, {"term": "euler"}]
        self.book["agent_preface"].extend([{"protected": "variable"}, {"term": "small"}])
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_preface_only_terminology_counts_as_used(self):
        term = copy.deepcopy(self.terms["terms"][1])
        term.update(id="prefaceOnly", number=3, source="introduction", target="introduction")
        self.terms["terms"].append(term)
        self.write("terms.json", self.terms)
        for field in ["agent_preface", "human_preface"]:
            book = copy.deepcopy(self.book)
            book[field] = [{"term": "prefaceOnly"}]
            self.write("book.json", book)
            with self.subTest(field=field):
                self.assertEqual(core.validate_book(self.root), book)

    def test_prefaces_reject_unknown_terminology(self):
        for field in ["agent_preface", "human_preface"]:
            with self.subTest(field=field):
                self.assert_bad_book(lambda book: book.update({field: [{"term": "missing"}]}), "unknown term")

    def test_immutable_source_changes_are_rejected(self):
        changes = [
            lambda book: book["blocks"][1]["source"][0].update(text="Changed original text"),
            lambda book: book["protected"][0].update(value="EULER"),
            lambda book: book["protected"][3].update(value=book["protected"][3]["value"].replace("\t", "    ")),
            lambda book: book["source_pages"][0].update(printed_label="invented"),
            lambda book: book["blocks"][0].update(level=2),
            lambda book: book["blocks"][5].update(relation="column"),
            lambda book: book["blocks"][5]["images"][0].update(x=1),
            lambda book: book["notes"][0]["source"][0].update(text="Changed note"),
            lambda book: book["blocks"].pop(),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assert_bad_book(change, "immutable source")

    def test_only_title_title_terms_targets_and_prefaces_may_change(self):
        self.book["title"] = "small: A different translated title"
        self.book["title_terms"] = [{"term": "small", "start": 0, "end": 5}]
        self.book["blocks"][0]["target"][1]["text"] = "New translated heading"
        self.book["notes"][0]["target"][0]["text"] = "Different wording "
        self.book["agent_preface"] = [{"text": "Updated machine-translation disclosure"}]
        self.book["human_preface"] = [{"text": "Human introduction"}]
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root), self.book)

    def test_seal_binds_entire_source_and_rejects_missing_or_corrupt_seal(self):
        seal = (self.root / "source.sha256").read_text(encoding="ascii")
        for value in ["", "0" * 64, "not a checksum"]:
            with self.subTest(value=value):
                (self.root / "source.sha256").write_text(value, encoding="ascii")
                with self.assertRaisesRegex(ValueError, "Source seal"):
                    core.validate_book(self.root)
        (self.root / "source.sha256").unlink()
        with self.assertRaisesRegex(ValueError, "source seal"):
            core.validate_book(self.root)
        (self.root / "source.sha256").write_text(seal, encoding="ascii")
        self.source["title"] = "Changed source title"
        self.write("book-source.json", self.source)
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root)
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root, translated=False)
        core.seal_source(self.root)
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)

    def test_validated_source_revision_does_not_replace_existing_seal(self):
        previous = (self.root / "source.sha256").read_bytes()
        self.source["title"] = "Explicitly reviewed source correction"
        self.write("book-source.json", self.source)
        self.assertEqual(core.validate_source(self.root), self.source)
        snapshot = core.source_snapshot_digest(self.root)
        self.assertNotEqual(snapshot, previous.decode("ascii").strip())
        self.assertEqual((self.root / "source.sha256").read_bytes(), previous)
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root, translated=False)
        self.assertEqual(core.seal_source(self.root), snapshot)
        self.assertEqual(core.validate_book(self.root, translated=False), self.source)

    def test_source_snapshot_validates_source_assets_without_resealing(self):
        previous = (self.root / "source.sha256").read_bytes()
        self.source["blocks"][4]["width"] = 41
        self.write("book-source.json", self.source)
        for validate in (core.validate_source, core.source_snapshot_digest):
            with self.subTest(validator=validate.__name__), self.assertRaisesRegex(ValueError, "aspect ratio"):
                validate(self.root)
        self.assertEqual((self.root / "source.sha256").read_bytes(), previous)

    def test_seal_binds_referenced_image_bytes(self):
        Image.new("RGB", (40, 20), "green").save(self.root / "assets/wide.png")
        with self.assertRaisesRegex(ValueError, "Source seal"):
            core.validate_book(self.root)

    def test_original_source_must_match_checksum(self):
        (self.root / "evidence/source.pdf").write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "Original source checksum"):
            core.validate_book(self.root)
        with self.assertRaisesRegex(ValueError, "Original source checksum"):
            core.seal_source(self.root)
        for validate in (core.validate_source, core.source_snapshot_digest):
            with self.subTest(validator=validate.__name__), self.assertRaisesRegex(ValueError, "Original source checksum"):
                validate(self.root)

    def test_asset_dimensions_and_group_canvas_are_strict(self):
        changes = [
            lambda book: book["blocks"][4].update(width=0),
            lambda book: book["blocks"][4].update(height=-1),
            lambda book: book["blocks"][5].update(images=[]),
            lambda book: book["blocks"][5].update(canvas_width=0),
            lambda book: book["blocks"][5].update(text_fraction=0.1),
            lambda book: book["blocks"][5]["images"][0].update(x=-1),
            lambda book: book["blocks"][5]["images"][0].update(y=21),
            lambda book: book["blocks"][5]["images"][1].update(x=51),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assert_bad_source(change)

    def test_declared_asset_aspect_ratio_matches_source(self):
        self.assert_bad_source(lambda book: book["blocks"][4].update(width=41), "aspect ratio")
        self.assert_bad_source(lambda book: book["blocks"][5]["images"][0].update(height=19), "aspect ratio")

    def test_missing_and_unreadable_assets_fail(self):
        self.assert_bad_source(lambda book: book["blocks"][4].update(asset="assets/missing.png"), "missing file")
        self.assert_bad_source(lambda book: book["blocks"][4].update(asset="assets/unused.txt"), "readable raster")

    def test_asset_paths_cannot_escape_or_use_absolute_paths(self):
        for value in ["../escape.png", "/tmp/image.png", "assets/../../image.png", "C:/image.png", r"C:\image.png", "assets\\wide.png"]:
            with self.subTest(value=value):
                self.assert_bad_source(lambda book: book["blocks"][4].update(asset=value), "path")

    def test_asset_symlink_escape_is_rejected(self):
        outside = Path(self.temporary.name) / "outside.png"
        shutil.copyfile(self.root / "assets/wide.png", outside)
        (self.root / "assets/escape.png").symlink_to(outside)
        self.assert_bad_source(lambda book: book["blocks"][4].update(asset="assets/escape.png"), "escapes")

    def test_generated_artifacts_are_not_source_assets(self):
        (self.root / "build").mkdir()
        shutil.copyfile(self.root / "assets/wide.png", self.root / "build/image.png")
        self.assert_bad_source(lambda book: book["blocks"][4].update(asset="build/image.png"), "Generated artifacts")

    def test_source_file_path_is_contained(self):
        for value in ["../source.pdf", "/tmp/source.pdf", "C:/source.pdf"]:
            self.job["source_file"] = value
            self.write("job.json", self.job)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "path"):
                core.validate_book(self.root)

    def test_manuscript_and_seal_symlinks_cannot_escape(self):
        for name in ["book-source.json", "book.json", "terms.json", "job.json", "source.sha256"]:
            with self.subTest(name=name):
                path = self.root / name
                outside = Path(self.temporary.name) / (name + ".outside")
                shutil.copyfile(path, outside)
                path.unlink()
                path.symlink_to(outside)
                with self.assertRaisesRegex(ValueError, "escapes"):
                    core.validate_book(self.root)
                path.unlink()
                shutil.copyfile(outside, path)

    def test_math_allowlist_rejects_executable_and_obfuscated_tex(self):
        commands = [r"\input{secret}", r"\include{file}", r"\write18{cmd}", r"\read1", r"\openout1", r"\catcode`x=0", r"\csname input\endcsname", r"\special{cmd}", r"\directlua{cmd}", r"\def\a{x}", r"\newcommand{\a}{x}", r"\usepackage{x}", r"\begin{document}x\end{document}", "x% comment", "^^5cinput{file}", r"\begin x", r"\unknowncommand{x}"]
        for value in commands:
            with self.subTest(value=value):
                self.assert_bad_source(lambda book: book["protected"][2].update(value=value), "TeX|math")

    def test_safe_math_environment_and_code_whitespace_survive(self):
        self.source["protected"][2]["value"] = r"\begin{aligned} x &= \sqrt{2} \\ y &= \alpha + \mathrm{d}t \end{aligned}"
        self.write("book-source.json", self.source)
        core.seal_source(self.root)
        self.book["protected"] = copy.deepcopy(self.source["protected"])
        self.write("book.json", self.book)
        self.assertEqual(core.validate_book(self.root)["protected"][3]["value"], "# English comment\nvalue = 1\n\tprint(value)\n")

    def test_digest_changes_for_content_terms_layout_and_identity(self):
        original = core.content_digest(self.root)
        self.book["blocks"][0]["target"][1]["text"] = "Changed translated heading"
        self.write("book.json", self.book)
        self.assertNotEqual(original, core.content_digest(self.root))
        self.write("book.json", dict(self.book, title="Another title"))
        original = core.content_digest(self.root)
        self.terms["terms"][0]["rationale"] = "Revised authority decision"
        self.write("terms.json", self.terms)
        self.assertNotEqual(original, core.content_digest(self.root))
        original = core.content_digest(self.root)
        self.job["layout"]["outer_mm"] = 9
        self.write("job.json", self.job)
        self.assertNotEqual(original, core.content_digest(self.root))
        original = core.content_digest(self.root)
        self.job["source_language"] = "de"
        self.write("job.json", self.job)
        self.assertNotEqual(original, core.content_digest(self.root))

    def test_digest_includes_all_asset_bytes_not_just_references(self):
        original = core.content_digest(self.root)
        (self.root / "assets/unused.txt").write_text("Changed unused evidence", encoding="utf-8")
        self.assertNotEqual(original, core.content_digest(self.root))
        original = core.content_digest(self.root)
        (self.root / "assets/another.bin").write_bytes(b"New evidence")
        self.assertNotEqual(original, core.content_digest(self.root))

    def test_digest_excludes_mutable_review_and_generated_state(self):
        original = core.content_digest(self.root)
        self.job.update(state="approved", round=2, history=[{"event": "reviewed", "arbitrary": [1, "evidence"]}], max_rounds=4)
        self.write("job.json", self.job)
        (self.root / "reviews").mkdir()
        self.write("reviews/round-2.json", self.review())
        self.write("build/verification.json", {"content_digest": "stale", "passed": False})
        (self.root / "output.pdf").write_bytes(b"Generated PDF")
        self.assertEqual(original, core.content_digest(self.root))

    def test_digest_rejects_unused_asset_symlinks_escaping_job(self):
        outside = Path(self.temporary.name) / "secret"
        outside.write_bytes(b"private")
        (self.root / "assets/secret").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            core.content_digest(self.root)

    def test_json_roundtrip_and_canonical_digest_ignore_key_order(self):
        original = core.content_digest(self.root)
        self.write("book.json", dict(reversed(list(self.book.items()))))
        self.assertEqual(original, core.content_digest(self.root))
        self.assertEqual(core.load_json(self.root / "book.json"), self.book)

    def test_json_rejects_duplicate_keys_nonfinite_nonobject_and_invalid_utf8(self):
        path = self.root / "bad.json"
        for data in [b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": Infinity}', b'{"a": 1e999}', b'[]', b'{"a": "\xff"}', b'{broken']:
            path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                core.load_json(path)

    def test_save_rejects_nonfinite_without_overwriting_existing_document(self):
        for value in [{"value": float("nan")}, {"value": float("inf")}, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.save_json(self.root / "job.json", value)
            self.assertEqual(core.load_json(self.root / "job.json"), self.job)

    def test_programmatic_documents_reject_nonfinite_numbers(self):
        for value in [float("nan"), float("inf"), -float("inf")]:
            job = copy.deepcopy(self.job)
            job["layout"]["outer_mm"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "non-finite"):
                core.validate_document("job", job)

    def test_models_accept_explicit_ids_without_vendor_restrictions(self):
        for provider, model in [("anthropic", "claude-sonnet-4-6"), ("google", "gemini-2.5-pro"),
                                ("openai", "gpt-5.2"), ("openai-codex", "gpt-6.1-sol"),
                                ("opencode-go", "deepseek-v4-flash"), ("openrouter", "anthropic/claude-sonnet-4.6"),
                                ("custom-provider", "explicit-model"), ("local-provider", "Model-v1:latest")]:
            with self.subTest(provider=provider, model=model):
                self.assertEqual(core.admit_model(provider, model), f"{provider}/{model}")

    def test_models_reject_ambiguous_selector_syntax_not_provider_identity(self):
        for provider, model in [("openai", "auto"), ("google", "default"), ("custom-provider", "Default"),
                                ("openai", "auto:high"), ("openrouter", "openrouter/auto"), ("provider", "default@route"),
                                ("provider", "inherit"), ("provider", "parent"),
                                ("", ""), ("Anthropic", "claude"), ("anthropic ", "claude"),
                                ("*", "model"), ("provider/path", "model"), ("provider", "@task"),
                                ("provider", "*"), ("provider", "model,other"), ("provider", "model other"),
                                ("provider", "model\nother"), ("provider", "?model"), ("provider", "")]:
            with self.subTest(provider=provider, model=model), self.assertRaises(ValueError):
                core.admit_model(provider, model)


    def test_unassigned_models_allowed_but_partial_or_unsafe_rejected(self):
        job = copy.deepcopy(self.job)
        job["models"]["terminology"] = {"provider": "", "model": ""}
        core.validate_document("job", job)
        job["models"]["terminology"] = {"provider": "anthropic", "model": ""}
        with self.assertRaisesRegex(ValueError, "set together"):
            core.validate_document("job", job)
        job["models"]["terminology"] = {"provider": "openai", "model": "@task"}
        with self.assertRaises(ValueError):
            core.validate_document("job", job)

    def test_job_rounds_layout_and_history(self):
        job = copy.deepcopy(self.job)
        job["max_rounds"] = 5
        job["history"] = [{"stage": "initialized", "anything": [True, None]}]
        core.validate_document("job", job)
        for field, value in [("max_rounds", 0), ("round", 6), ("state", "invented")]:
            document = copy.deepcopy(job)
            document[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                core.validate_document("job", document)
        for field, value in [("paper", "letter"), ("outer_mm", 0), ("source_mark_edge_mm", 9), ("top_mm", 200), ("inner_min_mm", 150)]:
            document = copy.deepcopy(job)
            document["layout"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                core.validate_document("job", document)

    def test_job_horizontal_margins_leave_usable_width_without_compensation(self):
        job = copy.deepcopy(self.job)
        job["layout"]["inner_min_mm"] = 139
        core.validate_document("job", job)
        job["layout"]["inner_min_mm"] = 140
        with self.assertRaisesRegex(ValueError, "horizontal margins"):
            core.validate_document("job", job)

    @staticmethod
    def review():
        return {"version": 1, "round": 1, "content_digest": "a" * 64, "pdf_sha256": "b" * 64, "verdict": "pass", "checks": {name: True for name in ["coverage", "terminology", "protected_content", "source_pages", "image_relations", "footnotes", "typography", "preface"]}, "findings": [], "evidence": ["Inspected PDF pages 1-4 against manuscript blocks heading-related and source p1-p2"]}

    def test_passing_review_requires_every_check_and_no_findings(self):
        core.validate_document("review", self.review())
        for check in self.review()["checks"]:
            review = self.review()
            review["checks"][check] = False
            with self.subTest(check=check), self.assertRaises(ValueError):
                core.validate_document("review", review)
        review = self.review()
        review["findings"].append({"id": "issue", "severity": "minor", "location": "PDF page 2", "detail": "Fix spacing"})
        with self.assertRaises(ValueError):
            core.validate_document("review", review)
        review["verdict"] = "changes_requested"
        review["checks"]["typography"] = False
        core.validate_document("review", review)

    def test_review_requires_exact_checks_and_real_evidence(self):
        for key in self.review()["checks"]:
            review = self.review()
            del review["checks"][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                core.validate_document("review", review)
        for evidence in [[], [" "]]:
            review = self.review()
            review["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                core.validate_document("review", review)
        review = self.review()
        review["checks"]["extra"] = True
        with self.assertRaises(ValueError):
            core.validate_document("review", review)
        review = self.review()
        review["verdict"] = "changes_requested"
        finding = {"id": "duplicate", "severity": "blocking", "location": "PDF page 1", "detail": "Needs repair"}
        review["findings"] = [finding, copy.deepcopy(finding)]
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            core.validate_document("review", review)

    def test_review_requires_author_artifact_identities(self):
        for verdict in ["pass", "changes_requested"]:
            for field in ["content_digest", "pdf_sha256"]:
                for value in [None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, 1]:
                    review = self.review()
                    review["verdict"] = verdict
                    review[field] = value
                    with self.subTest(verdict=verdict, field=field, value=value), self.assertRaises(ValueError):
                        core.validate_document("review", review)
                review = self.review()
                review["verdict"] = verdict
                del review[field]
                with self.subTest(verdict=verdict, missing=field), self.assertRaises(ValueError):
                    core.validate_document("review", review)

    def test_unknown_document_kind_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unknown document kind"):
            core.validate_document("automatic", {})

    def test_module_and_schemas_work_when_copied_without_repository(self):
        standalone = Path(self.temporary.name) / "standalone"
        (standalone / "scripts").mkdir(parents=True)
        shutil.copyfile(SCRIPTS / "core.py", standalone / "scripts/core.py")
        shutil.copytree(SCRIPTS.parent / "contracts", standalone / "contracts")
        spec = importlib.util.spec_from_file_location("standalone_core", standalone / "scripts/core.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.validate_book(self.root), self.book)
        self.assertEqual(module.content_digest(self.root), core.content_digest(self.root))


if __name__ == "__main__":
    unittest.main()
