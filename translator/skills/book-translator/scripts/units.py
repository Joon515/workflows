"""Durable bounded book work units; only assembly writes canonical manuscripts.

Unit admission deliberately leaves job.json, source seals and global rounds alone.
OMP owns execution. Content checkpoints retain compact task references, not execution
attestation. The controller owns stage transitions, seals, builds and review.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from jsonschema import Draft202012Validator

import core


_ROLES = {"source", "translation", "review"}
_REVIEW_CHECKS = {"coverage", "terminology", "protected_content", "source_pages", "image_relations", "footnotes", "typography", "preface"}
_METADATA = {"title", "title_terms", "agent_preface", "human_preface"}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _path(job: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Unit artifact path must be a nonempty relative POSIX path")
    relative = Path(value)
    result = (job / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not result.is_relative_to(job):
        raise ValueError(f"Unit artifact escapes job: {value}")
    return result


def _relative(job: Path, path: Path) -> str:
    return path.relative_to(job).as_posix()


def _job(job: Path) -> dict:
    data = core.load_json(job / "job.json")
    core.validate_document("job", data)
    if _hash(_path(job, data["source_file"])) != data["source_sha256"]:
        raise ValueError("Original source identity changed")
    return data


def _checked(job: Path, name: str, digest: str) -> dict:
    path = _path(job, name)
    if not path.is_file() or _hash(path) != digest:
        raise ValueError(f"Missing or changed immutable unit artifact: {name}")
    return core.load_json(path)


def _write_once(path: Path, value: dict) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"Unit artifact already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Controller mutations are serialized by the caller's job mutation lock.
    core.save_json(path, value)


def _asset_names(book: dict) -> set[str]:
    result = set()
    for block in book.get("blocks", []):
        if block.get("kind") == "image":
            result.add(block["asset"])
        for image in block.get("images", []):
            result.add(image["asset"])
    for item in book.get("blocks", []) + book.get("notes", []):
        for token in item.get("source", []):
            if "image" in token:
                result.add(token["image"]["asset"])
        for evidence in item.get("source_evidence", []):
            result.add(evidence["asset"])
        if item.get("restoration"):
            result.add(item["restoration"]["damage_asset"])
    return result


def _references(item: dict, key: str) -> set[str]:
    result = {token[key] for token in item.get("source", []) if key in token}
    if key == "protected" and "protected_id" in item:
        result.add(item["protected_id"])
    return result


def _import_draft(job: Path, directory: Path, draft_path: Path) -> tuple[dict, dict]:
    draft = core.load_json(draft_path)
    for field in ("blocks", "notes", "protected", "source_pages"):
        if not isinstance(draft.get(field), list):
            raise ValueError(f"Untrusted draft needs a {field} array before unit planning")
    original_digest = _hash(draft_path)
    replacements = {}
    assets = {}
    root = draft_path.parent.resolve()
    for name in sorted(_asset_names(draft)):
        source = _path(root, name)
        if not source.is_file():
            raise ValueError(f"Draft source asset is missing: {name}")
        digest = _hash(source)
        if root == job:
            destination = source
        else:
            destination = directory / "draft-assets" / f"{digest}{source.suffix.lower()}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(source, destination)
        replacement = _relative(job, destination)
        replacements[name] = replacement
        assets[replacement] = digest

    def relocate(value):
        if isinstance(value, dict):
            return {key: replacements.get(item, item) if key in {"asset", "damage_asset"} and isinstance(item, str)
                    else relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value

    draft = relocate(draft)
    _write_once(directory / "draft.json", draft)
    return draft, {"origin_sha256": original_digest, "snapshot": _relative(job, directory / "draft.json"),
                   "snapshot_sha256": _hash(directory / "draft.json"), "assets": assets, "trusted": False}


def _baseline(job: Path) -> dict:
    return {name: _hash(job / name) if (job / name).is_file() else None
            for name in ("book-source.json", "book.json", "source.sha256", "terms.json", "handoff.md")}


def _current_plan(job: Path, role: str) -> tuple[Path, dict, str]:
    if role not in _ROLES:
        raise ValueError("Bounded units support source, translation and review")
    active = core.load_json(_path(job, f"units/{role}/active.json"))
    plan = _checked(job, active["plan"], active["plan_sha256"])
    if (plan.get("version") != 1 or plan.get("kind") != "book-unit-plan"
            or plan.get("role") != role or plan.get("job_path") != str(job)):
        raise ValueError("Invalid active book unit plan; explicitly import historical completed checkpoints first")
    return _path(job, active["plan"]), plan, active["plan_sha256"]


def _plan_inputs(job: Path, plan: dict) -> None:
    if plan.get("job_path") != str(job):
        raise ValueError("Unit plan belongs to a different absolute job")
    if core.extraction_identity(job) != plan["extraction_sha256"]:
        raise ValueError("Extraction changed after unit planning; create a new plan")
    draft = plan.get("draft")
    if draft is not None:
        _checked(job, draft["snapshot"], draft["snapshot_sha256"])



def _stable_context(job: Path, plan: dict) -> dict:
    data = _job(job)
    readiness = plan.get("readiness")
    if plan["role"] != "source" and (not isinstance(readiness, dict)
            or readiness.get("source_digest") != plan["source_digest"]
            or not isinstance(readiness.get("bindings"), dict)):
        raise ValueError("Translation/review unit plan lacks admitted readiness bindings")
    if (_hash(job / "job.json") != plan["job_sha256"] or data["state"] != plan["base_state"]
            or data["round"] != plan["base_round"] or data["models"][plan["role"]] != plan["selected_model"]
            or _baseline(job) != plan["baseline"]):
        raise ValueError("Unit plan job/source/manuscript/model context changed; create a new plan")
    _plan_inputs(job, plan)
    if plan.get("build") is not None and _review_build(job) != plan["build"]:
        raise ValueError("Review unit build/PDF changed; create a new plan")
    for name, digest in plan.get("review_artifacts", {}).items():
        path = _path(job, name)
        current = _hash(path) if path.is_file() else None
        if current != digest:
            raise ValueError("Review worker changed a controller-owned canonical review artifact")
    return data


def page_count(job) -> int:
    """Use canonical extraction lineage before any declared manuscript inventory."""
    job = Path(job).resolve(strict=True)
    identity = core.extraction_identity(job)
    if identity is not None:
        for role in sorted(_ROLES):
            if not (job / f"units/{role}/active.json").is_file():
                continue
            _, plan, _ = _current_plan(job, role)
            if plan["extraction_sha256"] == identity:
                return len(plan["page_ids"])
        inventory = core.extraction_inventory(job)
        return len(inventory["pages"])
    source = job / "book-source.json"
    return len(core.load_json(source)["source_pages"]) if source.is_file() else 0


def _review_build(job: Path) -> dict:
    verification = core.load_json(job / "build/verification.json")
    digest = core.content_digest(job)
    pdf_digest = _hash(job / "build/book.pdf")
    if (verification.get("passed") is not True or verification.get("content_digest") != digest
            or verification.get("pdf_sha256") != pdf_digest):
        raise ValueError("Review units require an unchanged passing current build")
    return {"content_digest": digest, "pdf_sha256": pdf_digest,
            "verification_sha256": _hash(job / "build/verification.json")}


def _review_ownership(job: Path, specs: list, block_owners: dict, note_owners: dict, metadata_owner: str) -> list[int]:
    verification = core.load_json(job / "build/verification.json")
    physical = [item.get("physical_pdf_page", item.get("page")) for item in verification.get("pages", [])]
    if not physical or physical != list(range(1, len(physical) + 1)):
        raise ValueError("Review build lacks a complete physical PDF page inventory")
    needed = {spec["unit_id"]: set() for spec in specs}
    seen_blocks = set()
    for boundary in verification.get("block_boundaries", []):
        identifier = boundary["id"]
        if identifier not in block_owners:
            raise ValueError("Review build boundary references an unknown block")
        seen_blocks.add(identifier)
        start, end = boundary["start"]["page"], boundary["end"]["page"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(physical):
            raise ValueError("Review block has an invalid physical page range")
        needed[block_owners[identifier]].update(range(start, end + 1))
    book = core.load_json(job / "book.json")
    if seen_blocks != {block["id"] for block in book["blocks"] if block["kind"] != "blank"}:
        raise ValueError("Review build lacks complete nonblank block boundaries")
    seen_notes = set()
    for note in verification.get("notes", []):
        if note["id"] not in note_owners:
            raise ValueError("Review build note has no manuscript owner")
        seen_notes.add(note["id"])
        start, end, callout = note["start"]["page"], note["end"]["page"], note["callout"]["page"]
        if any(type(page) is not int or not 1 <= page <= len(physical) for page in (start, end, callout)) or start > end:
            raise ValueError("Review note has an invalid physical page range")
        needed[note_owners[note["id"]]].update(range(start, end + 1))
        needed[note_owners[note["id"]]].add(callout)
    if seen_notes != set(note_owners):
        raise ValueError("Review build lacks complete note boundaries")
    special = set(verification.get("agent_preface_pages", []))
    special.update(row.get("physical_pdf_page", row.get("page")) for row in verification.get("glossary_rows", []))
    if not special <= set(physical):
        raise ValueError("Review frontmatter/glossary page identity is invalid")
    owners = {page: metadata_owner for page in special}
    for spec in specs:
        for page in needed[spec["unit_id"]]:
            owners.setdefault(page, spec["unit_id"])
    for page in physical:
        owners.setdefault(page, metadata_owner)
    expanded = []
    for spec in specs:
        unit_id = spec["unit_id"]
        assigned = [page for page in physical if owners[page] == unit_id]
        chunks = [assigned[offset:offset + 8] for offset in range(0, len(assigned), 8)] or [[]]
        for index, chunk in enumerate(chunks, 1):
            child_id = unit_id if index == 1 else f"{unit_id}_pdf{index:03d}"
            context = {chunk[0] - 1, chunk[-1] + 1} & set(physical) if chunk else set()
            expanded.append({**spec, "unit_id": child_id, "source_unit_id": unit_id,
                             "pdf_pages": chunk, "context_pdf_pages": sorted(context - set(chunk))})
    specs[:] = expanded
    return physical



def create_plan(job, role: str, *, pages_per_unit: int = 8, draft_path=None, revise: bool = False,
                max_context_pages: int = 4, readiness: dict | None = None) -> dict:
    """Snapshot bounded page evidence and untrusted draft slices without admission.

    A complete block belongs to its first source page's unit. Notes follow their
    callout owner; shared protected declarations have one owner and read-only
    copies elsewhere. Crossing blocks stay intact with bounded context pages.
    """
    job = Path(job).resolve(strict=True)
    if role not in _ROLES or type(pages_per_unit) is not int or not 1 <= pages_per_unit <= 8:
        raise ValueError("Choose source/translation/review and pages_per_unit between 1 and 8")
    if type(max_context_pages) is not int or not 0 <= max_context_pages <= 4:
        raise ValueError("max_context_pages must be between 0 and 4")
    if role != "source" and (not isinstance(readiness, dict) or not isinstance(readiness.get("bindings"), dict)):
        raise ValueError("Controller must supply admitted readiness bindings for translation/review planning")
    data = _job(job)
    if any(not data["models"].get(name, {}).get("provider") or not data["models"].get(name, {}).get("model")
           for name in ("source", "terminology", "translation", "review")):
        raise ValueError("Every exact role model must be configured before unit planning")
    sealed = (job / "source.sha256").is_file()
    if role == "source":
        if (revise and not sealed) or (not revise and (data["state"] != "extracted" or sealed)):
            raise ValueError("Source units require extracted/unsealed state or explicit sealed revision")
    elif role == "translation" and (revise or data["state"] not in {"terminology_ready", "changes_requested"} or data["round"] >= data["max_rounds"]):
        raise ValueError("Translation units require an eligible pending translation round")
    elif role == "review" and (revise or data["state"] != "translated" or data["round"] < 1):
        raise ValueError("Review units require a current translated round")
    if role in {"translation", "review"}:
        core.validate_book(job, translated=role == "review")
        core.validate_document("terms", core.load_json(job / "terms.json"))
        if not (job / "handoff.md").read_text(encoding="utf-8").strip():
            raise ValueError("Translation units require a substantive terminology handoff")
    extraction = core.extraction_inventory(job)
    if extraction is None:
        raise ValueError("Unit planning requires controller-admitted complete extraction evidence")
    extraction_digest = next(event["extraction_sha256"] for event in reversed(data["history"]) if event.get("event") == "extracted")
    pages = extraction["pages"]
    page_ids = [page["id"] for page in pages]
    page_order = {name: index for index, name in enumerate(page_ids)}
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/{role}/{identifier}")
    directory.mkdir(parents=True, exist_ok=False)
    baseline = _baseline(job)
    review_artifacts = {}
    if role == "review":
        for suffix in ("json", "receipt.json"):
            name = f"reviews/round-{data['round']}.{suffix}"
            path = _path(job, name)
            review_artifacts[name] = _hash(path) if path.is_file() else None
    draft_info = None
    build = _review_build(job) if role == "review" else None
    if role in {"translation", "review"}:
        draft = core.load_json(job / ("book.json" if role == "review" else "book-source.json"))
    else:
        selected_draft = Path(draft_path).resolve(strict=True) if draft_path else job / "book-source.json"
        if selected_draft.is_file():
            draft, draft_info = _import_draft(job, directory, selected_draft)
        else:
            draft = {"title": data["title"], "main_body_start": None, "source_pages": [],
                     "blocks": [], "notes": [], "protected": []}
            for page in pages:
                text = page.get("ocr", {}).get("text") or page.get("text", "")
                source = [{"page": page["id"]}]
                if text:
                    source.append({"text": text})
                draft["blocks"].append({"id": f"draft_{page['id']}", "kind": "paragraph",
                    "source_pages": [page["id"]], "source": source, "target": []})
    if role != "source" and [page["id"] for page in draft["source_pages"]] != page_ids:
        raise ValueError("Sealed source inventory differs from complete original extraction page order")
    declarations = {}
    for category in ("blocks", "notes", "protected"):
        declarations[category] = {item["id"]: item for item in draft[category]}
        if len(declarations[category]) != len(draft[category]):
            raise ValueError(f"Draft {category} IDs are duplicated; resolve ownership before planning")
    owners = {}
    unit_specs = []
    for offset in range(0, len(pages), pages_per_unit):
        owned = page_ids[offset:offset + pages_per_unit]
        unit_id = f"u{len(unit_specs) + 1:04d}"
        unit_specs.append({"unit_id": unit_id, "owned_pages": owned, "owned_block_ids": [],
                           "owned_note_ids": [], "owned_protected_ids": []})
        owners.update({page: unit_id for page in owned})
    specifications = {item["unit_id"]: item for item in unit_specs}
    block_owners = {}
    for block in draft["blocks"]:
        covered = block.get("source_pages", [])
        if not covered or any(page not in page_order for page in covered):
            raise ValueError(f"Draft block {block['id']} has missing/unknown source-page ownership")
        if sorted(covered, key=page_order.__getitem__) != covered:
            raise ValueError(f"Draft block {block['id']} page order is invalid")
        owner = owners[covered[0]]
        block_owners[block["id"]] = owner
        specifications[owner]["owned_block_ids"].append(block["id"])
    note_owners = {}
    protected_users = {}
    for block in draft["blocks"]:
        owner = block_owners[block["id"]]
        for name in _references(block, "note"):
            if name not in declarations["notes"]:
                raise ValueError(f"Draft block references missing note {name}")
            if name in note_owners and note_owners[name] != owner:
                raise ValueError(f"Draft note {name} has competing cross-unit callout owners")
            note_owners[name] = owner
        for name in _references(block, "protected"):
            protected_users.setdefault(name, set()).add(owner)
    for note in draft["notes"]:
        owner = note_owners.get(note["id"])
        if owner is None:
            raise ValueError(f"Draft note {note['id']} has no callout owner")
        specifications[owner]["owned_note_ids"].append(note["id"])
        for name in _references(note, "protected"):
            protected_users.setdefault(name, set()).add(owner)
    for name in protected_users:
        if name not in declarations["protected"]:
            raise ValueError(f"Draft references missing protected declaration {name}")
    for item in draft["protected"]:
        users = protected_users.get(item["id"], {unit_specs[0]["unit_id"]})
        specifications[min(users)]["owned_protected_ids"].append(item["id"])
    metadata_owner = block_owners.get(draft.get("main_body_start"), unit_specs[0]["unit_id"])
    pdf_page_ids = _review_ownership(job, unit_specs, block_owners, note_owners, metadata_owner) if role == "review" else []
    page_records = {}
    for page in pages:
        image = page.get("image")
        if not image or not _path(job, image).is_file():
            raise ValueError(f"Source page {page['id']} lacks a readable inspection image")
        destination = directory / "pages" / f"{page['id']}.json"
        _write_once(destination, page)
        page_records[page["id"]] = {"page_id": page["id"], "locator": page["locator"],
            "evidence": _relative(job, destination), "evidence_sha256": _hash(destination),
            "image": image, "image_sha256": _hash(_path(job, image)),
            "raster_region_count": len(page.get("image_regions", []))}
    for spec in unit_specs:
        blocks = [declarations["blocks"][name] for name in spec["owned_block_ids"]]
        notes = [declarations["notes"][name] for name in spec["owned_note_ids"]]
        context_blocks = [block for block in draft["blocks"] if block["id"] not in spec["owned_block_ids"]
                          and set(block["source_pages"]) & set(spec["owned_pages"])]
        context_note_ids = {name for block in context_blocks for name in _references(block, "note")}
        context_notes = [note for note in draft["notes"] if note["id"] in context_note_ids]
        references = set()
        context = set()
        for block in blocks:
            context.update(block["source_pages"])
            references.update(_references(block, "protected"))
        for note in notes:
            references.update(_references(note, "protected"))
            context.update(item["source_page"] for item in note.get("source_evidence", []))
            if note.get("restoration"):
                context.add(note["restoration"]["source_page"])
        for block in context_blocks:
            context.update(block["source_pages"])
        for note in context_notes:
            context.update(item["source_page"] for item in note.get("source_evidence", []))
            if note.get("restoration"):
                context.add(note["restoration"]["source_page"])
        # Immediate seams are inspectable without granting ownership of neighbors.
        first, last = page_order[spec["owned_pages"][0]], page_order[spec["owned_pages"][-1]]
        context.update(page_ids[max(0, first - 1):first])
        context.update(page_ids[last + 1:last + 2])
        if spec["unit_id"] == metadata_owner:
            context.add(page_ids[0])
        if any(page not in page_order for page in context):
            raise ValueError("Draft note refers to an unknown original page")
        context.difference_update(spec["owned_pages"])
        if len(context) > max_context_pages:
            raise ValueError(f"Unit {spec['unit_id']} needs {len(context)} context pages, exceeding declared bound {max_context_pages}; explicitly replan")
        referenced = references | set(spec["owned_protected_ids"])
        packet = {"version": 1, "kind": "book-unit-packet", "role": role, "unit_id": spec["unit_id"],
            "plan_id": identifier, "source_file_sha256": data["source_sha256"],
            "owned_pages": spec["owned_pages"], "context_pages": sorted(context, key=page_order.__getitem__),
            "pages": [page_records[name] for name in spec["owned_pages"] + sorted(context, key=page_order.__getitem__)],
            "owned_block_ids": spec["owned_block_ids"], "owned_note_ids": spec["owned_note_ids"],
            "owned_protected_ids": spec["owned_protected_ids"],
            "shared_protected_ids": sorted(name for name in referenced if len(protected_users.get(name, set())) > 1),
            "blocks": blocks, "notes": notes,
            "context_blocks": context_blocks,
            "context_block_owners": {block["id"]: block_owners[block["id"]] for block in context_blocks},
            "outgoing_block_ids": [block["id"] for block in blocks if set(block["source_pages"]) - set(spec["owned_pages"])],
            "protected": [item for item in draft["protected"] if item["id"] in referenced],
            "metadata_owner": spec["unit_id"] == metadata_owner,
            "metadata": {"title": draft["title"], "main_body_start": draft.get("main_body_start")},
            "outline": [{"id": item["id"], "source_pages": item["source_pages"], "source": item["source"]}
                        for item in draft["blocks"] if item.get("kind") == "heading"],
            "warnings": [warning for warning in extraction.get("warnings", [])
                         if warning.split(":", 1)[0] not in page_order or warning.split(":", 1)[0] in spec["owned_pages"]],
            "draft_is_untrusted": role == "source"}
        packet["context_notes"] = context_notes
        packet["context_note_owners"] = {note["id"]: note_owners[note["id"]] for note in context_notes}
        context_refs = {name for item in context_blocks + context_notes for name in _references(item, "protected")}
        packet["context_protected"] = [item for item in draft["protected"] if item["id"] in context_refs]
        packet["source_assets"] = {name: _hash(_path(job, name)) for name in
            _asset_names({"blocks": blocks + packet["context_blocks"], "notes": notes + packet["context_notes"]})}
        if role in {"translation", "review"}:
            packet["terms"] = {"path": "terms.json", "sha256": baseline["terms.json"]}
            packet["handoff"] = {"path": "handoff.md", "sha256": baseline["handoff.md"]}
        if role == "review":
            packet.update(build=build, pdf="build/book.pdf", pdf_pages=spec["pdf_pages"],
                          context_pdf_pages=spec["context_pdf_pages"], source_unit_id=spec["source_unit_id"])
            packet["round"] = data["round"]
        packet_path = directory / "packets" / f"{spec['unit_id']}.json"
        _write_once(packet_path, packet)
        spec.update(packet=_relative(job, packet_path), packet_sha256=_hash(packet_path),
                    result=_relative(job, directory / "results" / f"{spec['unit_id']}.json"),
                    assets_dir=_relative(job, directory / "assets" / spec["unit_id"]),
                    checkpoint=_relative(job, directory / "checkpoints" / f"{spec['unit_id']}.json"))
    plan = {"version": 1, "kind": "book-unit-plan", "plan_id": identifier, "role": role,
            "job_path": str(job), "job_sha256": _hash(job / "job.json"),
            "base_state": data["state"], "base_round": data["round"], "revision": revise,
            "selected_model": data["models"][role], "source_file_sha256": data["source_sha256"],
            "source_digest": (job / "source.sha256").read_text(encoding="ascii").strip() if sealed else None,
            "baseline": baseline, "extraction_sha256": extraction_digest,
            "pages_per_unit": pages_per_unit, "max_context_pages": max_context_pages,
            "page_ids": page_ids, "pages": page_records, "metadata_owner": metadata_owner,
            "draft": draft_info, "build": build, "pdf_page_ids": pdf_page_ids, "readiness": readiness,
            "review_artifacts": review_artifacts, "units": unit_specs}
    destination = directory / "plan.json"
    _write_once(destination, plan)
    pointer = {"plan": _relative(job, destination), "plan_sha256": _hash(destination)}
    core.save_json(_path(job, f"units/{role}/active.json"), pointer)
    return {**pointer, "role": role, "units": [item["unit_id"] for item in unit_specs], "pages": len(page_ids)}


def _packet_scope(packet: dict) -> None:
    owned, context = packet["owned_pages"], packet["context_pages"]
    if (not 1 <= len(owned) <= 8 or len(set(owned)) != len(owned)
            or len(context) > 4 or len(set(context)) != len(context) or set(owned) & set(context)
            or Counter(page["page_id"] for page in packet["pages"]) != Counter(owned + context)):
        raise ValueError("Packet does not contain its exact bounded source-page scope")
    if packet["role"] == "review":
        physical, neighbors = packet["pdf_pages"], packet["context_pdf_pages"]
        if (len(physical) > 8 or len(neighbors) > 2
                or any(type(page) is not int or page < 1 for page in physical + neighbors)
                or len(set(physical)) != len(physical) or len(set(neighbors)) != len(neighbors)
                or set(physical) & set(neighbors)):
            raise ValueError("Review packet exceeds its bounded physical PDF page scope")



def unit_binding(job, role: str, unit_id: str, revise: bool | None = None) -> dict:
    job = Path(job).resolve(strict=True)
    plan_path, plan, digest = _current_plan(job, role)
    _stable_context(job, plan)
    if revise is not None and revise is not plan["revision"]:
        raise ValueError("Prepared revision intent differs from active unit plan")
    spec = next((item for item in plan["units"] if item["unit_id"] == unit_id), None)
    if spec is None:
        raise ValueError("Unknown unit in active plan")
    if _path(job, spec["checkpoint"]).exists():
        raise ValueError("Unit is already checkpointed; do not dispatch it again")
    packet = _checked(job, spec["packet"], spec["packet_sha256"])
    _packet_scope(packet)
    return {"plan": _relative(job, plan_path), "plan_sha256": digest,
            **{key: spec[key] for key in ("unit_id", "packet", "packet_sha256", "result", "assets_dir")}}


@lru_cache(maxsize=4)
def _item_validator(category: str):
    schema = core.load_json(Path(core.__file__).resolve().parent.parent / "contracts/book.schema.json")
    definition = {"source_pages": "sourcePage", "blocks": "block", "notes": "note", "protected": "protected"}[category]
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"})



def _items(category: str, items: list) -> None:
    if not isinstance(items, list):
        raise ValueError(f"Unit {category} must be an array")
    validator = _item_validator(category)
    ids = []
    for item in items:
        error = next(validator.iter_errors(item), None)
        if error is not None:
            raise ValueError(f"Unit {category}: {error.message}")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise ValueError(f"Unit {category} IDs are duplicated")


def _inspect(packet: dict, output: dict) -> None:
    entries = output.get("inspection")
    if not isinstance(entries, list) or Counter(item.get("page_id") for item in entries if isinstance(item, dict)) != Counter(packet["owned_pages"]):
        raise ValueError("Every owned original page needs exactly one inspection entry")
    pages = {page["page_id"]: page for page in packet["pages"]}
    semantic = {}
    body = output.get("blocks", []) + packet.get("context_blocks", [])
    for item in body:
        if any(token.get("text", "").strip() for token in item.get("source", [])):
            semantic[item["id"]] = set(item["source_pages"])
    for note in output.get("notes", []) + packet.get("context_notes", []):
        if any(token.get("text", "").strip() for token in note.get("source", [])):
            semantic[note["id"]] = {block_page for block in body if note["id"] in _references(block, "note")
                                    for block_page in block["source_pages"]}
    for entry in entries:
        page = pages[entry["page_id"]]
        if (entry.get("image_sha256") != page["image_sha256"] or entry.get("findings") != []
                or entry.get("protected_checked") is not True):
            raise ValueError(f"Page {entry['page_id']} is uninspected, changed, or has unresolved findings")
        if packet["role"] != "source":
            continue
        regions = entry.get("regions", [])
        if (not isinstance(regions, list) or any(not isinstance(item, dict) or type(item.get("index")) is not int for item in regions)
                or Counter(item["index"] for item in regions) != Counter(range(page["raster_region_count"]))):
            raise ValueError(f"Page {entry['page_id']} lacks complete raster-region classification")
        for region in regions:
            if region.get("classification") not in {"prose", "nonprose", "mixed", "blank"}:
                raise ValueError("Invalid source raster-region classification")
            if region["classification"] in {"prose", "mixed"} and not any(
                    entry["page_id"] in semantic.get(name, set()) for name in region.get("semantic_ids", [])):
                raise ValueError("Prose-bearing raster requires transcribed semantics on its actual source page")


def _validate_result(job: Path, packet: dict, output: dict, binding: dict) -> dict:
    _packet_scope(packet)
    expected = f"{packet['role']}-unit-result"
    if (output.get("version") != 1 or output.get("kind") != expected or output.get("unit_id") != packet["unit_id"]
            or output.get("packet_sha256") != binding["packet_sha256"]):
        raise ValueError("Unit result does not match its immutable packet")
    if packet["role"] == "review":
        allowed = {"version", "kind", "unit_id", "packet_sha256", "inspection", "pdf_inspection", "checks", "findings", "evidence", "verdict"}
        if set(output) - allowed:
            raise ValueError("Review unit result has unsupported authoring fields")
        _inspect(packet, output)
        inspected = output.get("pdf_inspection")
        if (not isinstance(inspected, list)
                or Counter(item.get("page") for item in inspected if isinstance(item, dict)) != Counter(packet["pdf_pages"])
                or any(not isinstance(item, dict) or type(item.get("page")) is not int for item in inspected)
                or any(not isinstance(item.get("evidence"), str) or not item["evidence"].strip() for item in inspected)):
            raise ValueError("Review unit must inspect exactly every owned physical PDF page")
        report = {"version": 1, "round": packet["round"], **packet["build"],
                  **{key: output.get(key) for key in ("verdict", "checks", "findings", "evidence")}}
        report.pop("verification_sha256")
        core.validate_document("review", report)
        should_pass = all(output["checks"].values()) and not output["findings"]
        if (output["verdict"] == "pass") != should_pass:
            raise ValueError("Review verdict must agree with checks and all findings")
        if any(not item["id"].startswith(packet["unit_id"] + "_") for item in output["findings"]):
            raise ValueError("Review finding IDs must use their unit_id_ namespace")
        return {}
    allowed = {"version", "kind", "unit_id", "packet_sha256", "blocks", "notes", "metadata", "inspection"}
    if packet["role"] == "source":
        allowed |= {"source_pages", "protected", "body_start"}
    if set(output) - allowed:
        raise ValueError("Unit result has unsupported fields")
    if packet["metadata_owner"] != ("metadata" in output):
        raise ValueError("Exactly the designated unit must author stage metadata")
    if "metadata" in output:
        fields = {"title", "main_body_start"} if packet["role"] == "source" else _METADATA
        required = {"title", "main_body_start"} if packet["role"] == "source" else {"title", "agent_preface", "human_preface"}
        if packet["role"] == "source" and packet["metadata"].get("main_body_start") is None:
            required = {"title"}
        if not isinstance(output["metadata"], dict) or set(output["metadata"]) - fields or not required <= set(output["metadata"]):
            raise ValueError("Unit stage metadata is incomplete or unsupported")
    _inspect(packet, output)
    if packet["role"] == "source":
        for category in ("source_pages", "blocks", "notes", "protected"):
            _items(category, output.get(category))
        if Counter(item["id"] for item in output["source_pages"]) != Counter(packet["owned_pages"]):
            raise ValueError("Source result must conserve exactly its owned original page records")
        pages = {item["page_id"]: item for item in packet["pages"]}
        for page in output["source_pages"]:
            if page["locator"] != pages[page["id"]]["locator"]:
                raise ValueError("Source result changed an original page locator")
        original_blocks = {item["id"]: item for item in packet["blocks"]}
        produced_blocks = {item["id"]: item for item in output["blocks"]}
        if "body_start" in output:
            candidate = output["body_start"]
            if not isinstance(candidate, str) or candidate not in produced_blocks or produced_blocks[candidate]["kind"] == "blank":
                raise ValueError("Declared body_start must reference this unit's own nonblank source block")
        metadata_candidate = output.get("metadata", {}).get("main_body_start")
        if metadata_candidate is not None and (not isinstance(metadata_candidate, str)
                or metadata_candidate not in produced_blocks or produced_blocks[metadata_candidate]["kind"] == "blank"):
            raise ValueError("Source metadata main_body_start must name the metadata owner's returned nonblank block")
        for name in packet.get("outgoing_block_ids", []):
            if name not in produced_blocks or produced_blocks[name]["source_pages"] != original_blocks[name]["source_pages"]:
                raise ValueError("Existing outgoing source block/span must survive intact; explicitly replan structural changes")
        for block in output["blocks"]:
            if block["source_pages"][0] not in packet["owned_pages"] or not set(block["source_pages"]) <= set(pages):
                raise ValueError("Source block crosses unit ownership or unprepared context")
            if set(block["source_pages"]) - set(packet["owned_pages"]):
                original_block = original_blocks.get(block["id"])
                if original_block is None or block["source_pages"] != original_block["source_pages"]:
                    raise ValueError("New cross-unit source structure needs explicit replanning; result remains unconsumed")
        original = {item["id"]: item for item in packet["protected"]}
        produced = {item["id"]: item for item in output["protected"]}
        readonly = (set(original) - set(packet["owned_protected_ids"])) | set(packet["shared_protected_ids"])
        if any(produced.get(name) != original[name] for name in readonly):
            raise ValueError("Shared/non-owned protected definitions are read-only; replan repairs")
        for category in ("blocks", "notes", "protected"):
            existing = set(packet[f"owned_{'block' if category == 'blocks' else 'note' if category == 'notes' else 'protected'}_ids"])
            if category == "protected":
                existing |= readonly
            for item in output[category]:
                if item["id"] not in existing and not item["id"].startswith(packet["unit_id"] + "_"):
                    raise ValueError("New source IDs must use their unit_id_ namespace")
        assets = {}
        allowed_assets = _asset_names({"blocks": packet["blocks"], "notes": packet["notes"]})
        for name in _asset_names(output):
            if name not in allowed_assets and not _path(job, name).is_relative_to(_path(job, binding["assets_dir"])):
                raise ValueError("New source assets must be in the assigned unit assets directory")
            assets[name] = _hash(_path(job, name))
        return assets
    terms = core.load_json(job / "terms.json")
    terminology = {item["id"]: item for item in terms["terms"]}
    for category in ("blocks", "notes"):
        supplied = output.get(category)
        if not isinstance(supplied, list) or Counter(item.get("id") for item in supplied if isinstance(item, dict)) != Counter(packet[f"owned_{'block' if category == 'blocks' else 'note'}_ids"]):
            raise ValueError(f"Translation result must cover exactly its owned {category}")
        originals = {item["id"]: item for item in packet[category]}
        for item in supplied:
            fields = {"id", "target", "fit"} if category == "blocks" else {"id", "target"}
            if set(item) - fields or "target" not in item:
                raise ValueError("Translation unit may change only target arrays and block fit")
            original = originals[item["id"]]
            candidate = {**original, **item}
            _items(category, [candidate])
            if "fit" in item and original["kind"] not in {"image", "group"}:
                raise ValueError("Only image/group blocks permit output fit")

            def conserved(tokens, target=False):
                sequence = []
                for token in tokens:
                    key, value = next(iter(token.items()))
                    if key == "text":
                        continue
                    if key == "term":
                        if not target or value not in terminology:
                            raise ValueError("Unknown or source-side terminology token")
                        sequence.extend(("protected", name) for name in terminology[value]["protected_ids"])
                    else:
                        sequence.append((key, value))
                return sequence

            if conserved(original["source"]) != conserved(item["target"], True):
                raise ValueError("Translation changed protected/image/note/page token order or multiplicity")
    return {}


def _packet_inputs(job: Path, packet: dict) -> None:
    for page in packet["pages"]:
        _checked(job, page["evidence"], page["evidence_sha256"])
        if _hash(_path(job, page["image"])) != page["image_sha256"]:
            raise ValueError("Original inspection image changed")
    for name, digest in packet.get("source_assets", {}).items():
        if _hash(_path(job, name)) != digest:
            raise ValueError("Immutable draft/source asset changed")



def task_metadata(value: dict, role: str, selected_model: dict) -> dict:
    """Retain normal settled task metadata as a reference, not execution attestation."""
    selector = core.admit_model(**selected_model)
    if (not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"].strip()
            or value.get("agent") != f"book-{role}" or type(value.get("exitCode")) is not int
            or value["exitCode"] != 0 or value.get("error") or value.get("aborted", False) is not False
            or value.get("resolvedModelIdentity") != selector
            or value.get("resolvedModelIsFallback", False) is not False):
        raise ValueError("Book checkpoint requires a successful settled task on the selected role/model without fallback")
    return {key: value[key] for key in ("id", "agent", "exitCode", "resolvedModelIdentity")} | {
        "resolvedModelIsFallback": False}


def _content_checkpoint(job: Path, plan: dict, plan_name: str, plan_digest: str, spec: dict) -> dict:
    packet = _checked(job, spec["packet"], spec["packet_sha256"])
    _packet_inputs(job, packet)
    output = core.load_json(_path(job, spec["result"]))
    assets = _validate_result(job, packet, output, spec)
    return {"version": 1, "kind": "book-unit-checkpoint", "role": plan["role"], "stage": plan["role"],
        "completed": True, **plan["selected_model"], "selector": core.admit_model(**plan["selected_model"]),
        "plan": plan_name, "plan_sha256": plan_digest, "unit_id": spec["unit_id"],
        "packet": spec["packet"], "packet_sha256": spec["packet_sha256"],
        "result": spec["result"], "result_sha256": _hash(_path(job, spec["result"])), "assets": assets,
        "source_file_sha256": plan["source_file_sha256"], "source_digest": plan["source_digest"],
        "base_state": plan["base_state"], "base_round": plan["base_round"], "revision": plan["revision"]}


def checkpoint_unit(job, role: str, unit_id: str, task: dict) -> dict:
    """Checkpoint complete assigned book content without changing global state."""
    job = Path(job).resolve(strict=True)
    plan_path, plan, digest = _current_plan(job, role)
    _stable_context(job, plan)
    spec = next((item for item in plan["units"] if item["unit_id"] == unit_id), None)
    if spec is None:
        raise ValueError("Unknown unit in active plan")
    if _path(job, spec["checkpoint"]).exists():
        raise ValueError("Unit is already checkpointed; do not dispatch it again")
    metadata = task_metadata(task, role, plan["selected_model"])
    checkpoint = _content_checkpoint(job, plan, _relative(job, plan_path), digest, spec)
    checkpoint["task"] = metadata
    checkpoint_path = _path(job, spec["checkpoint"])
    _write_once(checkpoint_path, checkpoint)
    return {**checkpoint, "checkpoint_path": _relative(job, checkpoint_path),
            "checkpoint_sha256": _hash(checkpoint_path)}


def _checkpoint_origin(job: Path, checkpoint: dict, plan: dict) -> None:
    if ("task" in checkpoint) == ("historical_origin" in checkpoint):
        raise ValueError("Book checkpoint needs exactly one task reference or explicit historical origin")
    if "task" in checkpoint:
        task_metadata(checkpoint["task"], plan["role"], plan["selected_model"])
    else:
        origin = checkpoint["historical_origin"]
        if not isinstance(origin, dict) or set(origin) != {"path", "sha256"}:
            raise ValueError("Invalid historical checkpoint origin")
        _checked(job, origin["path"], origin["sha256"])


def import_checkpoints(job, role: str, plan_path) -> dict:
    """Import legacy receipt-bound content, never replay or relabel old execution."""
    job = Path(job).resolve(strict=True)
    plan_path = Path(plan_path).resolve(strict=True)
    if not plan_path.is_relative_to(job / "units" / role):
        raise ValueError("Historical plan must be inside this job's role unit directory")
    legacy_name = _relative(job, plan_path)
    legacy_digest = _hash(plan_path)
    legacy = core.load_json(plan_path)
    if (legacy.get("version") != 1 or legacy.get("kind") != "native-unit-plan"
            or legacy.get("role") != role or role not in _ROLES):
        raise ValueError("Explicit import requires a historical native-unit-plan for this role")
    _stable_context(job, legacy)
    domain_path = plan_path.with_name("book-plan.json")
    domain_name = _relative(job, domain_path)
    domain = {**legacy, "kind": "book-unit-plan", "historical_plan": {"path": legacy_name, "sha256": legacy_digest},
              "units": []}
    imported = []
    for old_spec in legacy["units"]:
        spec = {key: value for key, value in old_spec.items() if key != "receipt"}
        spec["checkpoint"] = _relative(job, plan_path.parent / "checkpoints" / f"{spec['unit_id']}.json")
        domain["units"].append(spec)
        origin_path = _path(job, old_spec["receipt"])
        if not origin_path.exists():
            continue
        receipt = core.load_json(origin_path)
        expected = {"version": 1, "kind": "native-unit-completed", "completed": True, "role": role, "stage": role,
                    "selector": core.admit_model(**legacy["selected_model"]),
                    "plan": legacy_name, "plan_sha256": legacy_digest, "unit_id": spec["unit_id"],
                    **{key: spec[key] for key in ("packet", "packet_sha256", "result")},
                    **legacy["selected_model"],
                    **{key: legacy[key] for key in ("source_file_sha256", "source_digest", "base_state", "base_round", "revision")}}
        if (receipt.get("completed") is not True or type(receipt.get("revision")) is not bool
                or any(receipt.get(key) != value for key, value in expected.items())):
            raise ValueError("Historical completed receipt does not bind this exact planned result/context")
        checkpoint = _content_checkpoint(job, domain, domain_name, "", spec)
        if any(receipt.get(key) != checkpoint[key] for key in ("result_sha256", "assets")):
            raise ValueError("Historical completed result or source assets changed")
        checkpoint["historical_origin"] = {"path": old_spec["receipt"], "sha256": _hash(origin_path)}
        imported.append((spec, checkpoint))
    if not imported:
        raise ValueError("Historical plan contains no receipt-bound completed results to import")

    def publish(path: Path, value: dict) -> None:
        if path.is_symlink() or not path.resolve().is_relative_to(job):
            raise ValueError("Imported checkpoint artifact must stay inside the job without symlinks")
        if path.exists():
            if core.load_json(path) != value:
                raise ValueError("A different imported checkpoint artifact already exists")
        else:
            _write_once(path, value)

    publish(domain_path, domain)
    digest = _hash(domain_path)
    for spec, checkpoint in imported:
        checkpoint["plan_sha256"] = digest
        publish(_path(job, spec["checkpoint"]), checkpoint)
    pointer = {"plan": domain_name, "plan_sha256": digest}
    active = _path(job, f"units/{role}/active.json")
    if not active.exists() or core.load_json(active) != pointer:
        core.save_json(active, pointer)
    return {**status(job, role), "imported": [spec["unit_id"] for spec, _ in imported]}


def _members(job: Path, plan: dict, plan_name: str, plan_digest: str) -> tuple[list, list]:
    checkpoints, outputs = [], []
    _plan_inputs(job, plan)
    if plan.get("historical_plan") is not None:
        origin = plan["historical_plan"]
        _checked(job, origin["path"], origin["sha256"])
    if plan.get("draft") is not None:
        for name, digest in plan["draft"]["assets"].items():
            if _hash(_path(job, name)) != digest:
                raise ValueError("Imported untrusted draft asset identity changed")
    owned = [page for item in plan["units"] for page in item["owned_pages"]]
    complete_source = set(owned) == set(plan["page_ids"]) if plan["role"] == "review" else Counter(owned) == Counter(plan["page_ids"])
    if not complete_source or len(set(plan["page_ids"])) != len(plan["page_ids"]):
        raise ValueError("Unit plan does not cover the exact original source page union")
    if any(not 1 <= len(spec["owned_pages"]) <= 8 or len(set(spec["owned_pages"])) != len(spec["owned_pages"])
           for spec in plan["units"]):
        raise ValueError("Unit source-page scope exceeds its declared bound")
    if plan["role"] == "review":
        if any(len(spec["pdf_pages"]) > 8 or len(spec["context_pdf_pages"]) > 2 for spec in plan["units"]):
            raise ValueError("Review plan exceeds bounded physical PDF page scope")
        pdf_owned = [page for item in plan["units"] for page in item["pdf_pages"]]
        if Counter(pdf_owned) != Counter(plan["pdf_page_ids"]):
            raise ValueError("Review unit plan lacks exact complete physical PDF page ownership")
    for spec in plan["units"]:
        checkpoint_path = _path(job, spec["checkpoint"])
        checkpoint = core.load_json(checkpoint_path)
        expected = _content_checkpoint(job, plan, plan_name, plan_digest, spec)
        if checkpoint.get("completed") is not True or any(checkpoint.get(key) != value for key, value in expected.items()):
            raise ValueError("Unit checkpoint differs from its complete current result/context")
        _checkpoint_origin(job, checkpoint, plan)
        checkpoints.append({"path": spec["checkpoint"], "sha256": _hash(checkpoint_path)})
        outputs.append(core.load_json(_path(job, spec["result"])))
    return checkpoints, outputs


def _merge(job: Path, plan: dict, outputs: list) -> dict:
    metadata = next(output["metadata"] for output in outputs if output["unit_id"] == plan["metadata_owner"])
    if plan["role"] == "translation":
        book = core.load_json(job / "book-source.json")
        for category in ("blocks", "notes"):
            patches = {item["id"]: item for output in outputs for item in output[category]}
            for item in book[category]:
                item.update(patches[item["id"]])
        book.update(metadata)
        return book
    candidates = {output["body_start"] for output in outputs if output.get("body_start") is not None}
    if metadata.get("main_body_start") is not None:
        candidates.add(metadata["main_body_start"])
    if len(candidates) != 1:
        raise ValueError("Source assembly requires exactly one verified main-body boundary candidate; inspect missing/conflicting units")
    metadata = {**metadata, "main_body_start": next(iter(candidates))}
    page_order = {name: index for index, name in enumerate(plan["page_ids"])}
    book = {"version": 2, **metadata, "source_pages": [], "blocks": [], "notes": [], "protected": [],
            "agent_preface": [], "human_preface": None}
    for category in ("source_pages", "blocks", "notes", "protected"):
        seen = {}
        for output in outputs:
            for item in output[category]:
                if item["id"] in seen:
                    if category != "protected" or seen[item["id"]] != item:
                        raise ValueError(f"Competing canonical {category} ID {item['id']}")
                    continue
                seen[item["id"]] = item
                book[category].append(item)
        if category == "source_pages":
            book[category].sort(key=lambda item: page_order[item["id"]])
        elif category == "blocks":
            # Stable sort retains authored reading order within each starting page.
            book[category].sort(key=lambda item: page_order[item["source_pages"][0]])
    return book


def _review_report(plan: dict, outputs: list) -> dict:
    checks = {name: all(output["checks"][name] for output in outputs) for name in sorted(_REVIEW_CHECKS)}
    findings = [finding for output in outputs for finding in output["findings"]]
    evidence = []
    for output in outputs:
        evidence.extend(output["evidence"])
        evidence.extend(f"Physical PDF page {item['page']}: {item['evidence']}" for item in output["pdf_inspection"])
        evidence.extend(f"Original source {item['page_id']} image SHA256 {item['image_sha256']} inspected" for item in output["inspection"])
    report = {"version": 1, "round": plan["base_round"],
              "content_digest": plan["build"]["content_digest"], "pdf_sha256": plan["build"]["pdf_sha256"],
              "verdict": "pass" if all(checks.values()) and not findings else "changes_requested",
              "checks": checks, "findings": findings, "evidence": evidence}
    core.validate_document("review", report)
    return report



def assemble_units(job, role: str) -> dict:
    """Publish an exact complete content merge; the caller journals global state."""
    job = Path(job).resolve(strict=True)
    plan_path, plan, digest = _current_plan(job, role)
    _stable_context(job, plan)
    checkpoints, outputs = _members(job, plan, _relative(job, plan_path), digest)
    if role == "review":
        document = _review_report(plan, outputs)
        name = f"reviews/round-{plan['base_round']}.json"
    else:
        document = _merge(job, plan, outputs)
        core.validate_document("book", document)
        terms = core.load_json(job / "terms.json") if role == "translation" else None
        data = _job(job)
        source_language = data["source_language"].replace("_", "-").split("-", 1)[0].casefold()
        target_language = data["target_language"].replace("_", "-").split("-", 1)[0].casefold()
        core._validate_structure(document, job, terms, role == "translation", languages_differ=source_language != target_language)
        if role == "translation" and core._immutable(document) != core._immutable(core.load_json(job / "book-source.json")):
            raise ValueError("Assembled translation changed immutable source")
        name = "book-source.json" if role == "source" else "book.json"
    core.save_json(_path(job, name), document)
    aggregate = {"version": 1, "kind": "unit-role-completed", "execution": "units", "role": role,
        "stage": role, "completed": True, **plan["selected_model"],
        "selector": core.admit_model(**plan["selected_model"]),
        "plan": _relative(job, plan_path), "plan_sha256": digest, "unit_checkpoints": checkpoints,
        "base_state": plan["base_state"], "base_round": plan["base_round"], "revision": plan["revision"],
        "source_file_sha256": plan["source_file_sha256"], "source_digest": plan["source_digest"],
        "merged_document": name, "merged_document_sha256": _hash(_path(job, name)),
        "merged_document_digest": _canonical(document)}
    if role == "source":
        aggregate.update(source_document_sha256=aggregate["merged_document_sha256"],
                         source_snapshot_digest=core.source_snapshot_digest(job))
    elif role == "translation":
        aggregate["content_digest"] = core.content_digest(job)
    else:
        aggregate.update(round=plan["base_round"], review_sha256=aggregate["merged_document_sha256"], **plan["build"])
    return aggregate


def validate_aggregate(job, receipt: dict, role: str | None = None) -> None:
    """Validate complete immutable book content after global state advancement."""
    job = Path(job).resolve(strict=True)
    if receipt.get("execution") != "units" or receipt.get("role") not in _ROLES:
        raise ValueError("Invalid book unit aggregate")
    plan = _checked(job, receipt["plan"], receipt["plan_sha256"])
    if plan.get("kind") != "book-unit-plan" or (role is not None and role != plan["role"]):
        raise ValueError("Aggregate role differs from its book unit plan")
    role = plan["role"]
    if (receipt["role"] != role or receipt.get("base_state") != plan["base_state"]
            or receipt.get("base_round") != plan["base_round"]
            or receipt.get("stage") != role or receipt.get("revision") != plan["revision"]
            or receipt.get("source_file_sha256") != plan["source_file_sha256"]
            or receipt.get("source_digest") != plan["source_digest"]
            or receipt.get("selector") != core.admit_model(**plan["selected_model"])
            or any(receipt.get(key) != plan["selected_model"][key] for key in ("provider", "model"))):
        raise ValueError("Aggregate differs from immutable unit stage context")
    checkpoints, outputs = _members(job, plan, receipt["plan"], receipt["plan_sha256"])
    if receipt.get("unit_checkpoints") != checkpoints:
        raise ValueError("Aggregate member set/order/hash changed")
    if role == "review":
        report = _review_report(plan, outputs)
        name = f"reviews/round-{plan['base_round']}.json"
        if (_review_build(job) != plan["build"] or receipt.get("round") != plan["base_round"]
                or any(receipt.get(key) != value for key, value in plan["build"].items())
                or receipt.get("review_sha256") != _hash(_path(job, name))
                or receipt.get("merged_document") != name
                or receipt.get("merged_document_sha256") != _hash(_path(job, name))
                or receipt.get("merged_document_digest") != _canonical(report)
                or core.load_json(_path(job, name)) != report):
            raise ValueError("Aggregate review differs from exact complete PDF-bound member reports")
        return
    book = _merge(job, plan, outputs)
    name = "book-source.json" if role == "source" else "book.json"
    if (receipt.get("merged_document") != name or receipt.get("merged_document_digest") != _canonical(book)
            or receipt.get("merged_document_sha256") != _hash(job / name)
            or core.load_json(job / name) != book):
        raise ValueError("Canonical manuscript differs from immutable complete member merge")
    if role == "source":
        if receipt.get("source_snapshot_digest") != core.source_snapshot_digest(job):
            raise ValueError("Aggregate source snapshot changed")
    elif receipt.get("content_digest") != core.content_digest(job):
        raise ValueError("Aggregate translated content changed")


def status(job, role: str) -> dict:
    job = Path(job).resolve(strict=True)
    path, plan, digest = _current_plan(job, role)
    admitted, pending = [], []
    for spec in plan["units"]:
        (admitted if _path(job, spec["checkpoint"]).is_file() else pending).append(spec["unit_id"])
    return {"role": role, "plan": _relative(job, path), "plan_sha256": digest,
            "revision": plan["revision"], "base_state": plan["base_state"], "base_round": plan["base_round"],
            "pages": len(plan["page_ids"]), "admitted": admitted, "pending": pending,
            "complete": not pending}
