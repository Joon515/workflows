"""Strict data validation and content binding for standalone book jobs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import tempfile
from typing import Any
import unicodedata

from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError

__all__ = ["load_json", "save_json", "validate_document", "extraction_identity", "extraction_inventory", "validate_source", "source_snapshot_digest", "validate_book", "seal_source", "content_digest", "admit_model"]

_CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"
_JOB_CONTENT_KEYS = ("version", "title", "source_language", "target_language", "source_file", "source_sha256", "models", "layout")
# An allowlist is deliberate: TeX has too many executable primitives for a denylist.
_MATH_COMMANDS = frozenset("""
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa varkappa
lambda mu nu xi omicron pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega
Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
frac dfrac tfrac cfrac binom dbinom tbinom sqrt root overline underline widehat widetilde
hat check breve acute grave tilde bar vec dot ddot dddot ddddot mathring overbrace underbrace
overrightarrow overleftarrow overleftrightarrow underrightarrow underleftarrow
sum prod coprod int iint iiint iiiint oint oiint oiiint lim limsup liminf inf sup min max
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh coth log ln lg exp det gcd dim
ker hom Pr arg deg bmod pmod mod pod operatorname mathop mathbin mathrel mathord mathpunct
mathopen mathclose limits nolimits displaylimits substack overset underset stackrel
left right middle big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr
langle rangle lceil rceil lfloor rfloor lbrace rbrace lvert rvert lVert rVert vert Vert
lgroup rgroup backslash slash parallel nparallel perp mid nmid
infty partial nabla ell hbar hslash imath jmath Re Im wp aleph beth gimel daleth emptyset
varnothing exists nexists forall neg top bot angle measuredangle triangle square Box Diamond
in ni notin subset supset subseteq supseteq subsetneq supsetneq sqsubset sqsupset sqsubseteq
sqsupseteq cup cap uplus sqcup sqcap setminus smallsetminus land lor wedge vee bigcup bigcap
bigvee bigwedge bigoplus bigotimes biguplus le ge leq geq neq ne equiv sim simeq approx
cong asymp propto prec succ preceq succeq ll gg lesssim gtrsim lessapprox gtrapprox
pm mp times div cdot ast star circ bullet diamond oplus ominus otimes oslash odot
rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow longrightarrow
longleftarrow longleftrightarrow Longrightarrow Longleftarrow Longleftrightarrow mapsto
longmapsto hookrightarrow hookleftarrow uparrow downarrow updownarrow Uparrow Downarrow
Updownarrow nearrow searrow swarrow nwarrow to gets implies iff leadsto rightsquigarrow
rightharpoonup rightharpoondown leftharpoonup leftharpoondown rightleftharpoons
ldots cdots vdots ddots dots dotsc dotsb dotsm dotsi dotso prime dprime backprime
mathrm mathit mathbf mathsf mathtt mathcal mathbb mathfrak mathnormal boldsymbol bm
text textrm textit textbf textsf texttt textnormal emph fontfamily
quad qquad enspace thinspace medspace thickspace negthinspace negmedspace negthickspace
phantom hphantom vphantom smash mathstrut strut
displaystyle textstyle scriptstyle scriptscriptstyle
begin end not
""".split()) - {"fontfamily"}
_MATH_ENVIRONMENTS = frozenset("matrix pmatrix bmatrix Bmatrix vmatrix Vmatrix smallmatrix aligned alignedat gathered cases split array".split())


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is not allowed: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict:
    """Read one UTF-8 JSON object, rejecting ambiguous or non-standard JSON."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    _finite(value, str(path))
    return value


