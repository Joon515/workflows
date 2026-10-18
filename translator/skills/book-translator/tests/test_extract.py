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
                    if mixed:
                        self.assertIn("Native selectable heading", page["text"])
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
