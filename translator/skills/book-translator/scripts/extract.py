"""Extract reviewable source evidence without approving text or pagination."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import struct
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


_FORMATS = {".pdf": "pdf", ".epub": "epub", ".mobi": "mobi", ".djvu": "djvu", ".djv": "djvu"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg", ".jp2"}


def _fitz():
    try:
        return importlib.import_module("pymupdf")
    except ImportError as exc:
        raise RuntimeError("Source extraction requires PyMuPDF in this Python environment. Install the pymupdf package locally, then run doctor again.") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tessdata(fitz):
    explicit = os.environ.get("TESSDATA_PREFIX")
    if explicit:
        candidates = [Path(explicit)]
    else:
        candidates = []
        try:
            candidates.append(Path(fitz.get_tessdata()))
        except (AttributeError, RuntimeError):
            pass
        candidates.extend([Path("/usr/share/tessdata"), Path("/usr/local/share/tessdata"), Path("/usr/local/share/tesseract-ocr/tessdata"), Path("/opt/homebrew/share/tessdata")])
        candidates.extend(sorted(Path("/usr/share/tesseract-ocr").glob("*/tessdata")))
    for directory in candidates:
        if directory.is_dir():
            languages = sorted(file.stem for file in directory.glob("*.traineddata") if file.is_file())
            if languages:
                return directory, languages
    return None, []


def _ocr_configuration(fitz, language: str):
    directory, languages = _tessdata(fitz)
    requested = language.split("+")
    missing = [name for name in requested if name not in languages]
    if directory is None or missing:
        names = ", ".join(missing or requested)
        raise RuntimeError(f"OCR requires Tesseract language data ({names}). Provide matching .traineddata files in a local directory and set TESSDATA_PREFIX to that directory. PyMuPDF uses its embedded Tesseract engine; the tesseract CLI is not required. Use ocr='never' only to retain unrecognized evidence for explicit manual transcription.")
    return directory


def doctor() -> dict:
    """Report installed dependencies; OCR availability is a real engine probe."""
    tools = {name: shutil.which(name) for name in ("ddjvu", "djvutxt", "c44", "cjb2", "tesseract")}
    result = {"python": os.sys.version.split()[0], "tools": tools, "pymupdf": {"available": False}, "ocr": {"available": False, "engine": "PyMuPDF/Tesseract", "tessdata": None, "languages": []}, "djvu": {"available": bool(tools["ddjvu"]), "decoder": tools["ddjvu"], "text_decoder": tools["djvutxt"]}}
    try:
        fitz = _fitz()
        result["pymupdf"] = {"available": True, "version": fitz.VersionBind, "native_formats": ["pdf", "epub", "mobi"]}
        directory, languages = _tessdata(fitz)
        result["ocr"].update(tessdata=str(directory) if directory else None, languages=languages)
        if directory is None:
            result["ocr"]["error"] = "No Tesseract .traineddata files found. Set TESSDATA_PREFIX to a local tessdata directory; a missing CLI alone does not disable embedded OCR."
        else:
            language = "eng" if "eng" in languages else languages[0]
            with fitz.open() as document:
                page = document.new_page(width=160, height=60)
                page.insert_text((10, 35), "OCR PROBE", fontsize=16)
                textpage = page.get_textpage_ocr(language=language, dpi=150, full=True, tessdata=str(directory))
                text = page.get_text("text", textpage=textpage)
                if not text.strip():
                    raise RuntimeError("Embedded OCR returned no text for its visible probe.")
            result["ocr"]["available"] = True
            result["ocr"]["probe_language"] = language
    except Exception as exc:
        if not result["pymupdf"]["available"]:
            result["pymupdf"]["error"] = str(exc)
        else:
            result["ocr"]["error"] = str(exc)
    if not tools["ddjvu"]:
        result["djvu"]["error"] = "DjVu extraction requires the ddjvu decoder from DjVuLibre. djvutxt is also recommended for original hidden text. No decoder is substituted or downloaded."
    return result


class _Evidence:
    def __init__(self, job_dir: Path, directory: Path):
        self.job_dir = job_dir
        self.directory = directory
        self.assets = []
        self._images = {}

    def relative(self, path: Path) -> str:
        return path.relative_to(self.job_dir).as_posix()

    def image(self, data: bytes, extension: str, source: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._images:
            return self._images[digest]
        extension = extension.lower().lstrip(".")
        if not re.fullmatch(r"[a-z0-9]{1,8}", extension):
            extension = "bin"
        path = self.directory / f"asset-{len(self.assets) + 1:04d}.{extension}"
        path.write_bytes(data)
        relative = self.relative(path)
        self.assets.append({"path": relative, "source": source, "kind": "embedded_image"})
        self._images[digest] = relative
        return relative


def _zip_member(base: str, href: str) -> str:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"EPUB resource is external, not self-contained: {href}")
    name = posixpath.normpath(posixpath.join(base, unquote(parsed.path)))
    if name.startswith(("/", "../")) or name == ".." or "\\" in name:
        raise ValueError(f"EPUB contains an unsafe resource path: {href}")
    return name


def _epub_preflight(source: Path, evidence: _Evidence):
    try:
        with zipfile.ZipFile(source) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"EPUB has a corrupt archive member: {bad}")
            if archive.read("mimetype").strip() != b"application/epub+zip":
                raise ValueError("EPUB mimetype is missing or invalid.")
            if "META-INF/encryption.xml" in archive.namelist():
                encryption = ET.fromstring(archive.read("META-INF/encryption.xml"))
                if any(node.tag.rsplit("}", 1)[-1] == "EncryptedData" for node in encryption.iter()):
                    raise ValueError("EPUB contains encrypted resources (DRM or font obfuscation). Supply an authorized unencrypted edition; extraction does not decrypt resources.")
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            roots = [node.attrib.get("full-path") for node in container.iter() if node.tag.rsplit("}", 1)[-1] == "rootfile"]
            if not roots or not roots[0]:
                raise ValueError("EPUB container has no package document.")
            package_name = _zip_member("", roots[0])
            package = ET.fromstring(archive.read(package_name))
            manifest = {}
            for item in package.iter():
                if item.tag.rsplit("}", 1)[-1] != "item":
                    continue
                href = item.attrib.get("href")
                if not href:
                    raise ValueError("EPUB manifest item is missing its resource path.")
                name = _zip_member(posixpath.dirname(package_name), href)
                if name not in archive.namelist():
                    raise ValueError(f"EPUB resource is missing: {name}")
                manifest[item.attrib.get("id")] = name
                if item.attrib.get("media-type", "").startswith("image/") or Path(name).suffix.lower() in _IMAGE_EXTENSIONS:
                    evidence.image(archive.read(name), Path(name).suffix, f"epub:{name}")
            spine = [item.attrib.get("idref") for item in package.iter() if item.tag.rsplit("}", 1)[-1] == "itemref"]
            if not spine or any(reference not in manifest for reference in spine):
                raise ValueError("EPUB spine is empty or references a missing manifest item.")
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"Cannot read EPUB archive/package; input is corrupt or unsupported: {exc}") from exc


def _mobi_preflight(source: Path):
    with source.open("rb") as stream:
        header = stream.read(78)
        if len(header) != 78 or header[60:68] != b"BOOKMOBI":
            raise ValueError("MOBI input has no valid Palm database / BOOKMOBI header.")
        count = struct.unpack_from(">H", header, 76)[0]
        records = stream.read(count * 8)
        if not count or len(records) != count * 8:
            raise ValueError("MOBI record table is empty or truncated.")
        offsets = [struct.unpack_from(">I", records, index * 8)[0] for index in range(count)]
        if offsets[0] < 78 + count * 8 or offsets[-1] >= source.stat().st_size or any(a >= b for a, b in zip(offsets, offsets[1:])):
            raise ValueError("MOBI record offsets are invalid or truncated.")
        stream.seek(offsets[0])
        palmdoc = stream.read(16)
        if len(palmdoc) != 16:
            raise ValueError("MOBI PalmDOC header is truncated.")
        if struct.unpack_from(">H", palmdoc, 12)[0]:
            raise ValueError("MOBI is encrypted/DRM protected. Supply an authorized unencrypted edition; extraction does not remove DRM.")


def _run(arguments: list[str]):
    try:
        process = subprocess.run(arguments, capture_output=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"Cannot execute {arguments[0]}: {exc}") from exc
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{Path(arguments[0]).name} failed ({process.returncode}): {detail or 'decoder reported no diagnostic'}. Check that the source is valid and unencrypted.")
    return process.stdout


def _djvu_text(tool: str, source: Path, number: int, width: float, height: float, evidence: _Evidence):
    raw = _run([tool, f"--page={number}", "--detail=word", str(source)])
    path = evidence.directory / f"p{number:04d}-djvutxt.txt"
    path.write_bytes(raw)
    content = raw.decode("utf-8", errors="strict")
    root = re.search(r"\(page\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)", content)
    if not content.strip() or content.strip() == "()":
        return "", [], evidence.relative(path)
    if not root:
        raise ValueError(f"djvutxt page {number} did not return a structured page with coordinates.")
    x0, y0, x1, y1 = map(int, root.groups())
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"djvutxt page {number} has invalid dimensions.")
    spans = []
    pattern = r'\(word\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+("(?:\\.|[^"\\])*")\s*\)'
    for match in re.finditer(pattern, content):
        left, bottom, right, top = map(int, match.groups()[:4])
        text = ast.literal_eval(match.group(5))
        spans.append({"text": text, "bbox": [(left - x0) * width / (x1 - x0), (y1 - top) * height / (y1 - y0), (right - x0) * width / (x1 - x0), (y1 - bottom) * height / (y1 - y0)]})
    # Preserve the exact structured output as evidence; this joined text is not a reviewed reading order.
    return " ".join(span["text"] for span in spans), spans, evidence.relative(path)


def _bbox(fitz, page, values):
    rectangle = fitz.Rect(values) * page.rotation_matrix
    return [float(value) for value in rectangle]


def _spans(fitz, page, data):
    return [{"text": span["text"], "bbox": _bbox(fitz, page, span["bbox"])} for block in data["blocks"] if block["type"] == 0 for line in block["lines"] for span in line["spans"]]


def _label_candidates(page):
    if page["locator"].startswith("virtual:"):
        return []
    roman = re.compile(r"(?=[MDCLXVI]+$)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})", re.IGNORECASE)
    numbered = re.compile(r"(?:[A-Za-z]{1,6}[-.])?[0-9]{1,6}")
    candidates, seen = [], set()
    for origin, spans in (("native", page["spans"]), ("ocr", page["ocr"]["spans"])):
        for span in spans:
            text = span["text"].strip()
            if not (numbered.fullmatch(text) or roman.fullmatch(text)):
                continue
            left, top, right, bottom = span["bbox"]
            if not (bottom <= page["height"] * 0.15 or top >= page["height"] * 0.85 or right <= page["width"] * 0.06 or left >= page["width"] * 0.94):
                continue
            if text not in seen:
                evidence = f"{page['image']}#{origin}-span-bbox={json.dumps(span['bbox'])}; unverified printed-label candidate"
                candidates.append({"text": text, "evidence": evidence})
                seen.add(text)
    return candidates


def _native_page(fitz, document, page, number: int, evidence: _Evidence, reflowable: bool, policy: str, language: str, dpi: int, tessdata):
    identifier = f"p{number:04d}"
    flags = fitz.TEXTFLAGS_DICT | fitz.TEXT_PRESERVE_IMAGES
    data = page.get_text("dict", flags=flags)
    text = page.get_text("text")
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    image_path = evidence.directory / f"{identifier}.png"
    pixmap.save(str(image_path))
    spans = _spans(fitz, page, data)
    assets, regions = [], []
    for block in data["blocks"]:
        if block["type"] != 1:
            continue
        box = _bbox(fitz, page, block["bbox"])
        asset = evidence.image(block["image"], block.get("ext", "png"), f"{identifier}:embedded-image")
        assets.append({"path": asset, "bbox": box, "source": f"{identifier}:embedded-image"})
        if block.get("mask"):
            evidence.image(block["mask"], "png", f"{identifier}:image-mask")
        # Do not infer that selectable text elsewhere (or over this image) covers raster text.
        regions.append({"bbox": box, "ocr_needed": True, "reason": "Raster image may contain text not represented by native spans; requires OCR or manual review."})
    if document.is_pdf:
        for image in page.get_images(full=True):
            for xref in (image[0], image[1]):
                if not xref:
                    continue
                original = document.extract_image(xref)
                if not original or "image" not in original:
                    raise ValueError(f"Cannot preserve embedded PDF image xref {xref} on {identifier}.")
                evidence.image(original["image"], original["ext"], f"pdf:xref:{xref}")
    dominant, color = pixmap.color_topusage()
    has_marks = dominant < 1.0 or any(component < 250 for component in color)
    needed = bool(regions) or "\ufffd" in text or (not text.strip() and has_marks)
    if reflowable:
        chapter, chapter_page = document.location_from_page_number(number - 1)
        locator = f"virtual:chapter:{chapter}:page:{chapter_page}"
    else:
        locator = f"page:{number}"
    result = {"id": identifier, "locator": locator, "width": float(page.rect.width), "height": float(page.rect.height), "image": evidence.relative(image_path), "text": text, "spans": spans, "printed_label_candidates": [], "assets": assets, "image_regions": regions, "ocr": {"needed": needed, "performed": False, "engine": None, "language": language, "text": "", "spans": []}}
    if policy == "always" or (policy == "auto" and needed):
        directory = tessdata or _ocr_configuration(fitz, language)
        try:
            # Full-page OCR remains distinct from native text and also covers mixed pages.
            textpage = page.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=str(directory))
            ocr_data = page.get_text("dict", textpage=textpage)
            result["ocr"].update(performed=True, engine="PyMuPDF/Tesseract", text=page.get_text("text", textpage=textpage), spans=_spans(fitz, page, ocr_data))
        except Exception as exc:
            raise RuntimeError(f"OCR failed on {identifier} ({language}). Verify the PyMuPDF OCR build and matching TESSDATA_PREFIX language files: {exc}") from exc
    return result


def _check_native_warnings(fitz, warnings: list[str]):
    diagnostic = fitz.TOOLS.mupdf_warnings(reset=True).strip()
    if not diagnostic:
        return
    if re.search(r"error|cannot|corrupt|invalid|syntax|repair|unexpected|premature|zlib|truncated|broken", diagnostic, re.IGNORECASE):
        raise ValueError(f"MuPDF reported corrupt or unsupported source data: {diagnostic}")
    warnings.append(f"MuPDF diagnostic requiring source review: {diagnostic}")


def extract(source: Path, job_dir: Path, ocr: str = "auto", language: str = "eng", dpi: int = 200) -> dict:
    """Write complete extraction evidence, or raise without publishing a result."""
    source, job_dir = Path(source).resolve(), Path(job_dir).resolve()
    if ocr not in {"auto", "always", "never"}:
        raise ValueError("OCR policy must be auto, always, or never.")
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi <= 0:
        raise ValueError("Extraction DPI must be a positive integer.")
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", language):
        raise ValueError("OCR language must be Tesseract language codes joined by '+', for example eng or eng+deu.")
    if not source.is_file():
        raise ValueError(f"Source file does not exist: {source}")
    source_format = _FORMATS.get(source.suffix.lower())
    if source_format is None:
        raise ValueError("Unsupported source format. Supply PDF, EPUB, MOBI, or DjVu.")
    fitz = _fitz()
    tools = {name: shutil.which(name) for name in ("ddjvu", "djvutxt")}
    if source_format == "djvu" and not tools["ddjvu"]:
        raise RuntimeError("DjVu extraction requires ddjvu from DjVuLibre; it is not installed. Provide that real decoder (and djvutxt for hidden text), then retry. Renaming DjVu to PDF is not supported.")
    job_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = job_dir / "evidence"
    if not evidence_root.resolve().is_relative_to(job_dir):
        raise ValueError("Job evidence directory escapes the job directory.")
    evidence_root.mkdir(exist_ok=True)
    digest = _sha256(source)
    preserved = evidence_root / f"source.{source_format}"
    if not preserved.resolve().is_relative_to(job_dir):
        raise ValueError("Preserved source path escapes the job directory.")
    if preserved.exists() and _sha256(preserved) != digest:
        raise ValueError("Job already contains a different preserved source. Initialize a new job rather than overwriting source evidence.")
    tessdata = _ocr_configuration(fitz, language) if ocr == "always" else None
    warnings = []
    if source_format in {"epub", "mobi"}:
        warnings.append("Reflowed render pages are virtual extraction locators, not original printed pagination. Review source archive/spine and any page-list before assigning printed labels.")
    with tempfile.TemporaryDirectory(prefix="extraction-", dir=evidence_root) as temporary:
        directory = Path(temporary)
        evidence = _Evidence(job_dir, directory)
        if source_format == "epub":
            _epub_preflight(source, evidence)
        elif source_format == "mobi":
            _mobi_preflight(source)
        decoded = source
        if source_format == "djvu":
            decoded = directory / "decoded.pdf"
            _run([tools["ddjvu"], "-format=pdf", str(source), str(decoded)])
            if not decoded.is_file() or not decoded.stat().st_size:
                raise RuntimeError("ddjvu did not produce a decoded PDF. Check DjVuLibre PDF output support and source integrity.")
            if not tools["djvutxt"]:
                warnings.append("djvutxt is unavailable; original DjVu hidden text cannot be extracted. OCR/manual transcription is required for decoded images.")
        fitz.TOOLS.mupdf_warnings(reset=True)
        try:
            document = fitz.open(str(decoded))
        except Exception as exc:
            raise ValueError(f"Cannot decode {source_format.upper()}; source is corrupt, encrypted, or unsupported: {exc}") from exc
        with document:
            if source_format in {"pdf", "djvu"} and not document.is_pdf:
                raise ValueError("Source does not contain a valid PDF document.")
            if document.needs_pass or document.is_encrypted or (document.is_pdf and document.xref_get_key(-1, "Encrypt")[0] != "null"):
                raise ValueError("Source is encrypted/password-protected. Supply an authorized unencrypted edition; extraction does not bypass DRM.")
            if getattr(document, "is_repaired", False):
                raise ValueError("PDF required structural repair. Supply a valid, intact source rather than approving repaired evidence.")
            if not document.page_count:
                raise ValueError("Source has no decodable pages.")
            pages = []
            for index in range(document.page_count):
                page = document.load_page(index)
                result = _native_page(fitz, document, page, index + 1, evidence, source_format in {"epub", "mobi"}, ocr, language, dpi, tessdata)
                if source_format == "djvu" and tools["djvutxt"]:
                    text, spans, raw = _djvu_text(tools["djvutxt"], source, index + 1, result["width"], result["height"], evidence)
                    result.update(text=text, spans=spans, native_text_evidence=raw)
                result["printed_label_candidates"] = _label_candidates(result)
                if result["ocr"]["needed"] and not result["ocr"]["performed"]:
                    warnings.append(f"{result['id']}: necessary OCR was explicitly skipped by ocr='never'; inspect the source render and transcribe manually before source approval.")
                pages.append(result)
                _check_native_warnings(fitz, warnings)
        _check_native_warnings(fitz, warnings)
        if not preserved.exists():
            shutil.copyfile(source, preserved)
        # A successful run keeps its uniquely named evidence directory. Failed runs are removed.
        retained = directory.with_name("retained-" + directory.name)
        directory.rename(retained)
        old_prefix = directory.relative_to(job_dir).as_posix() + "/"
        new_prefix = retained.relative_to(job_dir).as_posix() + "/"
        def relocate(value):
            if isinstance(value, str):
                return new_prefix + value[len(old_prefix):] if value.startswith(old_prefix) else value
            if isinstance(value, list):
                return [relocate(item) for item in value]
            if isinstance(value, dict):
                return {key: relocate(item) for key, item in value.items()}
            return value
        output = {"version": 1, "input": {"path": preserved.relative_to(job_dir).as_posix(), "sha256": digest, "format": source_format}, "pages": relocate(pages), "assets": relocate(evidence.assets), "warnings": warnings}
        target = job_dir / "extraction.json"
        temporary_json = job_dir / ".extraction.json.tmp"
        temporary_json.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_json.replace(target)
        return output