def save_json(path: Path, value: dict) -> None:
    """Atomically save a JSON object without accepting NaN or infinity."""
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _finite(value: Any, location: str = "document") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{location}: non-finite number is not allowed")
    if isinstance(value, dict):
        for key, child in value.items():
            _finite(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite(child, f"{location}[{index}]")


def _unique(items: list[dict], key: str, location: str) -> None:
    values = [item[key] for item in items]
    duplicates = [str(value) for value, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValueError(f"{location}: duplicate {key}: {', '.join(duplicates)}")


def validate_document(kind: str, value: dict) -> None:
    """Validate a canonical document's schema and document-local invariants."""
    if kind not in {"book", "terms", "job", "review"}:
        raise ValueError(f"Unknown document kind: {kind}")
    _finite(value)
    schema = load_json(_CONTRACTS / f"{kind}.schema.json")
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: str(list(error.absolute_path)))
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.absolute_path)) or "root"
        raise ValueError(f"{kind}.{location}: {error.message}")
    if kind == "terms":
        _unique(value["terms"], "id", "terms")
        _unique(value["terms"], "number", "terms")
    elif kind == "review":
        _unique(value["findings"], "id", "review.findings")
    elif kind == "job":
        if value["round"] > value["max_rounds"]:
            raise ValueError("job.round cannot exceed max_rounds")
        for stage, model in value["models"].items():
            if bool(model["provider"]) != bool(model["model"]):
                raise ValueError(f"job.models.{stage}: provider and model must be set together")
            if model["provider"]:
                admit_model(model["provider"], model["model"])
        layout = value["layout"]
        if layout["source_mark_edge_mm"] >= layout["outer_mm"]:
            raise ValueError("Source-page mark must lie inside the outer margin")
        if layout["inner_min_mm"] + layout["outer_mm"] >= 148:
            raise ValueError("A5 horizontal margins leave no usable page width")
        if layout["top_mm"] + layout["bottom_mm"] >= 210:
            raise ValueError("A5 vertical margins leave no usable page height")
    elif kind == "book":
        all_ids = []
        for name in ("source_pages", "protected", "blocks", "notes"):
            _unique(value[name], "id", f"book.{name}")
            all_ids.extend(item["id"] for item in value[name])
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Book IDs must be unique across pages, protected values, blocks and notes")
        body_start = next((block for block in value["blocks"] if block["id"] == value["main_body_start"]), None)
        if body_start is None or body_start["kind"] == "blank":
            raise ValueError("book.main_body_start must reference an existing nonblank block ID")
        for block in value["blocks"]:
            if block["kind"] == "list_item" and type(block["list_level"]) is not int:
                raise ValueError(f"Block {block['id']}: list_level must be an integer")
        previous_end = 0
        for index, span in enumerate(value.get("title_terms", [])):
            start, end = span["start"], span["end"]
            location = f"book.title_terms[{index}]"
            if type(start) is not int or type(end) is not int:
                raise ValueError(f"{location}: offsets must be integers")
            if not 0 <= start < end <= len(value["title"]):
                raise ValueError(f"{location}: span must be nonempty and within the title's Unicode codepoint range")
            if start < previous_end:
                raise ValueError(f"{location}: spans must be ordered and nonoverlapping")
            previous_end = end


def admit_model(provider: str, model: str) -> str:
    """Validate one explicit selector; native execution must prove exact registry identity."""
    if not isinstance(provider, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", provider):
        raise ValueError("An explicit provider ID is required; aliases and wildcard routing are not selections")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]*", model):
        raise ValueError("One explicit model ID is required; role aliases, lists and wildcards are not selections")
    alias = re.split(r"[:@]", model.rsplit("/", 1)[-1], maxsplit=1)[0].casefold()
    if alias in {"auto", "default", "inherit", "inherited", "parent", "fallback"}:
        raise ValueError("Automatic, default and inherited model selectors are not explicit model choices")
    return f"{provider}/{model}"


