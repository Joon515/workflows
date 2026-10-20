"""Real tiny source fixtures; optional engines run only when installed locally."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract as extractor

import pymupdf as fitz


def make_pdf(path, scanned=False, mixed=False, image=False, rotated=False):
    with fitz.open() as document:
        page = document.new_page(width=600, height=400)
        if not scanned or mixed:
            page.insert_text((35, 45), "Native selectable heading", fontsize=18)
        if scanned:
            with fitz.open() as scan:
                scan_page = scan.new_page(width=560, height=180)
                scan_page.insert_text((30, 85), "SCANNED WORDS", fontsize=32)
                raster = scan_page.get_pixmap(dpi=180).tobytes("png")
            page.insert_image(fitz.Rect(20, 100, 580, 280), stream=raster)
        elif image:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 20), False)
            pixmap.clear_with(80)
            page.insert_image(fitz.Rect(30, 90, 150, 170), pixmap=pixmap)
        if rotated:
            page.set_rotation(90)
        document.save(path)


def make_font_pdf(path, rotation=0):
    with fitz.open() as document:
        page = document.new_page(width=360, height=240)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
        pixmap.clear_with(80)
        page.insert_image(fitz.Rect(300, 20, 330, 50), pixmap=pixmap)
        page.insert_text((40, 60), "Body ", fontsize=12, fontname="helv")
        continuation = 40 + fitz.get_text_length("Body ", fontsize=12, fontname="helv")
        page.insert_text((continuation, 60), "context", fontsize=12, fontname="tiit")
        page.insert_text((40, 75), "Second line", fontsize=12, fontname="helv")
        page.insert_text((40, 150), "Section heading", fontsize=21, fontname="tibo")
        page.set_rotation(rotation)
        document.save(path)



def make_epub(path, encrypted=False, missing=False):
    container = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    package = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book">test-book</dc:identifier><dc:title>Fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="picture" href="picture.png" media-type="image/png"/></manifest><spine><itemref idref="chapter"/></spine></package>'
    chapter = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Fixture</title></head><body><h1>EPUB Fixture</h1><p>Native EPUB text survives extraction.</p><img src="picture.png" alt="fixture image"/></body></html>'
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 12), False)
    pixmap.clear_with(120)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/package.opf", package)
        if not missing:
            archive.writestr("OPS/chapter.xhtml", chapter)
        archive.writestr("OPS/picture.png", pixmap.tobytes("png"))
        if encrypted:
            archive.writestr("META-INF/encryption.xml", '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#"><EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes256"/><CipherData><CipherReference URI="OPS/chapter.xhtml"/></CipherData></EncryptedData></encryption>')


def make_mobi(path, encrypted=False):
    # An uncompressed Palm database with a real MOBI header and one HTML record.
    html = b'<html><head><title>Tiny Book</title></head><body><h1>MOBI Fixture</h1><p>Native MOBI extraction evidence.</p></body></html>'
    header = bytearray(232)
    header[:4] = b"MOBI"
    struct.pack_into(">IIIIII", header, 4, 232, 2, 65001, 12345, 6, 0)
    for offset, value in [(0x40, 0xffffffff), (0x44, 248), (0x48, 9), (0x4c, 9), (0x6c, 0xffffffff), (0x70, 0xffffffff), (0x94, 0xffffffff)]:
        struct.pack_into(">I", header, offset, value)
    record = struct.pack(">HHIHHHH", 1, 0, len(html), 1, 4096, int(encrypted), 0) + header + b"Tiny Book"
    database = struct.pack(">32sHHIIIIII4s4sIIH", b"Tiny Book", 0, 0, 0, 0, 0, 0, 0, 0, b"BOOK", b"MOBI", 0, 0, 2)
    path.write_bytes(database + struct.pack(">II", 96, 0) + struct.pack(">II", 96 + len(record), 1) + b"\x00\x00" + record + html)


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dependencies = extractor.doctor()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = self.root / "job"

    def assert_evidence(self, output):
        self.assertEqual(output["version"], 1)
        original = self.job / output["input"]["path"]
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), output["input"]["sha256"])
        self.assertEqual(output, json.loads((self.job / "extraction.json").read_text(encoding="utf-8")))
        self.assertTrue(output["pages"])
        for number, page in enumerate(output["pages"], 1):
            self.assertEqual(page["id"], f"p{number:04d}")
            self.assertGreater(page["width"], 0)
            self.assertGreater(page["height"], 0)
            for candidate in page["printed_label_candidates"]:
                self.assertEqual(set(candidate), {"text", "evidence"})
                self.assertTrue(candidate["text"])
                self.assertTrue(candidate["evidence"])
            self.assertNotIn("printed_label", page)
            self.assertNotIn("label_verified", page)
            image = self.job / page["image"]
            self.assertTrue(image.is_file())
            self.assertGreater(fitz.Pixmap(str(image)).width, 0)
            for span in page["spans"] + page["ocr"]["spans"]:
                self.assertEqual(len(span["bbox"]), 4)
                self.assertIsInstance(span["text"], str)
            for asset in page["assets"]:
                self.assertTrue((self.job / asset["path"]).is_file())
        for asset in output["assets"]:
            self.assertTrue((self.job / asset["path"]).is_file())

    def assert_no_source_font(self, span):
        for key in ("font_size", "font_size_source", "font_size_unit", "origin"):
            self.assertIn(key, span)
            self.assertIsNone(span[key], key)



    def test_doctor_reports_actual_dependencies(self):
        self.assertTrue(self.dependencies["pymupdf"]["available"])
        self.assertEqual(self.dependencies["tools"]["ddjvu"], shutil.which("ddjvu"))
        self.assertEqual(self.dependencies["djvu"]["available"], bool(shutil.which("ddjvu")))
        if not self.dependencies["ocr"]["available"]:
            self.assertTrue(self.dependencies["ocr"]["error"])

    def test_pdf_keeps_native_text_spans_and_full_render(self):
        source = self.root / "native.pdf"
        make_pdf(source)
        output = extractor.extract(source, self.job, dpi=100)
        self.assert_evidence(output)
        page = output["pages"][0]
        self.assertIn("Native selectable heading", page["text"])
        self.assertTrue(page["spans"])
        self.assertFalse(page["ocr"]["needed"])
        self.assertFalse(page["ocr"]["performed"])
        self.assertEqual(page["locator"], "page:1")

    def test_native_pdf_font_em_baselines_and_context_keep_source_identity(self):
        for rotation in (0, 90):
            with self.subTest(rotation=rotation):
                source = self.root / f"font-evidence-{rotation}.pdf"
                make_font_pdf(source, rotation)
                original_bytes = source.read_bytes()
                job = self.job / str(rotation)
                output = extractor.extract(source, job, ocr="never", dpi=72)
                page = output["pages"][0]
                self.assertEqual(output["input"]["sha256"], hashlib.sha256(original_bytes).hexdigest())
                self.assertEqual((job / output["input"]["path"]).read_bytes(), original_bytes)
                self.assertEqual(source.read_bytes(), original_bytes)
                self.assertEqual(page["locator"], "page:1")
                self.assertEqual(output, json.loads((job / "extraction.json").read_text(encoding="utf-8")))
                self.assertIn("Second line", page["text"])
                self.assertTrue(page["assets"])
                self.assertTrue(any(span["line_index"] > 0 for span in page["spans"]))
                expected_sizes = {"Body": 12, "context": 12, "Second line": 12, "Section heading": 21}
                self.assertEqual({span["text"].strip() for span in page["spans"]}, set(expected_sizes))
                with fitz.open(source) as original:
                    native_page = original[0]
                    data = native_page.get_text("dict", flags=fitz.TEXTFLAGS_DICT | fitz.TEXT_PRESERVE_IMAGES)
                    self.assertEqual(page["text"], native_page.get_text("text"))
                    for span in page["spans"]:
                        block = data["blocks"][span["block_index"]]
                        line = block["lines"][span["line_index"]]
                        native = line["spans"][span["span_index"]]
                        self.assertEqual(span["text"], native["text"])
                        self.assertEqual(span["font_size"], expected_sizes[span["text"].strip()])
                        self.assertEqual(span["font_size"], native["size"])
                        self.assertEqual(span["font_name"], native["font"])
                        self.assertEqual(span["font_size_source"], "native_pdf")
                        self.assertEqual(span["font_size_unit"], "pt")
                        self.assertEqual(span["bbox"], list(fitz.Rect(native["bbox"]) * native_page.rotation_matrix))
                        self.assertEqual(span["line_bbox"], list(fitz.Rect(line["bbox"]) * native_page.rotation_matrix))
                        self.assertEqual(span["origin"], list(fitz.Point(native["origin"]) * native_page.rotation_matrix))
                        self.assertEqual(span["line_wmode"], line["wmode"])
                        self.assertEqual(span["line_direction"], [0.0, 1.0] if rotation else [1.0, 0.0])
                body = next(span for span in page["spans"] if span["text"].strip() == "Body")
                context = next(span for span in page["spans"] if span["text"] == "context")
                self.assertEqual((body["block_index"], body["line_index"]), (context["block_index"], context["line_index"]))
                self.assertNotEqual(body["span_index"], context["span_index"])
                if not rotation:
                    self.assertEqual(body["origin"], [40.0, 60.0])
                    self.assertNotAlmostEqual(body["bbox"][3] - body["bbox"][1], 12, places=3)
                    self.assertNotAlmostEqual(body["bbox"][3] - body["bbox"][1], context["bbox"][3] - context["bbox"][1], places=3)
                higher_dpi = extractor.extract(source, job / "higher-dpi", ocr="never", dpi=144)
                self.assertEqual(higher_dpi["pages"][0]["spans"], page["spans"])
                self.assertEqual(higher_dpi["input"], output["input"])

    def test_unavailable_or_invalid_font_measurements_are_not_derived_from_boxes(self):
        with fitz.open() as document:
            page = document.new_page()
            for size in (None, 0, -1, float("nan"), float("inf"), True, "12"):
                with self.subTest(size=size):
                    native = {"text": "Unmeasured text", "bbox": [10, 20, 110, 45], "origin": None}
                    if size is not None:
                        native["size"] = size
                    data = {"blocks": [{"type": 0, "lines": [{"spans": [native]}]}]}
                    span = extractor._spans(fitz, page, data, "native_pdf")[0]
                    self.assertEqual(span["text"], native["text"])
                    self.assertEqual(span["bbox"], native["bbox"])
                    self.assert_no_source_font(span)
                    for key in ("font_name", "line_bbox", "line_direction", "line_wmode"):
                        self.assertIsNone(span[key])

    def test_ocr_span_metrics_are_not_calibration_for_any_extraction_channel(self):
        with fitz.open() as document:
            page = document.new_page()
            for font_source in (None, "native_pdf", "reflow_layout"):
                for font_name in ("GlyphLessFont", "ABCDEF+GlyphLessFont"):
                    with self.subTest(font_source=font_source, font_name=font_name):
                        native = {"text": "OCR words", "bbox": [10, 20, 110, 45], "size": 24, "font": font_name, "origin": [10, 40]}
                        line = {"bbox": native["bbox"], "dir": [1, 0], "wmode": 0, "spans": [native]}
                        data = {"blocks": [{"type": 0, "lines": [line]}]}
                        span = extractor._spans(fitz, page, data, font_source)[0]
                        self.assert_no_source_font(span)
                        self.assertEqual(span["font_name"], font_name if font_source else None)
                        self.assertEqual(span["text"], native["text"])
                        self.assertEqual(span["bbox"], native["bbox"])
                        self.assertEqual(span["line_bbox"], line["bbox"])
                        self.assertEqual(span["line_direction"], line["dir"])
                        self.assertEqual((span["block_index"], span["line_index"], span["span_index"]), (0, 0, 0))


    def test_generated_native_ocr_layer_keeps_synthetic_calibration_missing(self):
        if not self.dependencies["ocr"]["available"] or "eng" not in self.dependencies["ocr"]["languages"]:
            self.skipTest("Native OCR-layer fixture requires the installed embedded OCR engine and English data")
        source = self.root / "ocr-layer.pdf"
        with fitz.open() as document:
            page = document.new_page(width=360, height=100)
            page.insert_text((20, 60), "SYNTHETIC OCR LAYER", fontsize=22)
            pixmap = page.get_pixmap(dpi=150, alpha=False)
            source.write_bytes(pixmap.pdfocr_tobytes(language="eng", tessdata=self.dependencies["ocr"]["tessdata"]))
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        self.assertIn("SYNTHETIC OCR LAYER", output["pages"][0]["text"])
        for span in output["pages"][0]["spans"]:
            self.assertIn("GlyphLessFont", span["font_name"])
            self.assert_no_source_font(span)

    def test_existing_extract_cli_saves_native_font_evidence(self):
        source = self.root / "cli-font-evidence.pdf"
        make_font_pdf(source)
        cli = Path(extractor.__file__).with_name("translator.py")
        initialized = subprocess.run([sys.executable, str(cli), "init", str(source), str(self.job), "--source-language", "en", "--target-language", "zh-CN"], capture_output=True, text=True, timeout=60)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(json.loads(initialized.stdout)["state"], "initialized")
        for role in ("source", "terminology", "translation", "review"):
            configured = subprocess.run([sys.executable, str(cli), "configure-model", str(self.job), role, "--provider", "openai", "--model", "gpt-5.2"], capture_output=True, text=True, timeout=60)
            self.assertEqual(configured.returncode, 0, configured.stderr)
        extracted = subprocess.run([sys.executable, str(cli), "extract", str(self.job), "--ocr", "never", "--dpi", "72"], capture_output=True, text=True, timeout=60)
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        output = json.loads(extracted.stdout)
        self.assert_evidence(output)
        self.assertEqual({span["font_size"] for span in output["pages"][0]["spans"]}, {12.0, 21.0})
        self.assertTrue(all(span["font_size_source"] == "native_pdf" for span in output["pages"][0]["spans"]))
        job = json.loads((self.job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual((job["state"], job["round"]), ("extracted", 0))


    def test_margin_labels_are_candidates_not_approved_pagination(self):
        source = self.root / "page-labels.pdf"
        labels = ["xii", "A-7", "12"]
        with fitz.open() as document:
            for label in labels:
                page = document.new_page(width=420, height=595)
                page.insert_text((35, 250), "xii", fontsize=12)
                page.insert_text((200, 570), label, fontsize=12)
            document.save(source)
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        for page, expected in zip(output["pages"], labels):
            self.assertEqual([item["text"] for item in page["printed_label_candidates"]], [expected])
            evidence = page["printed_label_candidates"][0]["evidence"]
            self.assertTrue(evidence.startswith(page["image"] + "#native-span-bbox="))
            self.assertIn("unverified", evidence)

    def test_source_already_inside_job_is_reused(self):
        source = self.job / "evidence" / "source.pdf"
        source.parent.mkdir(parents=True)
        make_pdf(source)
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        self.assertEqual(output["input"]["path"], "evidence/source.pdf")

    def test_images_and_native_text_both_survive(self):
        source = self.root / "image.pdf"
        make_pdf(source, image=True, rotated=True)
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        page = output["pages"][0]
        self.assertTrue(output["assets"])
        self.assertTrue(page["assets"])
        self.assertEqual((page["width"], page["height"]), (400, 600))
        self.assertTrue(page["ocr"]["needed"])
        self.assertTrue(page["image_regions"])
        self.assertIn("Native selectable heading", page["text"])
        self.assertIsNone(page["ocr"]["engine"])

    def test_scan_never_retains_unrecognized_evidence(self):
        source = self.root / "scan.pdf"
        make_pdf(source, scanned=True)
        output = extractor.extract(source, self.job, ocr="never", dpi=100)
        self.assert_evidence(output)
        page = output["pages"][0]
        self.assertEqual(page["text"], "")
        self.assertTrue(page["ocr"]["needed"])
        self.assertFalse(page["ocr"]["performed"])
        self.assertTrue(any("explicitly skipped" in warning for warning in output["warnings"]))

    def test_auto_scan_and_mixed_pages_use_actual_ocr_or_fail_actionably(self):
        available = self.dependencies["ocr"]["available"] and "eng" in self.dependencies["ocr"]["languages"]
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                source = self.root / f"scan-{mixed}.pdf"
                job = self.job / str(mixed)
                make_pdf(source, scanned=True, mixed=mixed)
                if not available:
                    with self.assertRaisesRegex(RuntimeError, "TESSDATA_PREFIX|OCR failed"):
                        extractor.extract(source, job, ocr="auto", dpi=150)
                    self.assertFalse((job / "extraction.json").exists())
                else:
                    output = extractor.extract(source, job, ocr="auto", dpi=150)
                    page = output["pages"][0]
                    self.assertTrue(page["ocr"]["needed"])
                    self.assertTrue(page["ocr"]["performed"])
                    self.assertIn("SCANNED WORDS", page["ocr"]["text"])
                    self.assertTrue(page["ocr"]["spans"])
                    for span in page["ocr"]["spans"]:
                        self.assert_no_source_font(span)
                        self.assertIsNone(span["font_name"])
                    if mixed:
                        self.assertIn("Native selectable heading", page["text"])
                        self.assertTrue(all(span["font_size_source"] == "native_pdf" for span in page["spans"]))
                        self.assertNotIn("SCANNED WORDS", page["text"])

    def test_always_requests_ocr_even_with_selectable_text(self):
        source = self.root / "always.pdf"
        make_pdf(source)
        if not self.dependencies["ocr"]["available"] or "eng" not in self.dependencies["ocr"]["languages"]:
            with self.assertRaisesRegex(RuntimeError, "TESSDATA_PREFIX|OCR failed"):
                extractor.extract(source, self.job, ocr="always", dpi=150)
        else:
            output = extractor.extract(source, self.job, ocr="always", dpi=150)
            self.assert_evidence(output)
            page = output["pages"][0]
            self.assertFalse(page["ocr"]["needed"])
            self.assertTrue(page["ocr"]["performed"])
            self.assertIn("Native selectable heading", page["ocr"]["text"])
            for span in page["ocr"]["spans"]:
                self.assert_no_source_font(span)

    def test_blank_page_does_not_need_auto_ocr(self):
        source = self.root / "blank.pdf"
        with fitz.open() as document:
            document.new_page(width=100, height=100)
            document.save(source)
        output = extractor.extract(source, self.job, dpi=72)
        self.assertFalse(output["pages"][0]["ocr"]["needed"])

    def test_epub_renders_virtual_pages_and_preserves_archive_images(self):
        source = self.root / "source.epub"
        make_epub(source)
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        self.assertTrue(output["pages"][0]["locator"].startswith("virtual:chapter:"))
        self.assertIn("Native EPUB text", "".join(page["text"] for page in output["pages"]))
        self.assertTrue(any(asset["source"] == "epub:OPS/picture.png" for asset in output["assets"]))
        self.assertTrue(any("not original printed" in warning for warning in output["warnings"]))
        native_spans = [span for page in output["pages"] for span in page["spans"]]
        self.assertTrue(native_spans)
        self.assertTrue(all(span["font_size_source"] == "reflow_layout" for span in native_spans))
        self.assertTrue(zipfile.is_zipfile(self.job / output["input"]["path"]))

    def test_mobi_uses_real_native_decoder(self):
        source = self.root / "source.mobi"
        make_mobi(source)
        output = extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assert_evidence(output)
        self.assertIn("Native MOBI extraction evidence.", "".join(page["text"] for page in output["pages"]))
        self.assertTrue(output["pages"][0]["locator"].startswith("virtual:chapter:"))

    def test_drm_inputs_are_rejected(self):
        epub = self.root / "encrypted.epub"
        make_epub(epub, encrypted=True)
        with self.assertRaisesRegex(ValueError, "encrypted|DRM"):
            extractor.extract(epub, self.job / "epub", ocr="never", dpi=72)
        mobi = self.root / "encrypted.mobi"
        make_mobi(mobi, encrypted=True)
        with self.assertRaisesRegex(ValueError, "encrypted|DRM"):
            extractor.extract(mobi, self.job / "mobi", ocr="never", dpi=72)
        pdf = self.root / "encrypted.pdf"
        with fitz.open() as document:
            document.new_page()
            document.save(pdf, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
        with self.assertRaisesRegex(ValueError, "encrypted|password"):
            extractor.extract(pdf, self.job / "pdf", ocr="never", dpi=72)

    def test_corrupt_and_incomplete_inputs_fail_without_success_artifact(self):
        for extension in ("pdf", "epub", "mobi"):
            with self.subTest(extension=extension):
                source = self.root / f"broken.{extension}"
                source.write_bytes(b"This is not a book container.")
                job = self.job / extension
                with self.assertRaises((ValueError, RuntimeError)):
                    extractor.extract(source, job, ocr="never", dpi=72)
                self.assertFalse((job / "extraction.json").exists())
        source = self.root / "incomplete.epub"
        make_epub(source, missing=True)
        with self.assertRaisesRegex(ValueError, "missing"):
            extractor.extract(source, self.job / "incomplete", ocr="never", dpi=72)

    def test_corrupt_pdf_content_stream_is_not_silently_accepted(self):
        source = self.root / "bad-stream.pdf"
        with fitz.open() as document:
            page = document.new_page(width=200, height=100)
            page.insert_text((10, 50), "Corrupt stream fixture")
            content = page.get_contents()[0]
            document.update_stream(content, b"invalid compressed stream", compress=False)
            document.xref_set_key(content, "Filter", "/FlateDecode")
            document.save(source)
        with self.assertRaisesRegex(ValueError, "corrupt|unsupported"):
            extractor.extract(source, self.job, ocr="never", dpi=72)
        self.assertFalse((self.job / "extraction.json").exists())

    def test_djvu_dependency_failure_is_explicit(self):
        if shutil.which("ddjvu"):
            self.skipTest("ddjvu exists; actual DjVu decoding is exercised separately")
        source = self.root / "source.djvu"
        source.write_bytes(b"AT&TFORM\x00\x00\x00\x04DJVU")
        with self.assertRaisesRegex(RuntimeError, "ddjvu.*DjVuLibre"):
            extractor.extract(source, self.job, ocr="never", dpi=72)

    def test_djvu_word_coordinates_do_not_invent_font_calibration(self):
        raw = b'(page 0 0 600 400 (line 20 50 200 100 (word 20 50 90 100 "Native") (word 100 50 200 100 "words")))\n'
        directory = self.job / "evidence"
        directory.mkdir(parents=True)
        evidence = extractor._Evidence(self.job, directory)
        with patch.object(extractor, "_run", return_value=raw):
            text, spans, saved = extractor._djvu_text("djvutxt", self.root / "source.djvu", 1, 300, 200, evidence)
        self.assertEqual(text, "Native words")
        self.assertEqual((self.job / saved).read_bytes(), raw)
        self.assertEqual(spans[0]["bbox"], [10.0, 150.0, 45.0, 175.0])
        for span in spans:
            self.assert_no_source_font(span)
            for key in ("font_name", "block_index", "line_index", "span_index", "line_bbox", "line_direction", "line_wmode"):
                self.assertIsNone(span[key])


    def test_actual_djvu_decoder_when_encoder_is_available(self):
        decoder, encoder = shutil.which("ddjvu"), shutil.which("c44")
        if not decoder or not encoder:
            self.skipTest("Actual DjVu fixture requires local DjVuLibre ddjvu and c44; neither dependency is downloaded by tests")
        ppm = self.root / "scan.ppm"
        with fitz.open() as document:
            page = document.new_page(width=300, height=150)
            page.insert_text((20, 70), "DJVU SCAN", fontsize=28)
            page.get_pixmap(dpi=100).save(str(ppm))
        source = self.root / "source.djvu"
        subprocess.run([encoder, str(ppm), str(source)], check=True, capture_output=True)
        output = extractor.extract(source, self.job, ocr="never", dpi=100)
        self.assert_evidence(output)
        self.assertEqual(output["input"]["format"], "djvu")
        self.assertTrue(output["pages"][0]["ocr"]["needed"])
        if self.dependencies["ocr"]["available"] and "eng" in self.dependencies["ocr"]["languages"]:
            ocr_output = extractor.extract(source, self.job, ocr="auto", dpi=150)
            self.assertIn("DJVU SCAN", ocr_output["pages"][0]["ocr"]["text"])
        editor = shutil.which("djvused")
        if editor and shutil.which("djvutxt"):
            text_file = self.root / "hidden-text.txt"
            text_file.write_text('(page 0 0 417 209 (line 20 80 300 130 (word 20 80 150 130 "DJVU") (word 160 80 300 130 "SCAN")))\n', encoding="utf-8")
            subprocess.run([editor, str(source), "-e", f"select 1; set-txt {text_file}; save"], check=True, capture_output=True)
            native_output = extractor.extract(source, self.job / "hidden", ocr="never", dpi=100)
            native_page = native_output["pages"][0]
            self.assertEqual(native_page["text"], "DJVU SCAN")
            self.assertEqual(len(native_page["spans"]), 2)
            self.assertTrue((self.job / "hidden" / native_page["native_text_evidence"]).is_file())
            self.assertGreater(native_page["spans"][0]["bbox"][1], 0)
            for span in native_page["spans"]:
                self.assert_no_source_font(span)
                self.assertIsNone(span["font_name"])
                self.assertIsNone(span["block_index"])
                self.assertIsNone(span["line_index"])

    def test_invalid_policy_and_source_formats_fail(self):
        source = self.root / "source.pdf"
        make_pdf(source)
        with self.assertRaisesRegex(ValueError, "policy"):
            extractor.extract(source, self.job, ocr="sometimes")
        with self.assertRaisesRegex(ValueError, "DPI"):
            extractor.extract(source, self.job, dpi=0)
        with self.assertRaisesRegex(ValueError, "language"):
            extractor.extract(source, self.job, language="../eng")
        other = self.root / "source.txt"
        other.write_text("not a supported book", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported source format"):
            extractor.extract(other, self.job)


if __name__ == "__main__":
    unittest.main()