def _contained(root: Path, relative: str, location: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ValueError(f"{location}: use a nonempty relative POSIX path")
    candidate = Path(relative)
    if candidate.is_absolute() or PureWindowsPath(relative).drive or ".." in candidate.parts:
        raise ValueError(f"{location}: path must stay inside the job directory: {relative}")
    root = root.resolve()
    path = (root / candidate).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{location}: missing file or path escapes job directory: {relative}")
    return path


def _job(job_dir: Path) -> dict:
    job = load_json(_contained(job_dir, "job.json", "job"))
    validate_document("job", job)
    source = _contained(job_dir, job["source_file"], "job.source_file")
    if _file_hash(source) != job["source_sha256"]:
        raise ValueError("Original source checksum differs from job.source_sha256; restore the source or initialize a new job")
    return job


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extraction_record(job_dir: Path) -> tuple[dict, str | None]:
    job_dir = Path(job_dir).resolve()
    job = _job(job_dir)
    event = next((item for item in reversed(job["history"]) if item.get("event") == "extracted"), None)
    path = job_dir / "extraction.json"
    if not path.exists() and not path.is_symlink():
        if event is None:
            return job, None
        raise ValueError("Controller-recorded extraction is missing")
    path = _contained(job_dir, "extraction.json", "extraction inventory")
    digest = _file_hash(path)
    if event is None or event.get("extraction_sha256") != digest:
        raise ValueError("Extraction differs from the latest controller-recorded extraction")
    return job, digest


def extraction_identity(job_dir: Path) -> str | None:
    """Stream-check controller-recorded extraction bytes, without decoding its pages.

    A bound plan may reuse its previously checked inventory only when this identity
    and its exact original job/source bindings still match. This is not a cache.
    """
    return _extraction_record(job_dir)[1]


def extraction_inventory(job_dir: Path) -> dict | None:
    """Load the canonical original-page inventory, not a declared draft page set."""
    job_dir = Path(job_dir).resolve()
    job, identity = _extraction_record(job_dir)
    if identity is None:
        return None
    extraction = load_json(_contained(job_dir, "extraction.json", "extraction inventory"))
    if not isinstance(extraction.get("input"), dict) or extraction["input"].get("sha256") != job["source_sha256"]:
        raise ValueError("Extraction inventory belongs to a different original source")
    pages = extraction.get("pages")
    if (not isinstance(pages, list) or not pages
            or any(not isinstance(page, dict)
                   or any(not isinstance(page.get(key), str) or not page[key].strip() for key in ("id", "locator"))
                   for page in pages)):
        raise ValueError("Extraction requires a nonempty original-page inventory")
    if any(len({page[key] for page in pages}) != len(pages) for key in ("id", "locator")):
        raise ValueError("Extraction original-page IDs and locators must be unique")
    return extraction


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _math(value: str, location: str) -> None:
    if "^^" in value or re.search(r"(?<!\\)%", value) or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"{location}: unsafe TeX characters or comments in protected math")
    for match in re.finditer(r"\\([A-Za-z]+|.)", value):
        command = match.group(1)
        if command.isalpha() and command not in _MATH_COMMANDS:
            raise ValueError(f"{location}: unsafe or unsupported TeX command \\{command}")
        if not command.isalpha() and command not in "\\{}_%#$& ,:;!|/":
            raise ValueError(f"{location}: unsupported TeX escape \\{command}")
    for match in re.finditer(r"\\(?:begin|end)\s*\{([^}]*)\}", value):
        if match.group(1) not in _MATH_ENVIRONMENTS:
            raise ValueError(f"{location}: unsupported math environment {match.group(1)}")
    # A malformed environment command must not be allowed to acquire arguments later.
    count = len(re.findall(r"\\(?:begin|end)\b", value))
    if count != len(re.findall(r"\\(?:begin|end)\s*\{[^}]*\}", value)):
        raise ValueError(f"{location}: malformed math environment")


def _assets(book: dict) -> list[tuple[str, float | None, float | None, str]]:
    assets = []
    for block in book["blocks"]:
        if block["kind"] == "image":
            assets.append((block["asset"], block["width"], block["height"], f"Block {block['id']}"))
        elif block["kind"] == "group":
            for image in block["images"]:
                if image["x"] + image["width"] > block["canvas_width"] + 1e-8 or image["y"] + image["height"] > block["canvas_height"] + 1e-8:
                    raise ValueError(f"Block {block['id']}: image extends beyond its group canvas")
                assets.append((image["asset"], image["width"], image["height"], f"Block {block['id']}"))
    for category in ("blocks", "notes"):
        for item in book[category]:
            for index, token in enumerate(item["source"]):
                if "image" in token:
                    image = token["image"]
                    assets.append((image["asset"], image["width_em"], image["height_em"],
                                   f"{category}.{item['id']}.source[{index}].image"))
    for note in book["notes"]:
        for index, evidence in enumerate(note.get("source_evidence", [])):
            assets.append((evidence["asset"], None, None, f"Note {note['id']}.source_evidence[{index}]"))
    return assets


def _asset_hashes(job_dir: Path, book: dict) -> dict:
    hashes = {}
    dimensions = {}
    for relative, width, height, location in _assets(book):
        path = _contained(job_dir, relative, location + " asset")
        resolved = path.relative_to(job_dir.resolve())
        if Path(relative).parts[0] == "build" or Path(relative) == Path("output.pdf") or resolved.parts[0] == "build" or resolved == Path("output.pdf"):
            raise ValueError(f"{location}: Generated artifacts are not source image evidence: {relative}")
        if relative not in dimensions:
            try:
                with Image.open(path) as image:
                    dimensions[relative] = image.size
                    image.verify()
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                raise ValueError(f"{location}: Image asset must be a readable raster image: {relative}: {exc}") from exc
            hashes[relative] = _file_hash(path)
        actual_width, actual_height = dimensions[relative]
        if width is not None and not math.isclose(width / height, actual_width / actual_height, rel_tol=0.01):
            raise ValueError(f"{location}: Image asset {relative}: declared aspect ratio differs from source image")
    return hashes


def _has_content(tokens: list[dict]) -> bool:
    return any(("text" in token and bool(token["text"].strip())) or any(key in token for key in ("protected", "term", "note", "image")) for token in tokens)



def _ordinary_text(tokens: list[dict], terminology: dict, protected: dict) -> str:
    """Only unprotected semantic prose; names, code, and mathematics stay literal."""
    pieces = []
    for token in tokens:
        if "text" in token:
            pieces.append(token["text"])
        elif "term" in token and token["term"] in terminology:
            term = terminology[token["term"]]
            text = term["target"]
            for protected_id in term["protected_ids"]:
                text = text.replace(protected[protected_id]["value"], "", 1)
            pieces.append(text)
    return "".join(pieces)


def _has_ordinary_prose(text: str) -> bool:
    return any(character.isalnum() for character in text)


def _semantic_text(tokens: list[dict], terminology: dict, protected: dict) -> str:
    pieces = []
    for token in tokens:
        if "text" in token:
            pieces.append(token["text"])
        elif "term" in token:
            pieces.append(terminology[token["term"]]["target"])
        elif "protected" in token:
            pieces.append(protected[token["protected"]]["value"])
    # Token splitting, typography, punctuation, and case changes do not translate prose.
    return "".join(character for character in unicodedata.normalize("NFKC", "".join(pieces)).casefold() if character.isalnum())

def _validate_structure(book: dict, job_dir: Path, terms: dict | None, translated: bool, *, languages_differ: bool = False) -> None:
    validate_document("book", book)
    pages = {item["id"]: item for item in book["source_pages"]}
    protected = {item["id"]: item for item in book["protected"]}
    notes = {item["id"]: item for item in book["notes"]}
    terminology = {item["id"]: item for item in terms["terms"]} if terms else {}
    page_order = {key: index for index, key in enumerate(pages)}
    source_protected = Counter()
    note_calls = Counter()
    page_calls = []
    used_terms = set()
    covered_pages = set()

    if not translated and book.get("title_terms"):
        raise ValueError("Source manuscripts cannot contain title term spans")
    for index, span in enumerate(book.get("title_terms", [])):
        term_id = span["term"]
        if term_id not in terminology:
            raise ValueError(f"title_terms[{index}]: unknown term {term_id}")
        term = terminology[term_id]
        literal = book["title"][span["start"]:span["end"]]
        if literal not in (term["source"], term["target"]):
            raise ValueError(f"title_terms[{index}]: displayed slice must equal term source or target literally")
        used_terms.add(term_id)

    for page in pages.values():
        if page["printed_label"] is not None and not page["label_verified"]:
            raise ValueError(f"Source page {page['id']}: printed label must be verified against source evidence before sealing")
    for item in protected.values():
        if item["kind"] in {"math", "variable"}:
            _math(item["value"], f"Protected {item['id']}")
    for term in terminology.values():
        spans = []
        cursor = 0
        for protected_id in term["protected_ids"]:
            item = protected.get(protected_id)
            if item is None or item["kind"] != "name":
                raise ValueError(f"Term {term['id']}: protected_ids must reference protected names")
            value = item["value"]
            position = term["target"].find(value, cursor)
            if position < 0 or value not in term["source"]:
                raise ValueError(f"Term {term['id']}: protected name {protected_id} must occur literally in source and target in declared order")
            cursor = position + len(value)
            spans.append((position, cursor))
        # Match disjoint declared name spans. A shorter protected name can be a
        # substring of another name without creating an extra occurrence.
        for protected_id in set(term["protected_ids"]):
            value = protected[protected_id]["value"]
            position = term["target"].find(value)
            while position >= 0:
                end = position + len(value)
                if not any(start <= position and end <= stop for start, stop in spans):
                    raise ValueError(f"Term {term['id']}: protected name multiplicity differs from protected_ids")
                position = term["target"].find(value, position + 1)

    def sequence(tokens: list[dict], location: str, source: bool, context: str, block_pages: list[str] | None = None) -> list[tuple[str, Any]]:
        result = []
        for token in tokens:
            key, value = next(iter(token.items()))
            if key == "text":
                continue
            if context == "preface" and key not in {"protected", "term"}:
                raise ValueError(f"{location}: prefaces permit only text, protected and term tokens")
            if context == "note" and key in {"note", "page"}:
                raise ValueError(f"{location}: notes cannot contain nested note or page tokens")
            if key == "image":
                result.append((key, value))
            elif key == "term":
                if source:
                    raise ValueError(f"{location}: source inline arrays cannot contain term tokens")
                if value not in terminology:
                    raise ValueError(f"{location}: unknown term {value}")
                used_terms.add(value)
                result.extend(("protected", item) for item in terminology[value]["protected_ids"])
            else:
                table = {"protected": protected, "note": notes, "page": pages}[key]
                if value not in table:
                    raise ValueError(f"{location}: unknown {key} reference {value}")
                result.append((key, value))
                if source and key == "protected":
                    source_protected[value] += 1
                elif source and key == "note":
                    note_calls[value] += 1
                elif source and key == "page":
                    if block_pages is not None and value not in block_pages:
                        raise ValueError(f"{location}: page token {value} is absent from block.source_pages")
                    page_calls.append(value)
        return result

    last_page = -1
    for block in book["blocks"]:
        location = f"Block {block['id']}"
        if "fit" in block:
            if not translated:
                raise ValueError(f"{location}: fit is output-only metadata; omit it from the source manuscript")
            if block["fit"]["scale"] < block["fit"]["min_scale"]:
                raise ValueError(f"{location}: fit.scale is below the reviewed legibility floor fit.min_scale; choose a readable scale or an explicitly reviewed structural/layout alternative")
        for page_id in block["source_pages"]:
            if page_id not in pages:
                raise ValueError(f"{location}: unknown source page {page_id}")
            index = page_order[page_id]
            if index < last_page:
                raise ValueError(f"{location}: source page coverage is out of reading order")
            last_page = index
            covered_pages.add(page_id)
        if block["kind"] in {"heading", "paragraph", "list_item"} and not _has_content(block["source"]):
            raise ValueError(f"{location}: source text/evidence must not be empty")
        if block["kind"] == "blank":
            expected_page = [{"page": block["source_pages"][0]}]
            if block["source"] != expected_page or (translated and block["target"] != expected_page):
                raise ValueError(f"{location}: blank must conserve exactly its one source-page token, with no fabricated prose")
            if any(other is not block and block["source_pages"][0] in other["source_pages"] for other in book["blocks"]):
                raise ValueError(f"{location}: blank source page cannot also contain nonblank or duplicate block coverage")
        if block["kind"] == "list_item":
            for field in (("source", "target") if translated else ("source",)):
                text = "".join(token.get("text", "") for token in block[field]).lstrip()
                if text == block["label"] or text.startswith(block["label"] + " ") or text.startswith(block["label"] + "\t"):
                    raise ValueError(f"{location}: list label must not be duplicated in inline prose")
        if block["kind"] in {"display_math", "code"}:
            protected_id = block["protected_id"]
            expected = "math" if block["kind"] == "display_math" else "code"
            if protected_id not in protected or protected[protected_id]["kind"] != expected:
                raise ValueError(f"{location}: protected_id must reference protected {expected}")
            source_protected[protected_id] += 1
        source_sequence = sequence(block["source"], location + ".source", True, "body", block["source_pages"])
        if translated:
            target_sequence = sequence(block["target"], location + ".target", False, "body", block["source_pages"])
            if source_sequence != target_sequence:
                raise ValueError(f"{location}: target must preserve exact protected, image, note and page token values, order and multiplicity")
            if _has_content(block["source"]) and not _has_content(block["target"]):
                raise ValueError(f"{location}: translated target must not be empty")
    if covered_pages != set(pages):
        raise ValueError("Source-page coverage is incomplete: " + ", ".join(sorted(set(pages) - covered_pages)))
    if len(page_calls) != len(set(page_calls)) or [page_order[page] for page in page_calls] != sorted(page_order[page] for page in page_calls):
        raise ValueError("Source page boundary tokens must occur once in source reading order")
    for note in notes.values():
        location = f"Note {note['id']}"
        if note_calls[note["id"]] != 1:
            raise ValueError(f"{location}: exactly one body note reference is required")
        if not _has_content(note["source"]):
            raise ValueError(f"{location}: source must not be empty")
        restoration = note.get("restoration")
        if restoration is not None:
            if note["content_type"] != "prose":
                raise ValueError(f"{location}: restoration requires a prose note with an editorial explanation")
            owner, callout = next((block, index) for block in book["blocks"]
                                  for index, token in enumerate(block["source"]) if token.get("note") == note["id"])
            if restoration["source_page"] not in owner["source_pages"]:
                raise ValueError(f"{location}: restoration source_page must belong to its owning source block")
            preceding = []
            for token in reversed(owner["source"][:callout]):
                if "text" not in token:
                    break
                preceding.append(token["text"])
            reading = "".join(reversed(preceding)).rstrip()
            replacement = restoration["replacement"]
            if replacement != replacement.strip() or not reading.endswith(replacement):
                raise ValueError(f"{location}: restoration replacement must immediately precede its source callout as ordinary text")
            asset = restoration["damage_asset"]
            if sum(token.get("image", {}).get("asset") == asset for token in note["source"]) != 1:
                raise ValueError(f"{location}: restoration requires exactly one original damage image in source tokens")
            witnesses = [evidence for evidence in note.get("source_evidence", []) if evidence["asset"] == asset]
            if len(witnesses) != 1 or witnesses[0]["source_page"] != restoration["source_page"]:
                raise ValueError(f"{location}: restoration damage image requires matching original source-page evidence")
            fragment = restoration["original_fragment"]
            for field in (("source", "target") if translated else ("source",)):
                if sum(token.get("text", "").count(fragment) for token in note[field]) != 1:
                    raise ValueError(f"{location}.{field}: original_fragment must occur verbatim exactly once within one text token")
                explanation = _ordinary_text(note[field], terminology, protected).replace(fragment, "", 1)
                if not _has_ordinary_prose(explanation):
                    raise ValueError(f"{location}.{field}: restoration requires semantic explanation beyond the original fragment")
        for evidence in note.get("source_evidence", []):
            if evidence["source_page"] not in pages:
                raise ValueError(f"{location}: source_evidence references unknown source page {evidence['source_page']}")
            if (not restoration or evidence["asset"] != restoration["damage_asset"]) and any(
                    token.get("image", {}).get("asset") == evidence["asset"] for token in note["source"] + note["target"]):
                raise ValueError(f"{location}: source evidence is non-rendered and must not be passed through as note imagery")
        source_sequence = sequence(note["source"], location + ".source", True, "note")
        source_prose = _has_ordinary_prose(_ordinary_text(note["source"], terminology, protected))
        if note["content_type"] == "prose" and not source_prose:
            raise ValueError(f"{location}: prose source requires genuine ordinary transcribed text; raster-only prose is not permitted")
        if note["content_type"] == "literal" and source_prose:
            raise ValueError(f"{location}: literal notes cannot contain ordinary prose; use protected tokens or classify as prose")
        if translated:
            target_sequence = sequence(note["target"], location + ".target", False, "note")
            if source_sequence != target_sequence:
                raise ValueError(f"{location}: target must preserve protected and image token values, order and multiplicity")
            if not _has_content(note["target"]):
                raise ValueError(f"{location}: translated target must not be empty")
            target_prose = _has_ordinary_prose(_ordinary_text(note["target"], terminology, protected))
            if note["content_type"] == "literal" and target_prose:
                raise ValueError(f"{location}: literal target cannot contain ordinary prose")
            if note["content_type"] == "prose":
                if not target_prose:
                    raise ValueError(f"{location}: translated prose target requires ordinary text or terminology content")
                if languages_differ and _semantic_text(note["source"], terminology, protected) == _semantic_text(note["target"], terminology, protected):
                    raise ValueError(f"{location}: ordinary prose is completely unchanged across different languages; translate the semantic note text")
    for name in ("agent_preface", "human_preface"):
        if book[name] is not None:
            sequence(book[name], name, False, "preface")
    if translated and not _has_content(book["agent_preface"]):
        raise ValueError("Translated book requires a nonempty agent_preface")
    if set(source_protected) != set(protected):
        raise ValueError("Protected values must all be used in the source body or notes")
    if translated and used_terms != set(terminology):
        raise ValueError("Unused terminology table entries: " + ", ".join(sorted(set(terminology) - used_terms)))
    _asset_hashes(job_dir, book)


def _source_digest(job_dir: Path, job: dict, source: dict) -> str:
    return _canonical_hash({"book-source": source, "source_file": job["source_file"], "source_sha256": job["source_sha256"], "assets": _asset_hashes(job_dir, source)})


def _check_seal(job_dir: Path, job: dict, source: dict) -> None:
    path = _contained(job_dir, "source.sha256", "source seal")
    seal = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", seal) or seal != _source_digest(job_dir, job, source):
        raise ValueError("Source seal does not match book-source.json, original source identity or source assets; explicitly review and reseal corrections")


def _immutable(book: dict) -> dict:
    return {key: ([{name: value for name, value in item.items() if name != "target" and not (key == "blocks" and name == "fit")} for item in items] if key in {"blocks", "notes"} else items) for key, items in book.items() if key not in {"title", "title_terms", "agent_preface", "human_preface"}}


def validate_source(job_dir: Path) -> dict:
    """Validate reviewed source structure/assets without accepting or replacing a seal."""
    job_dir = Path(job_dir).resolve()
    _job(job_dir)
    source = load_json(_contained(job_dir, "book-source.json", "source manuscript"))
    _validate_structure(source, job_dir, None, False)
    return source


def source_snapshot_digest(job_dir: Path) -> str:
    """Bind a validated source revision before its explicit coordinator-owned seal."""
    job_dir = Path(job_dir).resolve()
    source = validate_source(job_dir)
    return _source_digest(job_dir, _job(job_dir), source)


def validate_book(job_dir: Path, translated: bool = True) -> dict:
    """Validate source readiness or a sealed, structurally conserved translation."""
    job_dir = Path(job_dir).resolve()
    job = _job(job_dir)
    source = validate_source(job_dir)
    if not translated:
        if (job_dir / "source.sha256").exists():
            _check_seal(job_dir, job, source)
        return source
    _check_seal(job_dir, job, source)
    terms = load_json(_contained(job_dir, "terms.json", "terminology"))
    validate_document("terms", terms)
    book = load_json(_contained(job_dir, "book.json", "translated manuscript"))
    validate_document("book", book)
    if _immutable(book) != _immutable(source):
        raise ValueError("Translated manuscript changed immutable source structure; only title, title_terms, targets, prefaces and reviewed graphic fit may change")
    source_language = job["source_language"].strip().replace("_", "-").split("-", 1)[0].casefold()
    target_language = job["target_language"].strip().replace("_", "-").split("-", 1)[0].casefold()
    _validate_structure(book, job_dir, terms, True, languages_differ=source_language != target_language)
    return book


def seal_source(job_dir: Path) -> str:
    """Seal reviewed source structure and its original source/asset identity."""
    job_dir = Path(job_dir).resolve()
    digest = source_snapshot_digest(job_dir)
    # Replacing rather than following an existing symlink keeps this write contained.
    destination = job_dir / "source.sha256"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=job_dir, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(digest + "\n")
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return digest


def content_digest(job_dir: Path) -> str:
    """Bind current content and assets, excluding review/controller/build state."""
    job_dir = Path(job_dir).resolve()
    book = validate_book(job_dir, translated=True)
    job = _job(job_dir)
    assets = _asset_hashes(job_dir, book)
    asset_root = job_dir / "assets"
    if asset_root.exists():
        if not asset_root.resolve().is_relative_to(job_dir):
            raise ValueError("assets directory escapes the job directory")
        for path in sorted(asset_root.rglob("*")):
            if path.is_symlink() and (not path.resolve().is_relative_to(job_dir) or path.is_dir()):
                raise ValueError(f"Asset symlink is not a contained regular file: {path}")
            if path.is_file():
                relative = path.relative_to(job_dir).as_posix()
                assets[relative] = _file_hash(_contained(job_dir, relative, "asset"))
    return _canonical_hash({"book": book, "terms": load_json(_contained(job_dir, "terms.json", "terminology")), "job": {key: job[key] for key in _JOB_CONTENT_KEYS}, "source_seal": (job_dir / "source.sha256").read_text(encoding="ascii").strip(), "assets": assets})
