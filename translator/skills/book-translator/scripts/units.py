"""Durable bounded book work units; only assembly writes canonical manuscripts.

Unit admission deliberately leaves job.json, source seals and global rounds alone.
OMP owns execution. Content checkpoints retain compact task references, not execution
attestation. The controller owns stage transitions, seals, builds and review.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from jsonschema import Draft202012Validator
from PIL import Image

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


def _source_model_change(previous: dict, current: dict) -> dict:
    """Permit explicit future-model choices or targeted initial-source corrections."""
    core.validate_document("job", current)
    selected = current["models"].get("source")
    event = current["history"][-1] if current["history"] else {}
    reopened = event.get("reopened", [])
    if (not isinstance(reopened, list) or any(not isinstance(unit, str) or not unit for unit in reopened)
            or len(set(reopened)) != len(reopened)):
        raise ValueError("Reopened source units must be a list of unique nonempty unit IDs")
    if (previous.get("state") != "extracted" or current.get("state") != "extracted"
            or previous.get("round") != 0 or current.get("round") != 0
            or not isinstance(selected, dict)
            or any(current["models"].get(role) != selected for role in ("source", "terminology", "translation", "review"))
            or (selected == previous["models"].get("source") and not reopened)
            or {key: value for key, value in previous.items() if key not in {"models", "history"}}
                != {key: value for key, value in current.items() if key not in {"models", "history"}}
            or len(current["history"]) != len(previous["history"]) + 1
            or current["history"][:-1] != previous["history"]):
        raise ValueError("Source continuation requires changed future models or explicit completed units at extracted round 0")
    selector = core.admit_model(**selected)

    if event.get("event") != "source_model_continued" or event.get("selector") != selector:
        raise ValueError("Source continuation requires its explicit model-choice history event")
    return selected


def _translation_replan_context(plan: dict, previous: dict, *, allow_same_bound: bool = False) -> None:
    unchanged = ("role", "job_path", "job_sha256", "base_state", "base_round", "revision", "selected_model",
                 "source_file_sha256", "source_digest", "baseline", "extraction_sha256", "page_ids", "pages",
                 "max_context_pages", "draft", "build", "pdf_page_ids", "readiness", "review_artifacts")
    if (plan.get("role") != "translation" or previous.get("kind") != "book-unit-plan"
            or plan.get("base_state") not in {"terminology_ready", "changes_requested"}
            or plan.get("revision") is not False or plan.get("source_digest") is None
            or type(plan.get("pages_per_unit")) is not int or type(previous.get("pages_per_unit")) is not int
            or not 1 <= plan["pages_per_unit"] <= previous["pages_per_unit"] <= 8
            or (plan["pages_per_unit"] == previous["pages_per_unit"] and not allow_same_bound)
            or any(plan.get(name) != previous.get(name) for name in unchanged)):
        raise ValueError("Translation plan changed bound book/model/readiness inputs or its permitted page-bound relation")


def _plan_inputs(job: Path, plan: dict) -> None:
    if plan.get("job_path") != str(job):
        raise ValueError("Unit plan belongs to a different absolute job")
    if core.extraction_identity(job) != plan["extraction_sha256"]:
        raise ValueError("Extraction changed after unit planning; create a new plan")
    draft = plan.get("draft")
    if draft is not None:
        _checked(job, draft["snapshot"], draft["snapshot_sha256"])
    continuation = plan.get("continuation")
    if continuation is not None:
        if plan["role"] != "source" or plan["revision"] or plan["source_digest"] is not None:
            raise ValueError("Model continuation applies only to initial unsealed source units")
        previous_plan = _checked(job, continuation["plan"], continuation["plan_sha256"])
        previous = continuation["previous_job"]
        future = continuation["job_snapshot"]
        previous_job = _checked(job, previous["path"], previous["sha256"])
        future_job = _checked(job, future["path"], future["sha256"])
        if (previous_plan.get("job_sha256") != previous["sha256"] or plan["job_sha256"] != future["sha256"]
                or _source_model_change(previous_job, future_job) != plan["selected_model"]
                or continuation.get("reopened", []) != future_job["history"][-1].get("reopened", [])):
            raise ValueError("Source continuation job snapshots do not match their immutable plans")
    pending_replan = plan.get("pending_replan")
    if pending_replan is not None:
        if not isinstance(pending_replan, dict) or set(pending_replan) != {"plan", "plan_sha256"}:
            raise ValueError("Invalid pending translation replan link")
        previous = _checked(job, pending_replan["plan"], pending_replan["plan_sha256"])
        _translation_replan_context(plan, previous)
    if plan.get("translation_reopen") is not None:
        _reopen_inputs(job, plan, "translation")
    if plan.get("review_reopen") is not None:
        _reopen_inputs(job, plan, "review")
    if plan.get("source_revision") is not None:
        _source_revision_inputs(job, plan)
    if plan.get("source_rebase") is not None:
        _source_rebase_inputs(job, plan)



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



def _assign_ownership(draft: dict, declarations: dict, unit_specs: list, page_order: dict) -> tuple:
    owners, specifications = {}, {}
    for spec in unit_specs:
        if spec["unit_id"] in specifications:
            raise ValueError("Unit IDs must be unique")
        specifications[spec["unit_id"]] = spec
        owned = spec["owned_pages"]
        if not owned or len(owned) > 8 or any(page not in page_order or page in owners for page in owned):
            raise ValueError("Unit ownership does not cover the exact original source page union")
        positions = [page_order[page] for page in owned]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("Unit owned pages must be contiguous in original source order")
        owners.update({page: spec["unit_id"] for page in owned})
    if set(owners) != set(page_order):
        raise ValueError("Unit ownership does not cover the exact original source page union")
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
        first_owner = min(users, key=lambda unit_id: page_order[specifications[unit_id]["owned_pages"][0]])
        specifications[first_owner]["owned_protected_ids"].append(item["id"])
    metadata_owner = block_owners.get(draft.get("main_body_start"), unit_specs[0]["unit_id"])
    return block_owners, note_owners, protected_users, metadata_owner


def _translation_ownership(draft: dict, declarations: dict, plan: dict, page_order: dict) -> tuple:
    expected = [{"unit_id": spec["unit_id"], "owned_pages": spec["owned_pages"], "owned_block_ids": [],
                 "owned_note_ids": [], "owned_protected_ids": []} for spec in plan["units"]]
    ownership = _assign_ownership(draft, declarations, expected, page_order)
    if (ownership[3] != plan["metadata_owner"]
            or any(any(check[key] != original[key] for key in
                       ("owned_block_ids", "owned_note_ids", "owned_protected_ids"))
                   for check, original in zip(expected, plan["units"]))):
        raise ValueError("Active translation plan differs from canonical block/note/protected ownership")
    return ownership


def _prepare_pending_translation(job: Path, pages_per_unit: int, max_context_pages: int,
                                 readiness: dict, *, reduce_pending: bool = True) -> tuple[dict, dict, dict]:
    path, previous, digest = _current_plan(job, "translation")
    _stable_context(job, previous)
    if (previous["revision"] or previous["source_digest"] is None
            or previous["base_state"] not in {"terminology_ready", "changes_requested"}
            or previous.get("readiness") != readiness or previous["max_context_pages"] != max_context_pages):
        raise ValueError("Pending translation replanning requires unchanged stage readiness and context")
    if (type(previous["pages_per_unit"]) is not int or not 1 <= pages_per_unit <= previous["pages_per_unit"] <= 8
            or (reduce_pending and pages_per_unit == previous["pages_per_unit"])
            or (not reduce_pending and pages_per_unit != previous["pages_per_unit"])):
        raise ValueError("Pending replanning must strictly reduce its bound; reopening must keep the active page bound")
    specs = previous["units"]
    ids = [spec["unit_id"] for spec in specs]
    owned = [page for spec in specs for page in spec["owned_pages"]]
    if (len(set(ids)) != len(ids) or any(not unit.startswith("u") or not unit[1:].isascii() or not unit[1:].isdigit() for unit in ids)
            or len(set(previous["page_ids"])) != len(previous["page_ids"])
            or Counter(owned) != Counter(previous["page_ids"])
            or set(previous["pages"]) != set(previous["page_ids"])):
        raise ValueError("Active translation plan lacks exact unique unit/page ownership")
    carried, origin_plans = {}, {}
    if previous.get("source_rebase") is not None:
        _rebase_context(job, previous, origin_plans)
    for spec in specs:
        packet = _checked(job, spec["packet"], spec["packet_sha256"])
        _packet_scope(packet)
        if (packet.get("role") != "translation" or packet.get("source_file_sha256") != previous["source_file_sha256"]
                or any(packet.get(key) != spec[key] for key in
                       ("unit_id", "owned_pages", "owned_block_ids", "owned_note_ids", "owned_protected_ids"))
                or any(previous["pages"].get(page["page_id"]) != page for page in packet["pages"])):
            raise ValueError("Active translation packet differs from its planned ownership/evidence")
        checkpoint_path = _path(job, spec["checkpoint"])
        if checkpoint_path.exists() or spec.get("carried_checkpoint") is not None:
            _member_checkpoint(job, previous, _relative(job, path), digest, spec, origin_plans)
            carried[spec["unit_id"]] = {**spec, "carried_checkpoint": {
                "path": spec["checkpoint"], "sha256": _hash(checkpoint_path)}}
        else:
            _packet_inputs(job, packet)
    if reduce_pending and len(carried) == len(specs):
        raise ValueError("No pending translation units remain to replan")
    return {"plan": _relative(job, path), "plan_sha256": digest}, previous, carried


def _translation_reopen_ids(value, role: str = "Translation") -> list[str]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(unit, str) or not unit.strip() for unit in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{role} reopening requires unique nonblank string unit IDs")
    return list(value)


def _review_reopen_context(plan: dict, previous: dict) -> None:
    ignored = {"plan_id", "units", "review_reopen"}
    if (plan.get("kind") != "book-unit-plan" or previous.get("kind") != "book-unit-plan"
            or plan.get("role") != "review" or plan.get("base_state") != "translated"
            or type(plan.get("base_round")) is not int or plan["base_round"] < 1
            or plan.get("revision") is not False or plan.get("source_digest") is None
            or type(plan.get("pages_per_unit")) is not int or not 1 <= plan["pages_per_unit"] <= 8
            or plan.get("plan_id") == previous.get("plan_id")
            or any(plan.get(name) is not None for name in
                   ("pending_replan", "translation_reopen", "source_revision", "source_rebase", "continuation"))
            or {key: value for key, value in plan.items() if key not in ignored}
                != {key: value for key, value in previous.items() if key not in ignored}):
        raise ValueError("Review reopening changed its round, bound, authority or frozen inputs")


def _reopen_inputs(job: Path, plan: dict, role: str) -> None:
    label = role.capitalize()
    link = plan[f"{role}_reopen"]
    if (not isinstance(link, dict) or set(link) != {"plan", "plan_sha256", "reopened", "prior_checkpoints"}
            or plan.get("pending_replan") is not None):
        raise ValueError(f"Invalid explicit {role} reopening link")
    reopened = _translation_reopen_ids(link["reopened"], label)
    previous = _checked(job, link["plan"], link["plan_sha256"])
    if role == "translation":
        _translation_replan_context(plan, previous, allow_same_bound=True)
        ignored_plan = {"plan_id", "units", "pending_replan", "translation_reopen", "source_rebase"}
        if (plan["pages_per_unit"] != previous["pages_per_unit"] or plan["base_state"] != "terminology_ready"
                or plan["base_round"] != 0 or plan["plan_id"] == previous["plan_id"]
                or {key: value for key, value in plan.items() if key not in ignored_plan}
                    != {key: value for key, value in previous.items() if key not in ignored_plan}):
            raise ValueError("Translation reopening changed its bound, authority, scope or immutable inputs")
    else:
        _review_reopen_context(plan, previous)
        _plan_inputs(job, previous)
    if ([spec["unit_id"] for spec in plan["units"]] != [spec["unit_id"] for spec in previous["units"]]
            or not isinstance(link["prior_checkpoints"], dict) or set(link["prior_checkpoints"]) != set(reopened)):
        raise ValueError(f"{label} reopening changed its unit order or original checkpoint references")
    originals = {spec["unit_id"]: spec for spec in previous["units"]}
    if len(originals) != len(previous["units"]) or not set(reopened) <= set(originals):
        raise ValueError(f"{label} reopening names an unknown or duplicate prior unit")
    directory = _path(job, f"units/{role}/{plan['plan_id']}")
    for spec in plan["units"]:
        original = originals[spec["unit_id"]]
        if role == "review" and previous.get("review_reopen") is None:
            packet = _checked(job, original["packet"], original["packet_sha256"])
            if packet.get("plan_id") != previous["plan_id"]:
                raise ValueError("Historical review packet lacks typed reopening ancestry")
        ignored = {"carried_checkpoint"}
        if spec["unit_id"] in reopened:
            ignored |= {"result", "assets_dir", "checkpoint"}
            reference = link["prior_checkpoints"][spec["unit_id"]]
            if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
                    or reference["path"] != original["checkpoint"] or "carried_checkpoint" in spec):
                raise ValueError(f"Reopened {role} unit lacks its exact original checkpoint reference")
            prior = _checked(job, reference["path"], reference["sha256"])
            if (prior.get("kind") != "book-unit-checkpoint" or prior.get("completed") is not True
                    or prior.get("role") != role or prior.get("unit_id") != spec["unit_id"]
                    or any(prior.get(key) != original[key] for key in ("packet", "packet_sha256", "result"))):
                raise ValueError(f"Reopened {role} origin is not its completed original unit")
            if role == "review":
                _member_checkpoint(job, previous, link["plan"], link["plan_sha256"], original, {})
            paths = {"result": directory / "results" / f"{spec['unit_id']}.json",
                     "assets_dir": directory / "assets" / spec["unit_id"],
                     "checkpoint": directory / "checkpoints" / f"{spec['unit_id']}.json"}
            if any(spec[key] == original[key] or spec[key] != _relative(job, path) for key, path in paths.items()):
                raise ValueError(f"Only reopened {role} units may receive fresh assigned output paths")
        elif original.get("carried_checkpoint") is not None and spec.get("carried_checkpoint") != original["carried_checkpoint"]:
            raise ValueError(f"Unaffected {role} checkpoint reference changed")
        if ({key: value for key, value in spec.items() if key not in ignored}
                != {key: value for key, value in original.items() if key not in ignored}):
            raise ValueError(f"{label} reopening changed IDs, packet, ownership or unaffected output paths")


def _reopen_translation(job: Path, pages_per_unit: int, max_context_pages: int,
                        readiness: dict, reopen_units: list[str]) -> dict:
    reopened = _translation_reopen_ids(reopen_units)
    data = _job(job)
    if (data["state"] != "terminology_ready" or data["round"] != 0 or data["round"] >= data["max_rounds"]
            or any(event.get("event") in {"translation_content_authored", "stage_translation"} for event in data["history"])):
        raise ValueError("Translation reopening requires initial prebuild terminology_ready round 0 without complete authoring")
    pointer, previous, carried = _prepare_pending_translation(
        job, pages_per_unit, max_context_pages, readiness, reduce_pending=False)
    if any(event.get("unit_plan") == pointer["plan"] for event in data["history"]):
        raise ValueError("Translation plan already consumed; completed authoring cannot be reopened here")
    if not set(reopened) <= set(carried):
        raise ValueError("Only known completed translation checkpoints may be explicitly reopened")
    draft = core.load_json(job / "book-source.json")
    declarations = {name: {item["id"]: item for item in draft[name]} for name in ("blocks", "notes", "protected")}
    _translation_ownership(draft, declarations, previous, {page: index for index, page in enumerate(previous["page_ids"])})
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/translation/{identifier}")
    if directory.exists():
        raise ValueError("Fresh translation reopening directory already exists")
    specs = []
    for original in previous["units"]:
        if original["unit_id"] in reopened:
            spec = {key: value for key, value in original.items() if key != "carried_checkpoint"}
            spec.update(result=_relative(job, directory / "results" / f"{spec['unit_id']}.json"),
                        assets_dir=_relative(job, directory / "assets" / spec["unit_id"]),
                        checkpoint=_relative(job, directory / "checkpoints" / f"{spec['unit_id']}.json"))
        else:
            spec = dict(carried.get(original["unit_id"], original))
        specs.append(spec)
    plan = {key: value for key, value in previous.items() if key not in {"pending_replan", "translation_reopen", "source_rebase"}}
    plan.update(plan_id=identifier, units=specs,
                translation_reopen={**pointer, "reopened": reopened,
                                    "prior_checkpoints": {unit: carried[unit]["carried_checkpoint"] for unit in reopened}})
    _reopen_inputs(job, plan, "translation")
    destination = directory / "plan.json"
    _write_once(destination, plan)
    new_pointer = {"plan": _relative(job, destination), "plan_sha256": _hash(destination)}
    _stable_context(job, previous)
    _plan_inputs(job, plan)
    origins = {}
    for spec in specs:
        if spec.get("carried_checkpoint") is not None:
            _member_checkpoint(job, plan, new_pointer["plan"], new_pointer["plan_sha256"], spec, origins)
    core.save_json(job / "units/translation/active.json", new_pointer)
    return {**new_pointer, "role": "translation", "units": [spec["unit_id"] for spec in specs], "pages": len(plan["page_ids"])}


def _reopen_review(job: Path, pages_per_unit: int, max_context_pages: int,
                   readiness: dict, reopen_units: list[str]) -> dict:
    reopened = _translation_reopen_ids(reopen_units, "Review")
    path, previous, digest = _current_plan(job, "review")
    data = _stable_context(job, previous)
    pointer = {"plan": _relative(job, path), "plan_sha256": digest}
    report_names = (f"reviews/round-{data['round']}.json", f"reviews/round-{data['round']}.receipt.json")
    if (data["state"] != "translated" or not 1 <= data["round"] <= data["max_rounds"]
            or previous["revision"] or previous["base_round"] != data["round"]
            or previous.get("readiness") != readiness or previous["pages_per_unit"] != pages_per_unit
            or previous["max_context_pages"] != max_context_pages
            or any(_path(job, name).exists() for name in report_names)
            or any(value is not None for value in previous.get("review_artifacts", {}).values())
            or any(event.get("unit_plan") == pointer["plan"] for event in data["history"])):
        raise ValueError("Review reopening requires the unchanged current unconsumed translated round before report publication")
    for event in data["history"]:
        if event.get("event") == "role_review":
            receipt = _checked(job, event["receipt"], event["receipt_sha256"])
            if receipt.get("round", receipt.get("base_round")) == data["round"]:
                raise ValueError("The current review round already has a complete reviewer checkpoint")
        if event.get("event") == "review_submitted" and event.get("round") == data["round"]:
            raise ValueError("The current review round was already submitted")
    extraction = core.extraction_inventory(job)
    if extraction is None or [page["id"] for page in extraction["pages"]] != previous["page_ids"]:
        raise ValueError("Review reopening requires the unchanged complete original extraction inventory")
    draft = core.load_json(job / "book.json")
    declarations = {name: {item["id"]: item for item in draft[name]} for name in ("blocks", "notes", "protected")}
    page_ids = previous["page_ids"]
    expected = [{"unit_id": f"u{index + 1:04d}", "owned_pages": page_ids[offset:offset + pages_per_unit],
                 "owned_block_ids": [], "owned_note_ids": [], "owned_protected_ids": []}
                for index, offset in enumerate(range(0, len(page_ids), pages_per_unit))]
    ownership = _assign_ownership(draft, declarations, expected, {page: index for index, page in enumerate(page_ids)})
    physical = _review_ownership(job, expected, ownership[0], ownership[1], ownership[3])
    if (previous["metadata_owner"] != ownership[3] or previous["pdf_page_ids"] != physical
            or len(expected) != len(previous["units"]) or set(previous["pages"]) != set(page_ids)):
        raise ValueError("Review reopening changed canonical ownership, metadata authority or PDF inventory")
    packet_for = _packet_builder(job, "review", draft, declarations, page_ids, extraction, data,
                                 previous["baseline"], previous["build"], max_context_pages)
    carried, origins = {}, {}
    for spec, logical in zip(previous["units"], expected):
        if any(spec.get(key) != value for key, value in logical.items()):
            raise ValueError("Review reopening changed canonical source/block/note/physical-PDF ownership or order")
        packet = _checked(job, spec["packet"], spec["packet_sha256"])
        if (previous.get("review_reopen") is None and packet.get("plan_id") != previous["plan_id"]
                or packet != packet_for(logical, packet["plan_id"], previous["pages"], ownership)):
            raise ValueError("Review packet differs from its typed ancestry or frozen canonical inputs")
        _packet_scope(packet)
        _packet_inputs(job, packet)
        checkpoint = _path(job, spec["checkpoint"])
        if checkpoint.exists() or spec.get("carried_checkpoint") is not None:
            _member_checkpoint(job, previous, pointer["plan"], digest, spec, origins)
            carried[spec["unit_id"]] = {**spec, "carried_checkpoint": _ref(job, checkpoint)}
    if not set(reopened) <= set(carried):
        raise ValueError("Only known completed review checkpoints may be explicitly reopened")
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/review/{identifier}")
    if directory.exists():
        raise ValueError("Fresh review reopening directory already exists")
    specs = []
    for original in previous["units"]:
        if original["unit_id"] in reopened:
            spec = {key: value for key, value in original.items() if key != "carried_checkpoint"}
            spec.update(result=_relative(job, directory / "results" / f"{spec['unit_id']}.json"),
                        assets_dir=_relative(job, directory / "assets" / spec["unit_id"]),
                        checkpoint=_relative(job, directory / "checkpoints" / f"{spec['unit_id']}.json"))
        else:
            spec = dict(carried.get(original["unit_id"], original))
        specs.append(spec)
    plan = {**previous, "plan_id": identifier, "units": specs,
            "review_reopen": {**pointer, "reopened": reopened,
                              "prior_checkpoints": {unit: carried[unit]["carried_checkpoint"] for unit in reopened}}}
    _reopen_inputs(job, plan, "review")
    # Validate every inherited completion before the first write, using its real parent origin.
    for spec in specs:
        if spec.get("carried_checkpoint") is not None:
            _member_checkpoint(job, plan, "", "", spec, origins)
    _stable_context(job, previous)
    destination = directory / "plan.json"
    _write_once(destination, plan)
    new_pointer = {"plan": _relative(job, destination), "plan_sha256": _hash(destination)}
    core.save_json(job / "units/review/active.json", new_pointer)
    return {**new_pointer, "role": "review", "units": [spec["unit_id"] for spec in specs], "pages": len(page_ids)}


def _packet_builder(job: Path, role: str, draft: dict, declarations: dict, page_ids: list,
                    extraction: dict, data: dict, baseline: dict, build, max_context_pages: int):
    page_order = {name: index for index, name in enumerate(page_ids)}
    def packet_for(spec, packet_plan_id, records, packet_ownership):
        block_owners, note_owners, protected_users, metadata_owner = packet_ownership
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
            "plan_id": packet_plan_id, "source_file_sha256": data["source_sha256"],
            "owned_pages": spec["owned_pages"], "context_pages": sorted(context, key=page_order.__getitem__),
            "pages": [records[name] for name in spec["owned_pages"] + sorted(context, key=page_order.__getitem__)],
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
        return packet
    return packet_for


def _ref(job: Path, path: Path) -> dict:
    return {"path": _relative(job, path), "sha256": _hash(path)}


def _bound_bytes(job: Path, reference: dict) -> bytes:
    path = _path(job, reference["path"])
    if not path.is_file() or _hash(path) != reference["sha256"]:
        raise ValueError("Missing or changed frozen book artifact")
    return path.read_bytes()


def _snapshot(job: Path, directory: Path, relative: str, filename: str) -> dict:
    source = _path(job, relative)
    destination = directory / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(source.read_bytes())
    return _ref(job, destination)


def _admitted_artifacts(job: Path, roots: list[dict]) -> dict:
    """Retain hash identities after normal live admission, not historical runtime state."""
    mutable = {"job.json", "book-source.json", "source.sha256", "terms.json", "handoff.md", "book.json"}
    artifacts, followed = {}, set()

    def add(name, digest, follow=False):
        if name in mutable:
            return
        if name in artifacts and artifacts[name] != digest:
            raise ValueError("Conflicting admitted book artifact identities")
        artifacts[name] = digest
        if follow and name not in followed:
            followed.add(name)
            scan(_checked(job, name, digest))

    def scan(value, field=""):
        if isinstance(value, list):
            for item in value:
                scan(item, field)
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            add(value["path"], value["sha256"], field in {"source_receipt", "terminology_receipt", "checkpoint", "base", "unit_checkpoints", "target_checkpoints", "authoring_receipt", "finalization_receipt", "reviewer_receipt", "submitted_review"})
        if isinstance(value.get("plan"), str) and isinstance(value.get("plan_sha256"), str):
            add(value["plan"], value["plan_sha256"], True)
        for name, digest, follow in (("packet", "packet_sha256", True), ("result", "result_sha256", False),
                                     ("snapshot", "snapshot_sha256", False),
                                     ("evidence", "evidence_sha256", False), ("image", "image_sha256", False)):
            if isinstance(value.get(name), str) and isinstance(value.get(digest), str):
                add(value[name], value[digest], follow)
        for name, item in value.items():
            if name in {"assets", "source_assets", "artifacts", "target_drafts"} and isinstance(item, dict):
                for path, digest in item.items():
                    add(path, digest)
            else:
                scan(item, "checkpoint" if field in {"carried", "prior_checkpoints"} else name)

    for root in roots:
        scan(root)
    return artifacts


def _check_admitted_artifacts(job: Path, artifacts: dict) -> None:
    for name, digest in artifacts.items():
        if not _path(job, name).is_file() or _hash(_path(job, name)) != digest:
            raise ValueError("Frozen admitted member/packet/result/asset/evidence changed")


def _strict_ref(job: Path, value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value.get("sha256"), str) or len(value["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in value["sha256"])):
        raise ValueError("Post-review scope requires exact contained path/sha256 references")
    name = value["path"]
    path = _path(job, name)
    if Path(name).as_posix() != name or path != job / name or any(
            parent.is_symlink() for parent in [job / name, *(job / name).parents] if parent.is_relative_to(job)):
        raise ValueError("Post-review reference aliases/symlinks are forbidden")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Post-review reference must be a regular unaliased file")
    _bound_bytes(job, value)
    return value


def _scope_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate post-review scope object key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def _scope_shape(value: object, keys: set, location: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"Invalid closed post-review {location} shape")


def _scope_ids(values: object, location: str, *, nonempty=False) -> list:
    if (not isinstance(values, list) or (nonempty and not values)
            or any(not isinstance(value, str) or not value for value in values)
            or len(set(values)) != len(values)):
        raise ValueError(f"Post-review {location} requires unique nonempty identifiers")
    return values


def _scope_witnesses(job: Path, values: object, *, required=False) -> None:
    if not isinstance(values, list) or (required and not values):
        raise ValueError("Post-review witnesses must be an explicit readonly reference array")
    for value in values:
        _strict_ref(job, value)
    if len({value["path"] for value in values}) != len(values):
        raise ValueError("Duplicate post-review witness reference")


def _source_scope_request(job: Path, request: dict, *, historical=False) -> None:
    _scope_shape(request, {"version", "kind", "submitted_review", "expected_source", "source_changes"}, "request")
    version = request["version"]
    if (type(version) is not int or version not in ({1, 2} if historical else {2})
            or request["kind"] != "post-review-source-scope"):
        raise ValueError("Invalid strict post-review source scope request version; live authority requires version 2")
    for key in ("submitted_review", "expected_source"):
        _strict_ref(job, request[key])
    changes = request["source_changes"]
    if version == 1:
        # Provenance-only interpretation of an already admitted immutable base.
        _scope_shape(changes, {"block_ids", "allowed_fields"}, "historical v1 changes")
        _scope_ids(changes["block_ids"], "historical blocks", nonempty=True)
        fields = _scope_ids(changes["allowed_fields"], "historical fields", nonempty=True)
        if not set(fields) <= {"kind", "source", "label", "list_type", "list_level"}:
            raise ValueError("Unsupported historical post-review structural field")
        return
    _scope_shape(changes, {"block_fields", "deleted_blocks", "block_orders", "page_fields", "added_protected",
                           "removed_protected_ids", "added_notes", "crop_derivations"}, "source_changes")
    for key, eligible in (("block_fields", {"kind", "source", "label", "list_type", "list_level", "asset", "width", "height"}),
                          ("page_fields", {"printed_label", "label_verified", "evidence"})):
        if not isinstance(changes[key], dict) or any(not isinstance(name, str) or not name for name in changes[key]):
            raise ValueError("Post-review field authority must be a per-ID map")
        for fields in changes[key].values():
            if not set(_scope_ids(fields, key, nonempty=True)) <= eligible:
                raise ValueError("Unsupported post-review field authority")
    _scope_ids(changes["removed_protected_ids"], "removed protected IDs")
    for key in ("deleted_blocks", "block_orders", "added_protected", "added_notes", "crop_derivations"):
        if not isinstance(changes[key], list):
            raise ValueError(f"Post-review {key} must be an array")
    for row in changes["deleted_blocks"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid post-review deletion record")
        if row.get("kind") == "redundant-image":
            _scope_shape(row, {"id", "kind", "retained_block_ids"}, "image deletion")
            _scope_ids(row["retained_block_ids"], "retained image representation", nonempty=True)
        elif row.get("kind") == "redundant-ordinary-fragment":
            _scope_shape(row, {"id", "kind", "retained_at"}, "ordinary-fragment deletion")
            if not isinstance(row["retained_at"], list) or not row["retained_at"]:
                raise ValueError("Ordinary deletion requires exact retained destinations")
            for destination in row["retained_at"]:
                if not isinstance(destination, dict) or destination.get("field") not in {"label", "source"}:
                    raise ValueError("Invalid ordinary-fragment destination")
                keys = {"block_id", "field"} | ({"text_token_indexes"} if destination["field"] == "source" else set())
                _scope_shape(destination, keys, "ordinary-fragment destination")
                _scope_ids([destination["block_id"]], "destination block")
                if destination["field"] == "source":
                    indexes = destination["text_token_indexes"]
                    if (not isinstance(indexes, list) or not indexes or any(type(index) is not int or index < 0 for index in indexes)
                            or len(set(indexes)) != len(indexes)):
                        raise ValueError("Ordinary destination needs exact unique text-token indexes")
            if len({_canonical(destination) for destination in row["retained_at"]}) != len(row["retained_at"]):
                raise ValueError("Duplicate ordinary-fragment destination")
        else:
            raise ValueError("Unsupported post-review deletion kind")
        _scope_ids([row["id"]], "deleted block")
    for row in changes["block_orders"]:
        _scope_shape(row, {"unit_id", "block_ids"}, "block order")
        _scope_ids([row["unit_id"]], "order owner")
        _scope_ids(row["block_ids"], "surviving block permutation", nonempty=True)
    for category in ("added_protected", "added_notes"):
        for row in changes[category]:
            keys = {"id", "unit_id", "witnesses"} | ({"callout_block_id"} if category == "added_notes" else set())
            _scope_shape(row, keys, category)
            _scope_ids([row["id"]], "addition ID")
            _scope_ids([row["unit_id"]], "addition owner")
            if category == "added_notes":
                _scope_ids([row["callout_block_id"]], "note callout")
            _scope_witnesses(job, row["witnesses"], required=category == "added_notes")
    refs = [request["submitted_review"], request["expected_source"]]
    for category in ("added_protected", "added_notes"):
        refs.extend(ref for row in changes[category] for ref in row["witnesses"])
    for row in changes["crop_derivations"]:
        _scope_shape(row, {"unit_id", "origin", "use", "input", "rect_px", "output"}, "crop")
        _scope_ids([row["unit_id"]], "crop owner")
        origin, use = row["origin"], row["use"]
        if not isinstance(origin, dict) or not isinstance(use, dict):
            raise ValueError("Invalid crop origin/use")
        if origin.get("kind") == "source-asset" and use.get("kind") == "image-block":
            _scope_shape(origin, {"kind", "block_id"}, "crop origin")
            _scope_shape(use, {"kind", "block_id"}, "crop use")
            _scope_ids([origin["block_id"]], "crop block")
            if use["block_id"] != origin["block_id"]:
                raise ValueError("Crop must retain the same existing image block")
        elif origin.get("kind") == "original-page" and use.get("kind") == "restoration-note":
            _scope_shape(origin, {"kind", "page_id"}, "crop origin")
            _scope_shape(use, {"kind", "note_id", "callout_block_id", "source_page"}, "crop use")
            for name in (origin["page_id"], use["note_id"], use["callout_block_id"], use["source_page"]):
                _scope_ids([name], "restoration crop association")
            if origin["page_id"] != use["source_page"]:
                raise ValueError("Restoration crop must use its exact original source page")
        else:
            raise ValueError("Unsupported crop origin/use pairing")
        for key in ("input", "output"):
            image = row[key]
            _scope_shape(image, {"ref", "width_px", "height_px", "mode"}, "crop raster")
            _strict_ref(job, image["ref"])
            refs.append(image["ref"])
            if (any(type(image[dimension]) is not int or image[dimension] <= 0 for dimension in ("width_px", "height_px"))
                    or not isinstance(image["mode"], str) or not image["mode"]):
                raise ValueError("Crop raster needs exact integer dimensions and decoded mode")
        rect = row["rect_px"]
        if not isinstance(rect, list) or len(rect) != 4 or any(type(value) is not int for value in rect):
            raise ValueError("Crop rectangle must be four exact integers")
    for key, field in (("deleted_blocks", "id"), ("block_orders", "unit_id"), ("added_protected", "id"), ("added_notes", "id")):
        _scope_ids([row[field] for row in changes[key]], key)
    uses = [_canonical(row["use"]) for row in changes["crop_derivations"]]
    outputs = [row["output"]["ref"]["path"] for row in changes["crop_derivations"]]
    if len(set(uses)) != len(uses) or len(set(outputs)) != len(outputs):
        raise ValueError("Duplicate crop use/output declaration")
    identities = {}
    for ref in refs:
        if ref["path"] in identities and identities[ref["path"]] != ref["sha256"]:
            raise ValueError("Conflicting post-review reference hash identities")
        identities[ref["path"]] = ref["sha256"]


def _changed_fields(before: dict, after: dict) -> set:
    return {key for key in before.keys() | after.keys()
            if (key in before) != (key in after) or before.get(key) != after.get(key)}


def _asset_associations(book: dict) -> Counter:
    """Count exact uses, not just filenames; text-token resegmentation is irrelevant."""
    uses = Counter()
    for category in ("blocks", "notes"):
        for item in book.get(category, []):
            def add(kind, asset, geometry=None):
                uses[(category, item["id"], kind, asset, _canonical(geometry))] += 1
            if item.get("kind") == "image":
                add("image-block", item["asset"], {key: item[key] for key in ("width", "height")})
            for image in item.get("images", []):
                add("group-image", image["asset"], image)
            for field in ("source", "target"):
                for token in item.get(field, []):
                    if "image" in token:
                        add(field + "-image", token["image"]["asset"], token["image"])
            for evidence in item.get("source_evidence", []):
                add("source-evidence", evidence["asset"], evidence)
            if item.get("restoration"):
                add("restoration-damage", item["restoration"]["damage_asset"])
    return uses


def _crop_pixels(job: Path, row: dict) -> None:
    before, after = row["input"], row["output"]
    _strict_ref(job, before["ref"])
    _strict_ref(job, after["ref"])
    if before["ref"]["path"] == after["ref"]["path"]:
        raise ValueError("Prepared crop must be a distinct append-only candidate")
    x0, y0, x1, y1 = row["rect_px"]
    width, height = before["width_px"], before["height_px"]
    if (not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height
            or (x0, y0, x1, y1) == (0, 0, width, height)
            or (after["width_px"], after["height_px"]) != (x1 - x0, y1 - y0)
            or after["mode"] != before["mode"]):
        raise ValueError("Prepared crop must be an exact proper in-bounds rectangle with unchanged mode")
    try:
        with Image.open(_path(job, before["ref"]["path"])) as source, Image.open(_path(job, after["ref"]["path"])) as candidate:
            if (getattr(source, "n_frames", 1) != 1 or getattr(candidate, "n_frames", 1) != 1
                    or candidate.format != "PNG" or source.size != (width, height)
                    or candidate.size != (after["width_px"], after["height_px"])
                    or source.mode != before["mode"] or candidate.mode != after["mode"]):
                raise ValueError("Prepared crop decoded format/mode/dimensions changed")
            rectangle = source.crop((x0, y0, x1, y1))
            if (candidate.tobytes() != rectangle.tobytes() or candidate.getpalette() != rectangle.getpalette()
                    or candidate.info.get("transparency") != source.info.get("transparency")):
                raise ValueError("Prepared crop pixels differ from the exact source rectangle")
    except (OSError, SyntaxError) as exc:
        raise ValueError("Prepared crop must decode as an exact raster rectangle") from exc


def _expected_source(job: Path, old: dict, expected: dict, request: dict, plan: dict, reopened: list,
                     *, historical=False) -> None:
    _source_scope_request(job, request, historical=historical)
    changes = request["source_changes"]
    core._validate_structure(expected, job, None, False)
    if request["version"] == 1:
        ids, fields = changes["block_ids"], changes["allowed_fields"]
        if ({key: value for key, value in old.items() if key != "blocks"}
                != {key: value for key, value in expected.items() if key != "blocks"}
                or [item["id"] for item in old["blocks"]] != [item["id"] for item in expected["blocks"]]):
            raise ValueError("Historical expected source changed non-block data or ordered block identities")
        owners = {name: spec["unit_id"] for spec in plan["units"] for name in spec["owned_block_ids"]}
        if not set(ids) <= set(owners) or any(owners[name] not in reopened for name in ids):
            raise ValueError("Historical expected source lies outside admitted source owners")
        actual = {before["id"] for before, after in zip(old["blocks"], expected["blocks"]) if _changed_fields(before, after)}
        if actual != set(ids) or any(not _changed_fields(before, after) <= set(fields)
                                   for before, after in zip(old["blocks"], expected["blocks"])):
            raise ValueError("Historical expected source exceeded its exact narrow authority")
        if core._asset_hashes(job, old) != core._asset_hashes(job, expected):
            raise ValueError("Historical expected source changed asset identity")
        return
    mutable = {"blocks", "source_pages", "protected", "notes"}
    if ({key: value for key, value in old.items() if key not in mutable}
            != {key: value for key, value in expected.items() if key not in mutable}):
        raise ValueError("Expected source changed root metadata outside source authority")
    declarations, canonical_specs, ownership = _logical_layout(old, plan)
    block_owners, note_owners, _, _ = ownership
    page_owners = {page: spec["unit_id"] for spec in plan["units"] for page in spec["owned_pages"]}
    definition_owners = {name: spec["unit_id"] for spec in canonical_specs for name in spec["owned_protected_ids"]}
    selected = set(reopened)
    def owned(owner):
        if owner not in selected:
            raise ValueError("Expected source change lies outside selected existing source owners")
    def fields(category, authority, owners, eligible):
        before = {item["id"]: item for item in old[category]}
        after = {item["id"]: item for item in expected[category]}
        actual = {name: _changed_fields(before[name], after[name]) for name in before.keys() & after.keys()}
        actual = {name: delta for name, delta in actual.items() if delta}
        if set(actual) != set(authority):
            raise ValueError(f"Expected source {category} must have exactly its declared changed IDs")
        for name, delta in actual.items():
            owned(owners[name])
            if delta != set(authority[name]) or not delta <= eligible:
                raise ValueError(f"Expected source {category} exceeded exact per-ID changed-field authority")
    if [page["id"] for page in old["source_pages"]] != [page["id"] for page in expected["source_pages"]]:
        raise ValueError("Expected source changed ordered original page inventory")
    fields("source_pages", changes["page_fields"], page_owners, {"printed_label", "label_verified", "evidence"})
    before, after = declarations["blocks"], {item["id"]: item for item in expected["blocks"]}
    deleted = {row["id"]: row for row in changes["deleted_blocks"]}
    if set(after) - set(before) or set(before) - set(after) != set(deleted):
        raise ValueError("Expected source block membership differs from exact declared deletions")
    fields("blocks", changes["block_fields"], block_owners, {"kind", "source", "label", "list_type", "list_level", "asset", "width", "height"})
    for name, row in deleted.items():
        block = before[name]
        owned(block_owners[name])
        if len(block["source_pages"]) != 1 or name == old["main_body_start"] or block.get("target") != []:
            raise ValueError("Cannot delete a crossing/body-boundary/nonempty-target source block")
        if row["kind"] == "redundant-image":
            if block["kind"] != "image" or block["source"] != []:
                raise ValueError("Redundant image deletion requires an ordinary standalone image without source tokens")
            destinations = row["retained_block_ids"]
        else:
            if (block["kind"] not in {"paragraph", "list_item"} or not block["source"]
                    or any(set(token) != {"text"} for token in block["source"])):
                raise ValueError("Redundant ordinary deletion cannot remove typed semantics/page boundaries")
            destinations = [destination["block_id"] for destination in row["retained_at"]]
        for destination in destinations:
            if (destination not in after or block_owners[destination] != block_owners[name]
                    or after[destination]["source_pages"] != block["source_pages"]):
                raise ValueError("Deletion representation must survive on exactly the same owner/page")
        if row["kind"] == "redundant-ordinary-fragment":
            for destination in row["retained_at"]:
                retained = after[destination["block_id"]]
                if retained["kind"] not in {"paragraph", "list_item", "heading"}:
                    raise ValueError("Ordinary deletion needs a retained ordinary-text representation")
                if destination["field"] == "label":
                    if not isinstance(retained.get("label"), str) or not retained["label"]:
                        raise ValueError("Ordinary deletion destination needs a real retained label")
                elif any(index >= len(retained["source"]) or set(retained["source"][index]) != {"text"}
                         or not retained["source"][index]["text"] for index in destination["text_token_indexes"]):
                    raise ValueError("Ordinary deletion destination must name existing ordinary text tokens")
    orders = {row["unit_id"]: row["block_ids"] for row in changes["block_orders"]}
    sequence = []
    for spec in canonical_specs:
        unit = spec["unit_id"]
        surviving = [name for name in spec["owned_block_ids"] if name not in deleted]
        order = orders.get(unit, surviving)
        if unit in orders:
            owned(unit)
            if set(order) != set(surviving) or order == surviving:
                raise ValueError("Block order must be a real complete surviving same-owner permutation")
        sequence.extend(order)
    if set(orders) - {spec["unit_id"] for spec in plan["units"]} or sequence != [item["id"] for item in expected["blocks"]]:
        raise ValueError("Expected whole block order differs from declared natural-owner permutations")
    additions = {row["id"]: row for row in changes["added_protected"]}
    removals = set(changes["removed_protected_ids"])
    new_defs = {item["id"]: item for item in expected["protected"]}
    if (set(new_defs) - set(declarations["protected"]) != set(additions)
            or set(declarations["protected"]) - set(new_defs) != removals):
        raise ValueError("Expected protected membership differs from declared additions/removals")
    retained = [item for item in old["protected"] if item["id"] not in removals]
    if expected["protected"][:len(retained)] != retained:
        raise ValueError("Retained protected definitions/values/order are immutable")
    for name in removals:
        owned(definition_owners[name])
        if declarations["protected"][name]["kind"] not in {"math", "variable"}:
            raise ValueError("Only globally unused old math/variable definitions may be removed")
        for category in ("blocks", "notes"):
            for item in old[category]:
                references = _references(item, "protected") | {token["protected"] for token in item.get("target", []) if "protected" in token}
                if name in references:
                    owned(block_owners[item["id"]] if category == "blocks" else note_owners[item["id"]])
                    if category == "notes" or (item["id"] not in deleted and "source" not in changes["block_fields"].get(item["id"], [])):
                        raise ValueError("Every removed protected use needs explicit selected content authority")
        if any(name in _references(item, "protected") or any(token.get("protected") == name for token in item.get("target", []))
               for item in expected["blocks"] + expected["notes"]):
            raise ValueError("Removed protected definition still has a global source/target user")
    new_note_rows = {row["id"]: row for row in changes["added_notes"]}
    new_notes = {item["id"]: item for item in expected["notes"]}
    if (set(new_notes) != set(declarations["notes"]) | set(new_note_rows)
            or [item for item in expected["notes"] if item["id"] in declarations["notes"]] != old["notes"]):
        raise ValueError("Old notes/order are immutable; only declared new restoration notes are eligible")
    for name, row in {**additions, **new_note_rows}.items():
        owned(row["unit_id"])
        if not name.startswith(row["unit_id"] + "_"):
            raise ValueError("New source IDs require their selected natural owner's namespace")
    for name, row in additions.items():
        if new_defs[name]["kind"] not in {"math", "variable"}:
            raise ValueError("Only genuinely used math/variable protected additions are allowed")
        consumers = [block_owners[item["id"]] for item in expected["blocks"] if name in _references(item, "protected")]
        consumers += [note_owners[item["id"]] if item["id"] in note_owners else new_note_rows[item["id"]]["unit_id"]
                      for item in expected["notes"] if name in _references(item, "protected")]
        owner_rank = {spec["unit_id"]: index for index, spec in enumerate(plan["units"])}
        if (not consumers or any(owner not in selected for owner in consumers)
                or min(consumers, key=owner_rank.__getitem__) != row["unit_id"]):
            raise ValueError("New definitions must be used by authorized source content with their natural declared owner")
    # Preserve normal merge order, including old note objects in their real owner.
    owner_rank = {spec["unit_id"]: index for index, spec in enumerate(plan["units"])}
    added_order = [item["id"] for item in expected["protected"] if item["id"] in additions]
    if added_order != sorted(added_order, key=lambda name: owner_rank[additions[name]["unit_id"]]):
        raise ValueError("New definitions must follow deterministic normal owner merge order")
    note_order = [owner_rank[note_owners[item["id"]] if item["id"] in note_owners else new_note_rows[item["id"]]["unit_id"]]
                  for item in expected["notes"]]
    if note_order != sorted(note_order):
        raise ValueError("Notes must retain normal natural-owner merge order")
    for name, row in new_note_rows.items():
        note = new_notes[name]
        callout = row["callout_block_id"]
        if (callout not in after or block_owners[callout] != row["unit_id"]
                or "source" not in changes["block_fields"].get(callout, [])
                or sum(token.get("note") == name for token in after[callout]["source"]) != 1
                or note.get("content_type") != "prose" or note.get("target") != []
                or not isinstance(note.get("restoration"), dict) or not note["restoration"]):
            raise ValueError("New notes require a single authorized natural-owner callout and valid prose restoration")
    old_assets = core._asset_hashes(job, old)
    desired = _asset_associations(old)
    for name in deleted:
        desired.subtract(_asset_associations({"blocks": [before[name]]}))
    image_crops = set()
    note_crops = set()
    page_records = plan["pages"]
    for row in changes["crop_derivations"]:
        owned(row["unit_id"])
        _crop_pixels(job, row)
        output_name = row["output"]["ref"]["path"]
        if (output_name in old_assets or output_name in {page["image"] for page in page_records.values()}
                or Path(output_name).parts[0] not in {"work", "evidence"}):
            raise ValueError("Prepared output must be a distinct noncanonical work/evidence candidate")
        if row["origin"]["kind"] == "source-asset":
            name = row["origin"]["block_id"]
            if (name not in before or name not in after or block_owners[name] != row["unit_id"]
                    or before[name]["kind"] != "image" or after[name]["kind"] != "image"
                    or row["input"]["ref"] != {"path": before[name]["asset"], "sha256": old_assets[before[name]["asset"]]}
                    or (before[name]["width"], before[name]["height"]) != (row["input"]["width_px"], row["input"]["height_px"])
                    or after[name]["asset"] != output_name
                    or (after[name]["width"], after[name]["height"]) != (row["output"]["width_px"], row["output"]["height_px"])):
                raise ValueError("Prepared crop differs from its exact old image/owner/geometry association")
            image_crops.add(name)
            desired.subtract({use: count for use, count in _asset_associations({"blocks": [before[name]]}).items()
                              if use[2] == "image-block"})
            desired.update({use: count for use, count in _asset_associations({"blocks": [after[name]]}).items()
                            if use[2] == "image-block"})
        else:
            page_id, use = row["origin"]["page_id"], row["use"]
            name = use["note_id"]
            declaration = new_note_rows.get(name)
            if (page_owners.get(page_id) != row["unit_id"] or declaration is None
                    or declaration["unit_id"] != row["unit_id"] or declaration["callout_block_id"] != use["callout_block_id"]
                    or row["input"]["ref"] != {"path": page_records[page_id]["image"], "sha256": page_records[page_id]["image_sha256"]}
                    or new_notes[name]["restoration"]["source_page"] != page_id
                    or new_notes[name]["restoration"]["damage_asset"] != output_name):
                raise ValueError("Prepared damage crop differs from its exact original-page/restoration association")
            note_crops.add(name)
            if _asset_names({"notes": [new_notes[name]]}) != {output_name}:
                raise ValueError("New restoration imagery must be only its declared supplied-source damage crop")
            images = [token["image"] for token in new_notes[name]["source"] if "image" in token]
            if len(images) != 1:
                raise ValueError("New restoration note requires exactly its one declared damage image")
            desired.update(_asset_associations({"notes": [new_notes[name]]}))
    if note_crops != set(new_note_rows):
        raise ValueError("Every new restoration note requires its exact declared original-page crop")
    for name, fields_list in changes["block_fields"].items():
        if set(fields_list) & {"asset", "width", "height"} and name not in image_crops:
            raise ValueError("Image asset/geometry authority requires its exact declared prepared crop")
    if +desired != _asset_associations(expected):
        raise ValueError("Expected source changed an undeclared asset association")
    expected_assets = core._asset_hashes(job, expected)
    outputs = {row["output"]["ref"]["path"]: row["output"]["ref"]["sha256"] for row in changes["crop_derivations"]}
    if expected_assets != {name: outputs[name] if name in outputs else old_assets[name] for name in _asset_names(expected)}:
        raise ValueError("Expected source asset identities exceed exact prepared outputs")
    if expected == old:
        raise ValueError("Expected source must contain a real declared correction, not a no-op")


def _scope_request(job: Path, path) -> tuple[dict, dict]:
    path = Path(path)
    if path.is_absolute():
        if not path.is_relative_to(job):
            raise ValueError("Post-review scope request must be contained by this job")
        name = path.relative_to(job).as_posix()
    else:
        name = path.as_posix()
    reference = _ref(job, job / name)
    _strict_ref(job, reference)
    request = _scope_json(job / name)
    _source_scope_request(job, request)
    return reference, request

def _frozen_scope_request(job: Path, post: dict) -> dict:
    request = _checked(job, post["scope_request"]["path"], post["scope_request"]["sha256"])
    if isinstance(request, dict) and request.get("version") == 2:
        request = _scope_json(_path(job, post["scope_request"]["path"]))
    if (not isinstance(request, dict) or request.get("submitted_review") != post["submitted_review"]
            or request.get("expected_source", {}).get("sha256") != post["expected_source"]["sha256"]):
        raise ValueError("Frozen post-review scope request changed")
    # The original operator document is not a live dependency after snapshotting.
    request = {**request, "expected_source": post["expected_source"]}
    _source_scope_request(job, request, historical=True)
    return request


def _prepared_references(changes: dict) -> list:
    refs = [ref for key in ("added_protected", "added_notes") for row in changes[key] for ref in row["witnesses"]]
    refs.extend(row[key]["ref"] for row in changes["crop_derivations"] for key in ("input", "output"))
    return refs


def _prepared_source_scope(job: Path, post: dict, unit_id: str) -> dict | None:
    request = _frozen_scope_request(job, post)
    if request["version"] != 2:
        return None
    changes = request["source_changes"]
    witnesses = {}
    for key in ("added_protected", "added_notes"):
        for row in changes[key]:
            if row["unit_id"] == unit_id:
                for ref in row["witnesses"]:
                    witnesses[ref["path"]] = ref
    return {"version": 2, "scope_request": post["scope_request"], "expected_source": post["expected_source"],
            "crop_derivations": [row for row in changes["crop_derivations"] if row["unit_id"] == unit_id],
            "witnesses": list(witnesses.values())}


def _prepared_source_inputs(job: Path, packet: dict) -> dict | None:
    prepared = packet.get("prepared_source_scope")
    if prepared is None:
        return None
    _scope_shape(prepared, {"version", "scope_request", "expected_source", "crop_derivations", "witnesses"}, "prepared source packet")
    if packet["role"] != "source" or type(prepared["version"]) is not int or prepared["version"] != 2:
        raise ValueError("Prepared source authority is only version 2 source context")
    for key in ("scope_request", "expected_source"):
        _strict_ref(job, prepared[key])
    raw = _scope_json(_path(job, prepared["scope_request"]["path"]))
    if raw.get("version") != 2:
        raise ValueError("Prepared source context cannot grant historical v1 authority")
    post = {**prepared, "submitted_review": raw.get("submitted_review")}
    if prepared != _prepared_source_scope(job, post, packet["unit_id"]):
        raise ValueError("Prepared source packet differs from its frozen owner authority")
    expected = _checked(job, prepared["expected_source"]["path"], prepared["expected_source"]["sha256"])
    blocks = {item["id"]: item for item in packet["blocks"]}
    pages = {item["page_id"]: item for item in packet["pages"]}
    for row in prepared["crop_derivations"]:
        _crop_pixels(job, row)
        if row["origin"]["kind"] == "source-asset":
            block = blocks.get(row["origin"]["block_id"])
            if (block is None or block["kind"] != "image"
                    or row["input"]["ref"] != {"path": block["asset"], "sha256": packet["source_assets"][block["asset"]]}):
                raise ValueError("Prepared image input differs from the old canonical owned block")
        else:
            name = row["origin"]["page_id"]
            if (name not in packet["owned_pages"] or row["input"]["ref"] != {
                    "path": pages[name]["image"], "sha256": pages[name]["image_sha256"]}):
                raise ValueError("Prepared restoration input differs from the owned original page")
    return expected


def _admit_post_review(job: Path, data: dict, scope, source: dict, plan: dict, reopened: list) -> dict:
    import translator

    request_ref, request = _scope_request(job, scope)
    expected = _checked(job, request["expected_source"]["path"], request["expected_source"]["sha256"])
    _expected_source(job, source, expected, request, plan, reopened)
    admitted = translator.admit_post_review(job, data, request["submitted_review"])
    if (job / "build").is_symlink() or not (job / "build").is_dir():
        raise ValueError("Post-review build root must be a contained regular directory")
    build_files = {}
    for path in sorted((job / "build").rglob("*")):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ValueError("Post-review build must contain only regular files and directories")
        if path.is_file():
            build_files[_relative(job, path)] = _ref(job, path)
    post = {**admitted, "scope_request": request_ref, "expected_source": request["expected_source"],
            "target_document": _ref(job, job / "book.json"), "build_files": build_files,
            "original_round": data["round"], "original_max_rounds": data["max_rounds"], "derivation_version": 1}
    temporary = {"post_review": post, "target_plan": post["target_plan"]}
    failed, forced = _post_review_feedback(job, temporary, source)
    post.update(failed_review_units=failed, forced_pending=forced)
    return post


def _post_review_feedback(job: Path, base: dict, source: dict) -> tuple[list, dict]:
    """Conservative structured closure; freeform finding locations grant no authority."""
    post = base["post_review"]
    pointer = post["review_plan"]
    review = _checked(job, pointer["plan"], pointer["plan_sha256"])
    receipt = _checked(job, post["reviewer_receipt"]["path"], post["reviewer_receipt"]["sha256"])
    checkpoints, outputs = _members(job, review, pointer["plan"], pointer["plan_sha256"])
    report = _checked(job, post["report"]["path"], post["report"]["sha256"])
    if (receipt.get("unit_checkpoints") != checkpoints or _review_report(review, outputs) != report
            or receipt.get("merged_document_digest") != _canonical(report)):
        raise ValueError("Submitted review differs from its complete immutable member report reassembly")
    target_pointer = base["target_plan"]
    target = _checked(job, target_pointer["plan"], target_pointer["plan_sha256"])
    declarations, _, ownership = _logical_layout(source, target)
    block_owners, note_owners, protected_users, _ = ownership
    all_targets = {spec["unit_id"] for spec in target["units"]}
    verification_ref = post["build_files"].get("build/verification.json")
    if verification_ref is None:
        raise ValueError("Post-review archive lacks exact build verification")
    verification = _checked(job, verification_ref["path"], verification_ref["sha256"])
    physical = [item.get("physical_pdf_page", item.get("page")) for item in verification.get("pages", [])]
    ranges, mapped_blocks, mapped_notes = [], set(), set()
    trustworthy = bool(physical) and physical == list(range(1, len(physical) + 1))
    for category, records, owners in (("blocks", verification.get("block_boundaries", []), block_owners),
                                      ("notes", verification.get("notes", []), note_owners)):
        for row in records:
            start, end = row.get("start", {}).get("page"), row.get("end", {}).get("page")
            valid = row.get("id") in owners and type(start) is int and type(end) is int and 1 <= start <= end <= len(physical)
            if not valid:
                trustworthy = False
                continue
            pages = set(range(start, end + 1))
            if category == "notes":
                callout = row.get("callout", {}).get("page")
                if type(callout) is not int or callout not in physical:
                    trustworthy = False
                else:
                    pages.add(callout)
                mapped_notes.add(row["id"])
            else:
                mapped_blocks.add(row["id"])
            ranges.append((category, row["id"], pages))
    trustworthy &= mapped_blocks == {item["id"] for item in source["blocks"] if item["kind"] != "blank"}
    trustworthy &= mapped_notes == set(note_owners)
    special = set(verification.get("agent_preface_pages", []))
    special.update(row.get("physical_pdf_page", row.get("page")) for row in verification.get("glossary_rows", []))
    mapped_physical = {page for _, _, pages in ranges for page in pages}
    failed, forced = [], {}
    for spec, output in zip(review["units"], outputs):
        bad = {name for name in _REVIEW_CHECKS if output["checks"].get(name) is not True}
        if output["verdict"] != "changes_requested" and not bad and not output["findings"]:
            continue
        unit = spec["unit_id"]
        failed.append(unit)
        packet = _checked(job, spec["packet"], spec["packet_sha256"])
        pdf_pages = set(packet["pdf_pages"] + packet["context_pdf_pages"])
        uncertain = (not trustworthy or packet["metadata_owner"]
                     or spec.get("source_unit_id") == review["metadata_owner"] or not packet["owned_pages"]
                     or bool(bad & {"terminology", "preface"}) or (not bad and bool(output["findings"]))
                     or bool(pdf_pages & special) or not pdf_pages <= set(physical) or not pdf_pages <= mapped_physical)
        pages = set(packet["owned_pages"] + packet["context_pages"])
        blocks = {item["id"] for item in packet["blocks"] + packet.get("context_blocks", [])}
        notes = {item["id"] for item in packet["notes"] + packet.get("context_notes", [])}
        for category, name, physical_pages in ranges:
            if physical_pages & pdf_pages:
                (blocks if category == "blocks" else notes).add(name)
        for item in source["blocks"]:
            if set(item["source_pages"]) & pages or item["id"] in blocks:
                blocks.add(item["id"])
                pages.update(item["source_pages"])
                notes.update(_references(item, "note"))
        users = set()
        for category, names, owners in (("blocks", blocks, block_owners), ("notes", notes, note_owners)):
            for name in names:
                if name not in owners or name not in declarations[category]:
                    uncertain = True
                    continue
                users.add(owners[name])
                for protected in _references(declarations[category][name], "protected"):
                    if protected not in protected_users:
                        uncertain = True
                    users.update(protected_users.get(protected, set()))
        for definition in packet.get("protected", []) + packet.get("context_protected", []):
            users.update(protected_users.get(definition["id"], set()))
        users.update(spec["unit_id"] for spec in target["units"] if set(spec["owned_pages"]) & pages)
        if uncertain or not users:
            users = all_targets
        for target_id in sorted(users):
            forced.setdefault(target_id, []).append(unit)
    if not failed:
        raise ValueError("Submitted changes_requested review has no failed immutable member")
    return failed, forced


def _post_review_base(job: Path, base: dict, source: dict) -> None:
    post = base["post_review"]
    keys = {"scope_request", "expected_source", "original_round", "original_max_rounds", "target_document",
            "authoring_receipt", "finalization_receipt", "submitted_review", "report", "reviewer_receipt", "review_plan",
            "build_files", "failed_review_units", "forced_pending", "derivation_version"}
    if not isinstance(post, dict) or set(post) != keys or type(post.get("derivation_version")) is not int or post["derivation_version"] != 1:
        raise ValueError("Invalid strict admitted post_review source-revision tag")
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    if (old_job["state"] != "changes_requested" or type(post["original_round"]) is not int
            or not 0 < post["original_round"] < post["original_max_rounds"]
            or old_job["round"] != post["original_round"] or old_job["max_rounds"] != post["original_max_rounds"]):
        raise ValueError("Post-review base lost original changes_requested round/cap")
    for key in ("scope_request", "expected_source", "target_document", "authoring_receipt", "finalization_receipt", "submitted_review", "report", "reviewer_receipt"):
        _strict_ref(job, post[key])
    request = _frozen_scope_request(job, post)
    original = _checked(job, base["source_plan"]["plan"], base["source_plan"]["plan_sha256"])
    expected = _checked(job, post["expected_source"]["path"], post["expected_source"]["sha256"])
    _expected_source(job, source, expected, request, original, [spec["unit_id"] for spec in original["units"]], historical=True)
    for reference in post["build_files"].values():
        _strict_ref(job, reference)
    submitted = _checked(job, post["submitted_review"]["path"], post["submitted_review"]["sha256"])
    event = next((item for item in reversed(old_job["history"]) if item.get("event") == "review_submitted"), {})
    report = _checked(job, post["report"]["path"], post["report"]["sha256"])
    reviewer = _checked(job, post["reviewer_receipt"]["path"], post["reviewer_receipt"]["sha256"])
    core.validate_document("review", report)
    if (event.get("round") != old_job["round"] or event.get("verdict") != "changes_requested"
            or {"path": event.get("receipt"), "sha256": event.get("receipt_sha256")} != post["submitted_review"]
            or submitted.get("round") != old_job["round"] or submitted.get("source_digest") != base["source_digest"]
            or report["round"] != old_job["round"] or report["verdict"] != "changes_requested"
            or submitted.get("review_sha256") != post["report"]["sha256"]
            or {"path": submitted.get("reviewer_receipt"), "sha256": submitted.get("reviewer_receipt_sha256")} != post["reviewer_receipt"]
            or {"plan": reviewer.get("plan"), "plan_sha256": reviewer.get("plan_sha256")} != post["review_plan"]
            or reviewer.get("selector") != core.admit_model(**old_job["models"]["review"])
            or any(reviewer.get(key) != old_job["models"]["review"][key] for key in ("provider", "model"))
            or reviewer.get("review_sha256") != post["report"]["sha256"]
            or any(submitted.get(key) != reviewer.get(key) for key in ("content_digest", "pdf_sha256", "verification_sha256"))
            or any(submitted.get(key) != report.get(key) for key in ("content_digest", "pdf_sha256"))
            or post["build_files"]["build/book.pdf"]["sha256"] != submitted.get("pdf_sha256")
            or post["build_files"]["build/verification.json"]["sha256"] != submitted.get("verification_sha256")):
        raise ValueError("Frozen post-review submission/model/report/build authority changed")
    failed, forced = _post_review_feedback(job, base, source)
    if post["failed_review_units"] != failed or post["forced_pending"] != forced:
        raise ValueError("Post-review forced-pending feedback derivation changed")


def _post_review_target(job: Path, base: dict, source: dict, cache: dict) -> tuple[dict, dict]:
    post = base["post_review"]
    pointer = base["target_plan"]
    plan = _checked(job, pointer["plan"], pointer["plan_sha256"])
    proof = _checked(job, post["authoring_receipt"]["path"], post["authoring_receipt"]["sha256"])
    final = _checked(job, post["finalization_receipt"]["path"], post["finalization_receipt"]["sha256"])
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    event = next((item for item in old_job["history"] if item.get("event") == "translation_content_authored"
                  and item.get("receipt") == post["authoring_receipt"]["path"] and item.get("receipt_sha256") == post["authoring_receipt"]["sha256"]), None)
    if event is None:
        raise ValueError("Frozen completed target has no original authoring history")
    import translator

    before = {**old_job, "state": proof["base_state"], "round": proof["base_round"], "history": old_job["history"][:old_job["history"].index(event)]}
    if (proof.get("execution") != "units" or proof.get("authoring_complete") is not True
            or proof.get("kind") != "translation-content-authored" or proof.get("completed") is not False
            or proof.get("job_context_sha256") != translator.translation_context_digest(before)
            or {"plan": proof.get("plan"), "plan_sha256": proof.get("plan_sha256")} != pointer
            or plan["base_round"] != proof["base_round"] or plan["base_state"] != proof["base_state"]
            or proof["base_round"] + 1 != post["original_round"] or final.get("round") != post["original_round"]
            or final.get("authoring_receipt") != post["authoring_receipt"]["path"]
            or final.get("authoring_receipt_sha256") != post["authoring_receipt"]["sha256"]
            or final.get("completed") is not True or final.get("kind") != "translation-completed"
            or plan["selected_model"] != old_job["models"]["translation"]
            or plan["source_digest"] != base["source_digest"] or proof.get("source_digest") != base["source_digest"]
            or any(final.get(key) != proof.get(key) for key in ("plan", "plan_sha256", "unit_checkpoints", "merged_document_digest", "merged_document_sha256", "content_digest"))):
        raise ValueError("Frozen completed target lost original authoring/finalization ancestry")
    checkpoints, outputs = _members(job, plan, pointer["plan"], pointer["plan_sha256"], cache=cache)
    target = _checked(job, post["target_document"]["path"], post["target_document"]["sha256"])
    if (checkpoints != proof["unit_checkpoints"] or checkpoints != [{"path": item["path"], "sha256": item["sha256"]} for item in base["target_checkpoints"]]
            or proof["merged_document_sha256"] != post["target_document"]["sha256"]
            or proof["merged_document_digest"] != _canonical(target) or _merge(job, plan, outputs, source=source) != target):
        raise ValueError("Frozen complete target differs from its exact original native member merge")
    return plan, {spec["unit_id"]: output for spec, output in zip(plan["units"], outputs)}


def _active_post_review(job: Path, data: dict) -> dict | None:
    active = job / "units/source/active.json"
    if not active.is_file():
        return None
    _, plan, _ = _current_plan(job, "source")
    revision = plan.get("source_revision")
    if revision is None:
        return None
    base = _checked(job, revision["base"]["path"], revision["base"]["sha256"])
    if "post_review" not in base:
        return None
    post = base["post_review"]
    if type(post.get("original_round")) is not int:
        raise ValueError("Invalid post-review recovery round")
    if data["round"] > post["original_round"]:
        old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
        completions = []
        for event in data["history"][len(old_job["history"]):]:
            if event.get("event") != "stage_translation":
                continue
            final = _checked(job, event["receipt"], event["receipt_sha256"])
            if final.get("execution") == "units":
                target = _checked(job, final["plan"], final["plan_sha256"])
                if target.get("source_rebase", {}).get("base") == revision["base"]:
                    completions.append(final)
        if (len(completions) != 1 or completions[0].get("kind") != "translation-completed"
                or completions[0].get("completed") is not True
                or completions[0].get("round") != post["original_round"] + 1
                or completions[0].get("base_round") != post["original_round"]
                or data["history"][:len(old_job["history"])] != old_job["history"]
                or data["max_rounds"] != post["original_max_rounds"]):
            raise ValueError("Post-review recovery round changed without its complete finalized rebase")
        _, latest = _journal_ref(job, data, "stage_translation")
        if latest.get("round") != data["round"]:
            raise ValueError("Post-review recovery current round differs from actual finalization")
        return None
    source = _checked(job, base["source"]["path"], base["source"]["sha256"])
    _post_review_base(job, base, source)
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    _same_rebase_intent(old_job, data, post)
    return revision["base"]


def _fresh_post_review_terminology(job: Path, base: dict, task: dict) -> None:
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    for event in old_job["history"]:
        if event.get("event") == "stage_terminology":
            prior = _checked(job, event["receipt"], event["receipt_sha256"])
            if task.get("id") == prior.get("task", {}).get("id"):
                raise ValueError("Post-review terminology must have a genuinely fresh native task, not any historical task replay")


def _post_review_term(job: Path, reference: dict, base: dict, data: dict, term_ref: dict) -> None:
    term = _checked(job, term_ref["path"], term_ref["sha256"])
    _fresh_post_review_terminology(job, base, term.get("task", {}))
    if (term_ref == base["terminology_receipt"] or term.get("bindings", {}).get("post_review_base") != reference
            or data["state"] != "changes_requested" or data["round"] != base["post_review"]["original_round"]):
        raise ValueError("Post-review recovery requires fresh native whole-source terminology bound to its new seal/base")


def _initial_prebuild(data: dict) -> None:
    if (data["state"] != "terminology_ready" or data["round"] != 0 or data["round"] >= data["max_rounds"]
            or any(event.get("event") in {"translation_content_authored", "stage_translation"} for event in data["history"])):
        raise ValueError("Source correction/rebase requires initial unassembled terminology_ready round 0")


def _journal_ref(job: Path, data: dict, event_name: str) -> tuple[dict, dict]:
    event = next((entry for entry in reversed(data["history"]) if entry.get("event") == event_name), None)
    if event is None:
        raise ValueError(f"Missing admitted {event_name} record")
    reference = {"path": event["receipt"], "sha256": event["receipt_sha256"]}
    return reference, _checked(job, reference["path"], reference["sha256"])


def _term_proof(job: Path, data: dict, digest: str, terms: bytes, handoff: bytes, seal_sha256: str) -> tuple[dict, dict]:
    reference, receipt = _journal_ref(job, data, "stage_terminology")
    selected = data["models"]["terminology"]
    if (receipt.get("kind") != "book-role-checkpoint" or receipt.get("role") != "terminology"
            or receipt.get("stage") != "terminology" or receipt.get("completed") is not True
            or receipt.get("source_digest") != digest or receipt.get("source_file_sha256") != data["source_sha256"]
            or not isinstance(receipt.get("bindings"), dict)
            or receipt["bindings"].get("source_seal_sha256") != seal_sha256
            or receipt.get("selector") != core.admit_model(**selected)
            or any(receipt.get(key) != selected[key] for key in ("provider", "model"))
            or receipt.get("terms_sha256") != hashlib.sha256(terms).hexdigest()
            or receipt.get("handoff_sha256") != hashlib.sha256(handoff).hexdigest() or not handoff.strip()):
        raise ValueError("Terminology proof does not bind these exact source/terms/handoff/model artifacts")
    task_metadata(receipt.get("task"), "terminology", selected)
    return reference, receipt


def _old_target_context(job: Path, base: dict, source: dict, cache: dict) -> tuple[dict, dict]:
    if base.get("post_review") is not None:
        return _post_review_target(job, base, source, cache)
    pointer = base["target_plan"]
    plan = _checked(job, pointer["plan"], pointer["plan_sha256"])
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    terms = _bound_bytes(job, base["terms"])
    handoff = _bound_bytes(job, base["handoff"])
    term_reference, _ = _term_proof(job, old_job, base["source_digest"], terms, handoff, base["seal"]["sha256"])
    candidate = base.get("book_candidate")
    if plan["baseline"]["book.json"] != (candidate["sha256"] if candidate is not None else None):
        raise ValueError("Frozen target candidate baseline changed")
    if candidate is not None:
        _bound_bytes(job, candidate)
    if term_reference != base["terminology_receipt"]:
        raise ValueError("Frozen terminology receipt reference changed")
    bindings = {"source_seal_sha256": base["seal"]["sha256"], "terminology_receipt": term_reference["path"],
                "terminology_receipt_sha256": term_reference["sha256"], "terms_sha256": base["terms"]["sha256"],
                "handoff_sha256": base["handoff"]["sha256"]}
    if (plan.get("role") != "translation" or plan.get("kind") != "book-unit-plan"
            or plan["job_sha256"] != base["job"]["sha256"] or plan["base_state"] != "terminology_ready"
            or plan["base_round"] != 0 or plan["source_digest"] != base["source_digest"]
            or plan["selected_model"] != old_job["models"]["translation"]
            or plan["baseline"]["book-source.json"] != base["source"]["sha256"]
            or any(plan["baseline"][name] != base[key]["sha256"] for name, key in
                   (("source.sha256", "seal"), ("terms.json", "terms"), ("handoff.md", "handoff")))
            or plan["readiness"] != {"source_digest": base["source_digest"], "bindings": bindings}):
        raise ValueError("Frozen translation context is not bound to the archived source/terminology/job")
    records = {entry["unit_id"]: entry for entry in base["target_checkpoints"]}
    if len(records) != len(base["target_checkpoints"]):
        raise ValueError("Frozen target checkpoint IDs are duplicated")
    completed = {}
    for spec in plan["units"]:
        reference = records.get(spec["unit_id"])
        if reference is None:
            if _path(job, spec["checkpoint"]).exists():
                raise ValueError("Unfrozen target completion appeared after the source revision snapshot")
            continue
        if reference["path"] != spec["checkpoint"]:
            raise ValueError("Frozen target checkpoint path changed")
        checkpoint = _checked(job, reference["path"], reference["sha256"])
        if (checkpoint.get("completed") is not True or checkpoint.get("role") != "translation"
                or checkpoint.get("unit_id") != spec["unit_id"]
                or any(checkpoint.get(key) != spec[key] for key in ("packet", "packet_sha256", "result"))):
            raise ValueError("Frozen target member differs from its admitted original scope")
        completed[spec["unit_id"]] = _checked(job, checkpoint["result"], checkpoint["result_sha256"])
    if set(completed) != set(records):
        raise ValueError("Frozen target checkpoints do not match the old plan")
    for name, digest in base["target_drafts"].items():
        if _hash(_path(job, name)) != digest:
            raise ValueError("Frozen unadmitted target draft changed")
    return plan, completed


def _archived_source(job: Path, base_reference: dict, cache: dict) -> tuple[dict, dict]:
    key = ("archived-source", base_reference["path"], base_reference["sha256"])
    if key in cache:
        return cache[key]
    base = _checked(job, base_reference["path"], base_reference["sha256"])
    if base.get("version") != 1 or base.get("kind") != "source-revision-base":
        raise ValueError("Invalid source revision archive")
    _check_admitted_artifacts(job, base["artifacts"])
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    source = _checked(job, base["source"]["path"], base["source"]["sha256"])
    seal = _bound_bytes(job, base["seal"]).decode("ascii").strip()
    receipt = _checked(job, base["source_receipt"]["path"], base["source_receipt"]["sha256"])
    pointer = base["source_plan"]
    plan = _checked(job, pointer["plan"], pointer["plan_sha256"])
    proofs = [{"path": spec["checkpoint"], "sha256": base["artifacts"][spec["checkpoint"]]} for spec in plan["units"]]
    if (seal != base["source_digest"] or receipt.get("completed") is not True or receipt.get("role") != "source"
            or receipt.get("execution") != "units" or receipt.get("kind") != "unit-role-completed"
            or receipt.get("plan") != pointer["plan"] or receipt.get("plan_sha256") != pointer["plan_sha256"]
            or receipt.get("unit_checkpoints") != proofs or receipt.get("source_document_sha256") != base["source"]["sha256"]
            or receipt.get("merged_document_sha256") != base["source"]["sha256"]
            or receipt.get("merged_document_digest") != _canonical(source) or receipt.get("source_snapshot_digest") != seal
            or receipt.get("source_file_sha256") != old_job["source_sha256"]
            or receipt.get("selector") != core.admit_model(**old_job["models"]["source"])):
        raise ValueError("Archived canonical source differs from its normally admitted aggregate/member/seal identities")
    core._validate_structure(source, job, None, False)
    if core._source_digest(job, old_job, source) != seal:
        raise ValueError("Archived source seal or immutable source assets changed")
    if base.get("post_review") is not None:
        _post_review_base(job, base, source)
    cache[key] = (base, source)
    return base, source


def _source_revision_context(job: Path, pages_per_unit: int, reopen_units: list[str], *, post_review_scope=None) -> dict:
    reopened = _translation_reopen_ids(reopen_units)
    data = _job(job)
    if post_review_scope is None:
        _initial_prebuild(data)
    elif _active_post_review(job, data) is not None:
        raise ValueError("Post-review source recovery already admitted; resume its exact source plan")
    source = core.validate_book(job, translated=False)
    digest = (job / "source.sha256").read_text(encoding="ascii").strip()
    source_reference, source_receipt = _journal_ref(job, data, "role_source")
    source_pointer, source_plan, source_plan_sha = _current_plan(job, "source")
    pointer = {"plan": _relative(job, source_pointer), "plan_sha256": source_plan_sha}
    if (source_receipt.get("role") != "source" or source_receipt.get("completed") is not True
            or source_receipt.get("plan") != pointer["plan"] or source_receipt.get("plan_sha256") != source_plan_sha
            or source_receipt.get("source_snapshot_digest") != digest
            or source_receipt.get("source_document_sha256") != _hash(job / "book-source.json")
            or source_receipt.get("selector") != core.admit_model(**data["models"]["source"])
            or pages_per_unit != source_plan["pages_per_unit"]
            or not set(reopened) <= {spec["unit_id"] for spec in source_plan["units"]}):
        raise ValueError("Selective source revision requires the current complete sealed source plan at its original bound")
    validate_aggregate(job, source_receipt, "source")
    terms, handoff = (job / "terms.json").read_bytes(), (job / "handoff.md").read_bytes()
    term_reference, _ = _term_proof(job, data, digest, terms, handoff, _hash(job / "source.sha256"))
    target_path, target_plan, target_sha = _current_plan(job, "translation")
    target_readiness = {"source_digest": digest, "bindings": {
        "source_seal_sha256": _hash(job / "source.sha256"), "terminology_receipt": term_reference["path"],
        "terminology_receipt_sha256": term_reference["sha256"], "terms_sha256": _hash(job / "terms.json"),
        "handoff_sha256": _hash(job / "handoff.md")}}
    post = None
    if post_review_scope is not None:
        post = _admit_post_review(job, data, post_review_scope, source, source_plan, reopened)
        if post["target_plan"] != {"plan": _relative(job, target_path), "plan_sha256": target_sha}:
            raise ValueError("Post-review recovery requires the exact completed active target plan")
        post.pop("target_plan")
        proofs = _checked(job, post["authoring_receipt"]["path"], post["authoring_receipt"]["sha256"])["unit_checkpoints"]
        completed = {spec["unit_id"]: {**spec, "carried_checkpoint": next(ref for ref in proofs if ref["path"] == spec["checkpoint"])}
                     for spec in target_plan["units"]}
    else:
        _, _, completed = _prepare_pending_translation(job, target_plan["pages_per_unit"], target_plan["max_context_pages"],
                                                     target_readiness, reduce_pending=False)
    drafts = {}
    for spec in target_plan["units"]:
        if spec["unit_id"] not in completed and _path(job, spec["result"]).is_file():
            drafts[spec["result"]] = _hash(_path(job, spec["result"]))
    roots = [source_reference, term_reference, pointer,
             {"plan": _relative(job, target_path), "plan_sha256": target_sha},
             {"path": data["source_file"], "sha256": data["source_sha256"]}]
    roots.append({"target_checkpoints": [spec["carried_checkpoint"] for spec in completed.values()], "target_drafts": drafts})
    if post is not None:
        roots.extend([{key: post[key]} for key in ("authoring_receipt", "finalization_receipt", "submitted_review", "report", "reviewer_receipt")])
        roots.append(post["review_plan"])
        request = _checked(job, post["scope_request"]["path"], post["scope_request"]["sha256"])
        roots.extend(_prepared_references(request["source_changes"]))
        roots.extend({"terminology_receipt": {"path": event["receipt"], "sha256": event["receipt_sha256"]}}
                     for event in data["history"] if event.get("event") == "stage_terminology")
    artifacts = _admitted_artifacts(job, [{"source_receipt": source_reference, "terminology_receipt": term_reference}, *roots])
    for ref in [source_reference, term_reference, *[spec["carried_checkpoint"] for spec in completed.values()]]:
        artifacts[ref["path"]] = ref["sha256"]
    _check_admitted_artifacts(job, artifacts)
    return {"source": source, "source_digest": digest, "source_receipt": source_reference, "artifacts": artifacts,
            "source_plan": pointer, "old_source_plan": source_plan,
            "terminology_receipt": term_reference,
            "target_plan": {"plan": _relative(job, target_path), "plan_sha256": target_sha},
            "target_checkpoints": [{"unit_id": unit, **spec["carried_checkpoint"]} for unit, spec in completed.items()],
            "target_drafts": drafts, "reopened": reopened, "post_review": post}


def _freeze_source_base(job: Path, directory: Path, context: dict) -> dict:
    base = {"version": 1, "kind": "source-revision-base", "source_digest": context["source_digest"],
            **{key: context[key] for key in ("source_receipt", "source_plan", "terminology_receipt", "target_plan", "target_checkpoints", "target_drafts", "artifacts")}}
    for key, relative, name in (("job", "job.json", "before-job.json"), ("source", "book-source.json", "before-source.json"),
                                ("seal", "source.sha256", "before-source.sha256"), ("terms", "terms.json", "before-terms.json"),
                                ("handoff", "handoff.md", "before-handoff.md")):
        base[key] = _snapshot(job, directory, relative, name)
    if (job / "book.json").is_file():
        base["book_candidate"] = _snapshot(job, directory, "book.json", "before-book.json")
    if context.get("post_review") is not None:
        post = deepcopy(context["post_review"])
        for key, filename in (("scope_request", "scope-request.json"), ("expected_source", "expected-source.json"),
                              ("target_document", "before-complete-target.json")):
            original = post[key]
            post[key] = _snapshot(job, directory, original["path"], filename)
            if post[key]["sha256"] != original["sha256"]:
                raise ValueError("Post-review input changed while freezing")
        post["build_files"] = {name: _snapshot(job, directory, name, "before-build/" + name.removeprefix("build/"))
                               for name in post["build_files"]}
        if any(ref["sha256"] != context["post_review"]["build_files"][name]["sha256"]
               for name, ref in post["build_files"].items()):
            raise ValueError("Post-review build changed while freezing")
        base["post_review"] = post
    path = directory / "revision-base.json"
    _write_once(path, base)
    return _ref(job, path)


def _source_projection(source: dict, packet: dict) -> dict:
    owned_pages = set(packet["owned_pages"])
    blocks = [block for block in source["blocks"] if block["source_pages"][0] in owned_pages]
    note_ids = {note for block in blocks for note in _references(block, "note")}
    protected_ids = set(packet["owned_protected_ids"])
    projection = {"version": 1, "kind": "source-unit-projection", "unit_id": packet["unit_id"],
                  "source_pages": [page for page in source["source_pages"] if page["id"] in owned_pages],
                  "blocks": blocks, "notes": [note for note in source["notes"] if note["id"] in note_ids],
                  "protected": [item for item in source["protected"] if item["id"] in protected_ids]}
    if packet["metadata_owner"]:
        projection["metadata"] = {"title": source["title"], "main_body_start": source["main_body_start"]}
    return projection


def _source_revision_inputs(job: Path, plan: dict) -> tuple[dict, dict]:
    revision = plan["source_revision"]
    if not isinstance(revision, dict) or set(revision) != {"base", "reopened"}:
        raise ValueError("Invalid selective source revision link")
    reopened = _translation_reopen_ids(revision["reopened"])
    base = _checked(job, revision["base"]["path"], revision["base"]["sha256"])
    source = _checked(job, base["source"]["path"], base["source"]["sha256"])
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    original = _checked(job, base["source_plan"]["plan"], base["source_plan"]["plan_sha256"])
    post = base.get("post_review")
    if post is not None:
        _post_review_base(job, base, source)
        if _hash(job / "job.json") == plan["job_sha256"]:
            if _hash(job / "book.json") != post["target_document"]["sha256"]:
                raise ValueError("Admitted complete target changed during post-review source authoring")
            live = {}
            for path in (job / "build").rglob("*"):
                if path.is_symlink():
                    raise ValueError("Admitted build changed to a symlink during source authoring")
                if path.is_file():
                    live[_relative(job, path)] = _hash(path)
            if live != {name: ref["sha256"] for name, ref in post["build_files"].items()}:
                raise ValueError("Admitted build changed during post-review source authoring")
        request = _frozen_scope_request(job, post)
        if request["version"] == 1 and _hash(job / "job.json") == plan["job_sha256"]:
            raise ValueError("Historical version-1 source authority is read-only; no new live execution is admitted")
        expected = _checked(job, post["expected_source"]["path"], post["expected_source"]["sha256"])
        _expected_source(job, source, expected, request, original, reopened, historical=True)
    if (plan["role"] != "source" or plan["revision"] is not True or plan["base_round"] != (post["original_round"] if post is not None else 0)
            or plan["base_state"] != ("changes_requested" if post is not None else "terminology_ready") or plan["job_sha256"] != base["job"]["sha256"]
            or plan["source_digest"] != base["source_digest"] or plan["selected_model"] != old_job["models"]["source"]
            or plan["pages_per_unit"] != original["pages_per_unit"]
            or [(spec["unit_id"], spec["owned_pages"]) for spec in plan["units"]]
                != [(spec["unit_id"], spec["owned_pages"]) for spec in original["units"]]
            or not set(reopened) <= {spec["unit_id"] for spec in original["units"]}
            or plan["baseline"]["book-source.json"] != base["source"]["sha256"]
            or any(plan["baseline"][name] != base[key]["sha256"] for name, key in
                   (("source.sha256", "seal"), ("terms.json", "terms"), ("handoff.md", "handoff")))):
        raise ValueError("Selective source revision changed its frozen scope or original context")
    declarations = {name: {item["id"]: item for item in source[name]} for name in ("blocks", "notes", "protected")}
    _translation_ownership(source, declarations, plan, {page: index for index, page in enumerate(plan["page_ids"])})
    for spec in plan["units"]:
        if (spec["unit_id"] in reopened) == (spec.get("source_carry") is not None) or spec.get("carried_checkpoint") is not None:
            raise ValueError("Source revision may freshly execute only its explicit selected units")
        packet = _checked(job, spec["packet"], spec["packet_sha256"])
        prepared = _prepared_source_scope(job, post, spec["unit_id"]) if post is not None and spec["unit_id"] in reopened else None
        if packet.get("prepared_source_scope") != prepared:
            raise ValueError("Source packet prepared scope differs from frozen selected owner authority")
    return base, source


def _source_carried_member(job: Path, plan: dict, spec: dict, cache: dict) -> tuple[dict, dict]:
    reference = plan["source_revision"]["base"]
    base, source = _archived_source(job, reference, cache)
    carry = spec["source_carry"]
    old_plan = _checked(job, base["source_plan"]["plan"], base["source_plan"]["plan_sha256"])
    old_spec = next(item for item in old_plan["units"] if item["unit_id"] == spec["unit_id"])
    receipt = _checked(job, base["source_receipt"]["path"], base["source_receipt"]["sha256"])
    origin = next(item for item in receipt["unit_checkpoints"] if item["path"] == old_spec["checkpoint"])
    if (set(carry) != {"checkpoint", "projection"} or carry["checkpoint"] != origin
            or spec["checkpoint"] != origin["path"] or spec["result"] != carry["projection"]["path"]):
        raise ValueError("Source projection is not bound to its original aggregate/member")
    packet = _checked(job, spec["packet"], spec["packet_sha256"])
    _packet_inputs(job, packet)
    projection = _checked(job, carry["projection"]["path"], carry["projection"]["sha256"])
    if projection != _source_projection(source, packet):
        raise ValueError("Carried source projection differs from the frozen canonical source")
    return _checked(job, origin["path"], origin["sha256"]), projection


def _source_revision_scope(job: Path, plan: dict, document: dict, cache: dict) -> None:
    base, old = _archived_source(job, plan["source_revision"]["base"], cache)
    if base.get("post_review") is not None:
        expected = _checked(job, base["post_review"]["expected_source"]["path"], base["post_review"]["expected_source"]["sha256"])
        if document != expected:
            raise ValueError("Native complete source candidate differs from the exact expected_source")
    selected = set(plan["source_revision"]["reopened"])
    untouched = {page for spec in plan["units"] if spec["unit_id"] not in selected for page in spec["owned_pages"]}
    if (document["title"] != old["title"] or document["main_body_start"] != old["main_body_start"]
            or [page["id"] for page in document["source_pages"]] != [page["id"] for page in old["source_pages"]]
            or [page["locator"] for page in document["source_pages"]] != [page["locator"] for page in old["source_pages"]]
            or [page for page in document["source_pages"] if page["id"] in untouched]
                != [page for page in old["source_pages"] if page["id"] in untouched]):
        raise ValueError("Source revision changed inventory, metadata or unselected source pages")
    old_blocks = [block for block in old["blocks"] if block["source_pages"][0] in untouched]
    new_blocks = [block for block in document["blocks"] if block["source_pages"][0] in untouched]
    note_ids = {note for block in old_blocks for note in _references(block, "note")}
    if (old_blocks != new_blocks
            or [note for note in old["notes"] if note["id"] in note_ids] != [note for note in document["notes"] if note["id"] in note_ids]):
        raise ValueError("Source revision changed unselected owned blocks or notes")
    if document == old:
        raise ValueError("Selective source revision has no corrected source content to reseal")
    protected_ids = {name for item in old_blocks + [note for note in old["notes"] if note["id"] in note_ids]
                     for name in _references(item, "protected")}
    old_defs = {item["id"]: item for item in old["protected"]}
    new_defs = {item["id"]: item for item in document["protected"]}
    if any(new_defs.get(name) != old_defs[name] for name in protected_ids):
        raise ValueError("Source revision changed a shared definition outside its explicit closure")


def _same_rebase_intent(old: dict, current: dict, post_review: dict | None = None) -> None:
    keys = ("version", "title", "source_language", "target_language", "source_file", "source_sha256", "models", "layout", "max_rounds", "round")
    if (any(old[key] != current[key] for key in keys) or old["round"] != (post_review["original_round"] if post_review is not None else 0)
            or current["history"][:len(old["history"])] != old["history"]):
        raise ValueError("Source rebase changed original evidence/model/language/layout/cap/round or prior history")


def _term_source_names(terms: dict, old: dict, current: dict) -> None:
    before = {item["id"]: item for item in old["protected"]}
    after = {item["id"]: item for item in current["protected"]}
    for term in terms["terms"]:
        for name in term["protected_ids"]:
            if (name not in before or before[name]["kind"] != "name" or after.get(name) != before[name]
                    or before[name]["value"] not in term["source"] or before[name]["value"] not in term["target"]):
                raise ValueError("Unchanged terminology no longer binds the same protected source names")


def _logical_layout(source: dict, plan: dict) -> tuple[dict, list, tuple]:
    declarations = {name: {item["id"]: item for item in source[name]} for name in ("blocks", "notes", "protected")}
    specs = [{"unit_id": spec["unit_id"], "owned_pages": spec["owned_pages"], "owned_block_ids": [],
              "owned_note_ids": [], "owned_protected_ids": []} for spec in plan["units"]]
    ownership = _assign_ownership(source, declarations, specs, {page: index for index, page in enumerate(plan["page_ids"])})
    return declarations, specs, ownership


def _source_footprint(packet: dict, source: dict, canonical: dict) -> str:
    envelope = {"version", "kind", "role", "unit_id", "plan_id", "terms", "handoff"}
    value = {key: item for key, item in packet.items() if key not in envelope}
    for key in ("context_block_owners", "context_note_owners"):
        value[key] = canonical[key]
    page_ids = {page["page_id"] for page in packet["pages"]}
    value["source_page_records"] = [page for page in source["source_pages"] if page["id"] in page_ids]
    return _canonical(value)


def _rebase_view(job: Path, revision_pointer: dict, base_reference: dict, current: dict,
                 acceptance: dict, old_target: dict, cache: dict) -> dict:
    base, old_source = _archived_source(job, base_reference, cache)
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    new_job = _checked(job, current["job"]["path"], current["job"]["sha256"])
    _same_rebase_intent(old_job, new_job, base.get("post_review"))
    new_source = _checked(job, current["source"]["path"], current["source"]["sha256"])
    seal = _bound_bytes(job, current["seal"]).decode("ascii").strip()
    revision = _checked(job, revision_pointer["plan"], revision_pointer["plan_sha256"])
    receipt = _checked(job, current["source_receipt"]["path"], current["source_receipt"]["sha256"])
    _check_admitted_artifacts(job, current["artifacts"])
    proofs = [{"path": spec["checkpoint"], "sha256": current["artifacts"][spec["checkpoint"]]} for spec in revision["units"]]
    if (revision.get("source_revision", {}).get("base") != base_reference or revision["revision"] is not True
            or receipt.get("plan") != revision_pointer["plan"] or receipt.get("plan_sha256") != revision_pointer["plan_sha256"]
            or receipt.get("unit_checkpoints") != proofs or receipt.get("source_document_sha256") != current["source"]["sha256"]
            or receipt.get("source_snapshot_digest") != seal or receipt.get("revision") is not True
            or receipt.get("role") != "source" or receipt.get("completed") is not True
            or receipt.get("kind") != "unit-role-completed" or receipt.get("execution") != "units"
            or receipt.get("merged_document_digest") != _canonical(new_source) or seal == base["source_digest"]):
        raise ValueError("Source rebase lacks the exact completed source revision/aggregate/new snapshot")
    core._validate_structure(new_source, job, None, False)
    _source_revision_scope(job, revision, new_source, cache)
    if core._source_digest(job, new_job, new_source) != seal:
        raise ValueError("Source rebase new seal/source assets changed")
    reseal = next((event for event in reversed(new_job["history"]) if event.get("event") == "source_resealed"), {})
    if (reseal.get("source_digest") != seal or reseal.get("source_receipt") != current["source_receipt"]["path"]
            or reseal.get("source_receipt_sha256") != current["source_receipt"]["sha256"]):
        raise ValueError("Source rebase requires the legitimate explicit reseal journal record")
    terms_before = _bound_bytes(job, base["terms"])
    terms_after = _bound_bytes(job, current["terms"])
    handoff_after = _bound_bytes(job, current["handoff"])
    if terms_before != terms_after:
        raise ValueError("Source rebase requires entire terminology bytes unchanged")
    term_ref, _ = _term_proof(job, new_job, seal, terms_after, handoff_after, current["seal"]["sha256"])
    if (term_ref != current["terminology_receipt"] or acceptance.get("accepted") is not True
            or acceptance.get("handoff_sha256") != current["handoff"]["sha256"]
            or acceptance.get("scope") != ["forms", "meanings", "style", "register", "names", "first_use", "index", "source_quality", "metadata", "preface"]):
        raise ValueError("Source rebase requires explicit acceptance of the exact fresh native handoff compatibility claim")
    if base.get("post_review") is not None:
        _post_review_term(job, base_reference, base, new_job, term_ref)
    terms = core.load_json(_path(job, current["terms"]["path"]))
    _term_source_names(terms, old_source, new_source)
    if (old_source["title"] != new_source["title"] or old_source["main_body_start"] != new_source["main_body_start"]
            or [(page["id"], page["locator"]) for page in old_source["source_pages"]]
                != [(page["id"], page["locator"]) for page in new_source["source_pages"]]):
        raise ValueError("Source rebase changed global title/body/inventory metadata")
    archived_target, completed = _old_target_context(job, base, old_source, cache)
    if archived_target != old_target:
        raise ValueError("Source rebase used a different frozen target plan")
    _packet_inputs(job, {"pages": list(old_target["pages"].values())})
    extraction = core.extraction_inventory(job)
    old_defs, old_specs, old_ownership = _logical_layout(old_source, old_target)
    new_defs, new_specs, new_ownership = _logical_layout(new_source, old_target)
    if old_ownership[3] != old_target["metadata_owner"] or new_ownership[3] != old_target["metadata_owner"]:
        raise ValueError("Source rebase changed translation metadata ownership")
    baseline_before = old_target["baseline"]
    baseline_after = {"terms.json": current["terms"]["sha256"], "handoff.md": current["handoff"]["sha256"]}
    old_builder = _packet_builder(job, "translation", old_source, old_defs, old_target["page_ids"], extraction,
                                  old_job, baseline_before, None, old_target["max_context_pages"])
    new_builder = _packet_builder(job, "translation", new_source, new_defs, old_target["page_ids"], extraction,
                                  new_job, baseline_after, None, old_target["max_context_pages"])
    exclusions = _post_review_feedback(job, base, old_source)[1] if base.get("post_review") is not None else {}
    footprints, packets = {}, {}
    for original, before_spec, after_spec in zip(old_target["units"], old_specs, new_specs):
        actual = _checked(job, original["packet"], original["packet_sha256"])
        before_packet = old_builder(before_spec, actual["plan_id"], old_target["pages"], old_ownership)
        after_packet = new_builder(after_spec, "source-rebase-candidate", old_target["pages"], new_ownership)
        before = _source_footprint(actual, old_source, before_packet)
        canonical_before = _source_footprint(before_packet, old_source, before_packet)
        after = _source_footprint(after_packet, new_source, after_packet)
        forced = exclusions.get(original["unit_id"], [])
        carried = original["unit_id"] in completed and before == canonical_before == after and not forced
        reason = "exact unchanged owned/read-only source footprint" if carried else (
            "submitted review requires fresh native work" if forced else "no completed checkpoint" if original["unit_id"] not in completed else "changed or uncertain source footprint")
        footprints[original["unit_id"]] = {"before": before, "after": after, "decision": "carried" if carried else "pending", "reason": reason}
        if base.get("post_review") is not None:
            footprints[original["unit_id"]]["review_exclusions"] = forced
        packets[original["unit_id"]] = (after_spec, after_packet)
    return {"base": base, "old_source": old_source, "new_source": new_source, "old_target": old_target,
            "completed": completed, "footprints": footprints, "packets": packets, "new_job": new_job}


def _rebase_context(job: Path, plan: dict, cache: dict) -> dict:
    bridge = plan["source_rebase"]
    key = ("source-rebase", bridge["base"]["path"], _canonical(bridge))
    if key not in cache:
        old_target = _checked(job, bridge["prior_target_plan"]["plan"], bridge["prior_target_plan"]["plan_sha256"])
        view = _rebase_view(job, bridge["revision_plan"], bridge["base"], bridge["current"], bridge["policy_acceptance"], old_target, cache)
        if bridge["footprints"] != view["footprints"]:
            raise ValueError("Recorded source rebase footprint decisions changed")
        references = {entry["unit_id"]: {"path": entry["path"], "sha256": entry["sha256"]} for entry in view["base"]["target_checkpoints"]}
        expected = {unit: references[unit] for unit, footprint in view["footprints"].items() if footprint["decision"] == "carried"}
        if bridge["carried"] != expected:
            raise ValueError("Source rebase carried checkpoint set changed")
        cache[key] = view
    return cache[key]


def _source_rebase_inputs(job: Path, plan: dict) -> None:
    bridge = plan["source_rebase"]
    if plan["role"] != "translation" or any(plan.get(key) is not None for key in ("pending_replan", "translation_reopen", "source_revision")):
        raise ValueError("Invalid active source rebase transition")
    base = _checked(job, bridge["base"]["path"], bridge["base"]["sha256"])
    current = bridge["current"]
    current_job = _checked(job, current["job"]["path"], current["job"]["sha256"])
    old_job = _checked(job, base["job"]["path"], base["job"]["sha256"])
    _same_rebase_intent(old_job, current_job, base.get("post_review"))
    for record in (base, current):
        for key in ("source", "seal", "terms", "handoff", "source_receipt", "terminology_receipt"):
            _bound_bytes(job, record[key])
    seal = _bound_bytes(job, current["seal"]).decode("ascii").strip()
    terms, handoff = _bound_bytes(job, current["terms"]), _bound_bytes(job, current["handoff"])
    term_reference, _ = _term_proof(job, current_job, seal, terms, handoff, current["seal"]["sha256"])
    acceptance = bridge["policy_acceptance"]
    bindings = {"source_seal_sha256": current["seal"]["sha256"], "terminology_receipt": term_reference["path"],
                "terminology_receipt_sha256": term_reference["sha256"], "terms_sha256": current["terms"]["sha256"],
                "handoff_sha256": current["handoff"]["sha256"]}
    post = base.get("post_review")
    if post is not None:
        bindings["post_review_base"] = bridge["base"]
    if (terms != _bound_bytes(job, base["terms"]) or term_reference != current["terminology_receipt"]
            or acceptance.get("accepted") is not True or acceptance.get("handoff_sha256") != current["handoff"]["sha256"]
            or acceptance.get("scope") != ["forms", "meanings", "style", "register", "names", "first_use", "index", "source_quality", "metadata", "preface"]
            or plan["readiness"] != {"source_digest": seal, "bindings": bindings}):
        raise ValueError("Source rebase policy acceptance or exact terminology/readiness binding changed")
    if (plan["job_sha256"] != current["job"]["sha256"] or plan["base_state"] != ("changes_requested" if post is not None else "terminology_ready")
            or plan["base_round"] != (post["original_round"] if post is not None else 0)
            or plan["selected_model"] != current_job["models"]["translation"] or plan["source_digest"] != seal
            or any(plan["baseline"][name] != current[key]["sha256"] for name, key in
                   (("book-source.json", "source"), ("source.sha256", "seal"), ("terms.json", "terms"), ("handoff.md", "handoff")))):
        raise ValueError("Current source rebase plan differs from its exact frozen new context")
    pointer = bridge["revision_plan"]
    revision = _checked(job, pointer["plan"], pointer["plan_sha256"])
    receipt = _checked(job, current["source_receipt"]["path"], current["source_receipt"]["sha256"])
    if (revision.get("source_revision", {}).get("base") != bridge["base"] or revision.get("revision") is not True
            or receipt.get("plan") != pointer["plan"] or receipt.get("plan_sha256") != pointer["plan_sha256"]
            or receipt.get("source_snapshot_digest") != seal or receipt.get("source_document_sha256") != current["source"]["sha256"]
            or receipt.get("revision") is not True or receipt.get("role") != "source" or receipt.get("completed") is not True):
        raise ValueError("Source rebase lost its exact completed source revision and new seal")
    original = _checked(job, base["target_plan"]["plan"], base["target_plan"]["plan_sha256"])
    unchanged = ("pages_per_unit", "max_context_pages", "metadata_owner", "source_file_sha256", "extraction_sha256", "page_ids", "pages")
    if (bridge["prior_target_plan"] != base["target_plan"] or any(plan[key] != original[key] for key in unchanged)
            or plan["baseline"]["book.json"] != (post["target_document"]["sha256"] if post is not None else original["baseline"]["book.json"])
            or [(spec["unit_id"], spec["owned_pages"]) for spec in plan["units"]]
                != [(spec["unit_id"], spec["owned_pages"]) for spec in original["units"]]):
        raise ValueError("Source rebase changed target ownership, metadata authority or immutable evidence/page bounds")
    ids = {spec["unit_id"] for spec in plan["units"]}
    footprints, carried = bridge["footprints"], bridge["carried"]
    if (set(footprints) != ids or any(item.get("decision") not in {"carried", "pending"} for item in footprints.values())
            or set(carried) != {unit for unit, item in footprints.items() if item["decision"] == "carried"}):
        raise ValueError("Source rebase decisions do not describe the exact target partition")
    for spec in plan["units"]:
        reference = carried.get(spec["unit_id"])
        if spec.get("carried_checkpoint") != reference or (reference is not None and reference["path"] != spec["checkpoint"]):
            raise ValueError("Source rebase carried checkpoint identity changed")
    if post is not None:
        _rebase_context(job, plan, {})


def _rebased_member(job: Path, plan: dict, spec: dict, cache: dict) -> tuple[dict, dict]:
    view = _rebase_context(job, plan, cache)
    reference = plan["source_rebase"]["carried"].get(spec["unit_id"])
    original = next(item for item in view["old_target"]["units"] if item["unit_id"] == spec["unit_id"])
    ignored = {"carried_checkpoint"}
    if (reference is None or spec.get("carried_checkpoint") != reference or reference["path"] != spec["checkpoint"]
            or {key: value for key, value in spec.items() if key not in ignored}
                != {key: value for key, value in original.items() if key not in ignored}):
        raise ValueError("Rebased checkpoint is not the exact accepted original member")
    return _checked(job, reference["path"], reference["sha256"]), view["completed"][spec["unit_id"]]


def _rebase_translation(job: Path, pages_per_unit: int, max_context_pages: int, readiness: dict,
                        revision_path, accept_policy_compatibility) -> dict:
    data = _job(job)
    if not isinstance(revision_path, (str, Path)):
        raise ValueError("Source rebase requires an absolute or job-relative source revision plan path")
    path = Path(revision_path)
    path = path.resolve(strict=True) if path.is_absolute() else _path(job, str(path))
    if not path.is_relative_to(job):
        raise ValueError("Source revision plan must be contained by this job")
    revision = core.load_json(path)
    if revision.get("role") != "source" or revision.get("revision") is not True or revision.get("source_revision") is None:
        raise ValueError("Source rebase requires the explicit selective source revision plan")
    revision_pointer = {"plan": _relative(job, path), "plan_sha256": _hash(path)}
    base_reference = revision["source_revision"]["base"]
    base, old_source = _archived_source(job, base_reference, {})
    post = base.get("post_review")
    if post is None:
        _initial_prebuild(data)
    elif (_active_post_review(job, data) != base_reference or data["state"] != "changes_requested"
          or data["round"] != post["original_round"]):
        raise ValueError("Post-review source rebase requires its admitted current recovery")
    source = core.validate_book(job, translated=False)
    digest = (job / "source.sha256").read_text(encoding="ascii").strip()
    source_reference, source_receipt = _journal_ref(job, data, "role_source")
    if (source_receipt.get("plan") != revision_pointer["plan"] or source_receipt.get("plan_sha256") != revision_pointer["plan_sha256"]
            or source_receipt.get("source_snapshot_digest") != digest or source_receipt.get("revision") is not True):
        raise ValueError("New source is not the completed, explicitly resealed requested revision")
    validate_aggregate(job, source_receipt, "source")
    terms, handoff = (job / "terms.json").read_bytes(), (job / "handoff.md").read_bytes()
    if terms != _bound_bytes(job, base["terms"]):
        raise ValueError("Source rebase requires entire terminology bytes unchanged")
    term_reference, _ = _term_proof(job, data, digest, terms, handoff, _hash(job / "source.sha256"))
    if (not isinstance(accept_policy_compatibility, str) or accept_policy_compatibility != _hash(job / "handoff.md")):
        raise ValueError("Explicit acceptance must name the exact fresh native handoff compatibility judgment")
    old_target = _checked(job, base["target_plan"]["plan"], base["target_plan"]["plan_sha256"])
    if (pages_per_unit != old_target["pages_per_unit"] or max_context_pages != old_target["max_context_pages"]
            or core.load_json(job / "units/translation/active.json") != base["target_plan"]):
        raise ValueError("Source rebase must use the frozen active target plan and unchanged page/context bounds")
    candidate_sha = _hash(job / "book.json") if (job / "book.json").is_file() else None
    if candidate_sha != (post["target_document"]["sha256"] if post is not None else old_target["baseline"]["book.json"]):
        raise ValueError("Unadmitted canonical target baseline changed during source correction")
    expected_readiness = {"source_digest": digest, "bindings": {
        "source_seal_sha256": _hash(job / "source.sha256"), "terminology_receipt": term_reference["path"],
        "terminology_receipt_sha256": term_reference["sha256"], "terms_sha256": _hash(job / "terms.json"),
        "handoff_sha256": _hash(job / "handoff.md")}}
    if post is not None:
        expected_readiness["bindings"]["post_review_base"] = base_reference
    if readiness != expected_readiness:
        raise ValueError("Source rebase requires current source/terminology readiness")
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/translation/{identifier}")
    current = {"source_receipt": source_reference, "terminology_receipt": term_reference,
               "artifacts": _admitted_artifacts(job, [{"source_receipt": source_reference,
                                                       "terminology_receipt": term_reference}, revision_pointer,
                                                      {"path": data["source_file"], "sha256": data["source_sha256"]}])}
    snapshots = (("job", "job.json", "current-job.json"), ("source", "book-source.json", "current-source.json"),
                 ("seal", "source.sha256", "current-source.sha256"), ("terms", "terms.json", "current-terms.json"),
                 ("handoff", "handoff.md", "current-handoff.md"))
    for key, relative, _ in snapshots:
        current[key] = _ref(job, _path(job, relative))
    acceptance = {"handoff_sha256": accept_policy_compatibility, "accepted": True,
                  "scope": ["forms", "meanings", "style", "register", "names", "first_use", "index", "source_quality", "metadata", "preface"],
                  "at": datetime.now(timezone.utc).isoformat()}
    view = _rebase_view(job, revision_pointer, base_reference, current, acceptance, old_target, {})
    for key, relative, name in snapshots:
        frozen = _snapshot(job, directory, relative, name)
        if frozen["sha256"] != current[key]["sha256"]:
            raise ValueError("Current source rebase context changed during freezing")
        current[key] = frozen
    references = {entry["unit_id"]: {"path": entry["path"], "sha256": entry["sha256"]} for entry in base["target_checkpoints"]}
    specs, carried = [], {}
    for original in old_target["units"]:
        unit = original["unit_id"]
        if view["footprints"][unit]["decision"] == "carried":
            spec = {**original, "carried_checkpoint": references[unit]}
            carried[unit] = references[unit]
        else:
            logical, packet = view["packets"][unit]
            packet = {**packet, "plan_id": identifier}
            packet_path = directory / "packets" / f"{unit}.json"
            _write_once(packet_path, packet)
            spec = {**logical, "packet": _relative(job, packet_path), "packet_sha256": _hash(packet_path),
                    "result": _relative(job, directory / "results" / f"{unit}.json"),
                    "assets_dir": _relative(job, directory / "assets" / unit),
                    "checkpoint": _relative(job, directory / "checkpoints" / f"{unit}.json")}
            old_result = _path(job, original["result"])
            if old_result.is_file():
                aid = {"result": _ref(job, old_result)}
                if unit in references:
                    aid["checkpoint"] = references[unit]
                spec["reading_aid"] = aid
        specs.append(spec)
    plan = {"version": 1, "kind": "book-unit-plan", "plan_id": identifier, "role": "translation",
            "job_path": str(job), "job_sha256": current["job"]["sha256"], "base_state": data["state"], "base_round": data["round"],
            "revision": False, "selected_model": data["models"]["translation"], "source_file_sha256": data["source_sha256"],
            "source_digest": digest, "baseline": _baseline(job), "extraction_sha256": old_target["extraction_sha256"],
            "pages_per_unit": pages_per_unit, "max_context_pages": max_context_pages,
            "page_ids": old_target["page_ids"], "pages": old_target["pages"], "metadata_owner": old_target["metadata_owner"],
            "draft": None, "build": None, "pdf_page_ids": [], "readiness": readiness, "review_artifacts": {}, "units": specs,
            "source_rebase": {"revision_plan": revision_pointer, "base": base_reference, "prior_target_plan": base["target_plan"],
                              "current": current, "policy_acceptance": acceptance, "footprints": view["footprints"], "carried": carried}}
    destination = directory / "plan.json"
    _write_once(destination, plan)
    pointer = {"plan": _relative(job, destination), "plan_sha256": _hash(destination)}
    _stable_context(job, plan)
    _rebase_context(job, plan, {})
    core.save_json(job / "units/translation/active.json", pointer)
    return {**pointer, "role": "translation", "units": [spec["unit_id"] for spec in specs], "pages": len(plan["page_ids"])}



def create_plan(job, role: str, *, pages_per_unit: int = 8, draft_path=None, revise: bool = False,
                max_context_pages: int = 4, readiness: dict | None = None, replan_pending: bool = False,
                reopen_units: list[str] | None = None, rebase_source: Path | None = None,
                accept_policy_compatibility: str | None = None, post_review_scope: Path | None = None) -> dict:
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
    if replan_pending and (role != "translation" or draft_path is not None or revise):
        raise ValueError("Pending replanning requires translation without draft import or revision")
    source_revision_requested = role == "source" and revise is True and reopen_units is not None
    if post_review_scope is not None and not source_revision_requested:
        raise ValueError("Post-review scope requires source --revise --reopen")
    if source_revision_requested and (draft_path is not None or replan_pending or rebase_source is not None or accept_policy_compatibility is not None):
        raise ValueError("Selective source revision cannot combine draft/resize/rebase options")
    if reopen_units is not None and not source_revision_requested and (role not in {"translation", "review"} or draft_path is not None or revise or replan_pending):
        raise ValueError("Reopening requires selected source revision, eligible prebuild translation or unpublished current review")
    if (rebase_source is None) != (accept_policy_compatibility is None):
        raise ValueError("Source rebase requires explicit handoff-policy acceptance")
    if rebase_source is not None and (role != "translation" or draft_path is not None or revise or replan_pending or reopen_units is not None):
        raise ValueError("Source rebase cannot combine role/draft/revision/resize/reopen options")
    data = _job(job)
    if any(not data["models"].get(name, {}).get("provider") or not data["models"].get(name, {}).get("model")
           for name in ("source", "terminology", "translation", "review")):
        raise ValueError("Every exact role model must be configured before unit planning")
    if role == "source" and data["round"] > 0 and post_review_scope is None:
        raise ValueError("Positive-round source planning requires explicit post-review scope")
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
    recovery = _active_post_review(job, data) if role == "translation" else None
    if recovery is not None and rebase_source is None:
        raise ValueError("Post-review source recovery requires feedback-bound source rebase")
    if rebase_source is not None:
        return _rebase_translation(job, pages_per_unit, max_context_pages, readiness, rebase_source, accept_policy_compatibility)
    source_context = _source_revision_context(job, pages_per_unit, reopen_units, post_review_scope=post_review_scope) if source_revision_requested else None
    if reopen_units is not None and not source_revision_requested:
        if role == "review":
            return _reopen_review(job, pages_per_unit, max_context_pages, readiness, reopen_units)
        return _reopen_translation(job, pages_per_unit, max_context_pages, readiness, reopen_units)
    pending_replan, previous, carried = None, None, {}
    if replan_pending:
        pending_replan, previous, carried = _prepare_pending_translation(job, pages_per_unit, max_context_pages, readiness)
    extraction = core.extraction_inventory(job)
    if extraction is None:
        raise ValueError("Unit planning requires controller-admitted complete extraction evidence")
    extraction_digest = next(event["extraction_sha256"] for event in reversed(data["history"]) if event.get("event") == "extracted")
    pages = extraction["pages"]
    page_ids = [page["id"] for page in pages]
    page_order = {name: index for index, name in enumerate(page_ids)}
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/{role}/{identifier}")
    if not replan_pending:
        directory.mkdir(parents=True, exist_ok=False)
    revision_base = _freeze_source_base(job, directory, source_context) if source_context is not None else None
    baseline = _baseline(job)
    review_artifacts = {}
    if role == "review":
        for suffix in ("json", "receipt.json"):
            name = f"reviews/round-{data['round']}.{suffix}"
            path = _path(job, name)
            review_artifacts[name] = _hash(path) if path.is_file() else None
    draft_info = None
    build = _review_build(job) if role == "review" else None
    if source_context is not None:
        draft = source_context["source"]
        base = _checked(job, revision_base["path"], revision_base["sha256"])
        draft_info = {"snapshot": base["source"]["path"], "snapshot_sha256": base["source"]["sha256"],
                      "assets": core._asset_hashes(job, draft), "trusted": False, "origin": "sealed-source"}
    elif role in {"translation", "review"}:
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
    unit_specs = []
    if previous is None:
        groups = [(f"u{index + 1:04d}", page_ids[offset:offset + pages_per_unit])
                  for index, offset in enumerate(range(0, len(pages), pages_per_unit))]
    else:
        if page_ids != previous["page_ids"]:
            raise ValueError("Original page inventory changed before pending replanning")
        old_ownership = _translation_ownership(draft, declarations, previous, page_order)
        completed_pages = {page for spec in carried.values() for page in spec["owned_pages"]}
        new_groups = []
        for offset in range(0, len(page_ids), pages_per_unit):
            run = []
            for page in page_ids[offset:offset + pages_per_unit]:
                if page in completed_pages:
                    if run:
                        new_groups.append(run)
                        run = []
                else:
                    run.append(page)
            if run:
                new_groups.append(run)
        next_id = max(int(spec["unit_id"][1:]) for spec in previous["units"]) + 1
        groups = [(spec["unit_id"], spec["owned_pages"]) for spec in carried.values()]
        groups.extend((f"u{next_id + index:04d}", owned) for index, owned in enumerate(new_groups))
        groups.sort(key=lambda group: page_order[group[1][0]])
    for unit_id, owned in groups:
        unit_specs.append({"unit_id": unit_id, "owned_pages": owned, "owned_block_ids": [],
                           "owned_note_ids": [], "owned_protected_ids": []})
    if source_context is not None and [(spec["unit_id"], spec["owned_pages"]) for spec in unit_specs] != [
            (spec["unit_id"], spec["owned_pages"]) for spec in source_context["old_source_plan"]["units"]]:
        raise ValueError("Selective source revision must retain original source ownership")
    ownership = _assign_ownership(draft, declarations, unit_specs, page_order)
    block_owners, note_owners, protected_users, metadata_owner = ownership
    if previous is not None:
        for index, spec in enumerate(unit_specs):
            if spec["unit_id"] not in carried:
                continue
            original = carried[spec["unit_id"]]
            if (any(spec[key] != original[key] for key in ("owned_pages", "owned_block_ids", "owned_note_ids", "owned_protected_ids"))
                    or (previous["metadata_owner"] == spec["unit_id"]) != (metadata_owner == spec["unit_id"])):
                raise ValueError("Pending replanning changed completed unit ownership or metadata authority")
            unit_specs[index] = original
    pdf_page_ids = _review_ownership(job, unit_specs, block_owners, note_owners, metadata_owner) if role == "review" else []
    page_records = previous["pages"] if previous is not None else {}
    for page in ([] if previous is not None else pages):
        image = page.get("image")
        if not image or not _path(job, image).is_file():
            raise ValueError(f"Source page {page['id']} lacks a readable inspection image")
        destination = directory / "pages" / f"{page['id']}.json"
        _write_once(destination, page)
        page_records[page["id"]] = {"page_id": page["id"], "locator": page["locator"],
            "evidence": _relative(job, destination), "evidence_sha256": _hash(destination),
            "image": image, "image_sha256": _hash(_path(job, image)),
            "raster_region_count": len(page.get("image_regions", []))}
    packet_for = _packet_builder(job, role, draft, declarations, page_ids, extraction, data, baseline, build, max_context_pages)

    if previous is not None:
        for spec in previous["units"]:
            if spec["unit_id"] in carried:
                continue
            actual_packet = _checked(job, spec["packet"], spec["packet_sha256"])
            expected_packet = packet_for(spec, actual_packet["plan_id"], previous["pages"], old_ownership)
            if previous.get("translation_reopen") is not None and actual_packet["plan_id"] != previous["plan_id"]:
                # The validated parent/packet hashes bind these historical read-only labels.
                for field in ("context_block_owners", "context_note_owners"):
                    expected_packet[field] = actual_packet[field]
            if actual_packet != expected_packet:
                raise ValueError("Pending packet differs from canonical source/context/terminology inputs")
    packets = []
    for spec in unit_specs:
        if spec["unit_id"] in carried:
            continue
        packet = packet_for(spec, identifier, page_records, ownership)
        if source_context is not None and base.get("post_review") is not None and spec["unit_id"] in source_context["reopened"]:
            prepared = _prepared_source_scope(job, base["post_review"], spec["unit_id"])
            if prepared is not None:
                packet["prepared_source_scope"] = prepared
        _packet_scope(packet)
        packets.append((spec, packet))
    for spec, packet in packets:
        packet_path = directory / "packets" / f"{spec['unit_id']}.json"
        _write_once(packet_path, packet)
        spec.update(packet=_relative(job, packet_path), packet_sha256=_hash(packet_path),
                    result=_relative(job, directory / "results" / f"{spec['unit_id']}.json"),
                    assets_dir=_relative(job, directory / "assets" / spec["unit_id"]),
                    checkpoint=_relative(job, directory / "checkpoints" / f"{spec['unit_id']}.json"))
    if source_context is not None:
        old_specs = {spec["unit_id"]: spec for spec in source_context["old_source_plan"]["units"]}
        old_receipt = _checked(job, source_context["source_receipt"]["path"], source_context["source_receipt"]["sha256"])
        origins = {item["path"]: item for item in old_receipt["unit_checkpoints"]}
        for spec in unit_specs:
            if spec["unit_id"] in source_context["reopened"]:
                continue
            packet = _checked(job, spec["packet"], spec["packet_sha256"])
            projection_path = directory / "projections" / f"{spec['unit_id']}.json"
            _write_once(projection_path, _source_projection(draft, packet))
            origin = origins[old_specs[spec["unit_id"]]["checkpoint"]]
            spec.update(result=_relative(job, projection_path), checkpoint=origin["path"],
                        source_carry={"checkpoint": origin, "projection": _ref(job, projection_path)})
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
    if revision_base is not None:
        plan["source_revision"] = {"base": revision_base, "reopened": source_context["reopened"]}
        _source_revision_inputs(job, plan)
    if pending_replan is not None:
        plan["pending_replan"] = pending_replan
    destination = directory / "plan.json"
    _write_once(destination, plan)
    pointer = {"plan": _relative(job, destination), "plan_sha256": _hash(destination)}
    if previous is not None:
        _stable_context(job, previous)
        _plan_inputs(job, plan)
        origins = {}
        for spec in unit_specs:
            if spec.get("carried_checkpoint") is not None:
                _member_checkpoint(job, plan, pointer["plan"], pointer["plan_sha256"], spec, origins)
    if revision_base is not None:
        _stable_context(job, plan)
        _archived_source(job, revision_base, {})
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
        prepared_expected = _prepared_source_inputs(job, packet)
        prepared_assets = {}
        if prepared_expected is not None:
            associations = _asset_associations(output)
            expected_associations = _asset_associations(prepared_expected)
            for row in packet["prepared_source_scope"]["crop_derivations"]:
                ref = row["output"]["ref"]
                name = ref["path"]
                actual = Counter({use: count for use, count in associations.items() if use[3] == name})
                declared = Counter({use: count for use, count in expected_associations.items() if use[3] == name})
                if actual and actual != declared:
                    raise ValueError("Prepared output may be used only at its exact declared block/note association and geometry")
                prepared_assets[name] = ref["sha256"]
        for name in _asset_names(output):
            if (name not in allowed_assets and name not in prepared_assets
                    and not _path(job, name).is_relative_to(_path(job, binding["assets_dir"]))):
                raise ValueError("New source assets must be in the assigned unit assets directory or their exact prepared association")
            assets[name] = _hash(_path(job, name))
            if name in prepared_assets and assets[name] != prepared_assets[name]:
                raise ValueError("Prepared output identity changed")
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
    _prepared_source_inputs(job, packet)



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


def _member_checkpoint(job: Path, plan: dict, plan_name: str, plan_digest: str, spec: dict,
                       origin_plans: dict) -> tuple[dict, dict]:
    if spec.get("source_carry") is not None:
        return _source_carried_member(job, plan, spec, origin_plans)
    if plan.get("source_rebase") is not None and spec.get("carried_checkpoint") is not None:
        return _rebased_member(job, plan, spec, origin_plans)
    reference = spec.get("carried_checkpoint")
    checkpoint_path = _path(job, spec["checkpoint"])
    if reference is None:
        checkpoint = core.load_json(checkpoint_path)
        origin_plan, origin_name, origin_digest, origin_spec = plan, plan_name, plan_digest, spec
    else:
        if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
                or reference["path"] != spec["checkpoint"]):
            raise ValueError("Invalid carried checkpoint reference")
        checkpoint = _checked(job, reference["path"], reference["sha256"])
        origin_name, origin_digest = checkpoint["plan"], checkpoint["plan_sha256"]
        key = (origin_name, origin_digest)
        if key not in origin_plans:
            origin_plans[key] = _checked(job, origin_name, origin_digest)
        origin_plan = origin_plans[key]
        if plan["role"] == "source":
            if (plan["base_state"] != "extracted" or plan["base_round"] != 0
                    or plan["revision"] or plan["source_digest"] is not None):
                raise ValueError("Carried checkpoints are restricted to unchanged initial source scope")
            unchanged = ("role", "job_path", "base_state", "base_round", "revision", "source_file_sha256", "source_digest",
                         "baseline", "extraction_sha256", "page_ids", "pages_per_unit", "max_context_pages", "metadata_owner", "draft")
            if (origin_plan.get("kind") != "book-unit-plan"
                    or any(origin_plan.get(name) != plan.get(name) for name in unchanged)):
                raise ValueError("Carried source checkpoint belongs to different book inputs or coverage")
        elif ((plan["role"] == "translation" and (plan.get("pending_replan") is not None or plan.get("translation_reopen") is not None))
              or (plan["role"] == "review" and plan.get("review_reopen") is not None)):
            role = plan["role"]
            reopening = plan.get(f"{role}_reopen") is not None
            link = plan[f"{role}_reopen"] if reopening else plan["pending_replan"]
            parent_key = (link["plan"], link["plan_sha256"])
            if parent_key not in origin_plans:
                origin_plans[parent_key] = _checked(job, *parent_key)
            parent = origin_plans[parent_key]
            if role == "review":
                _review_reopen_context(plan, parent)
            else:
                _translation_replan_context(plan, parent, allow_same_bound=reopening)
            if reopening and plan["pages_per_unit"] != parent["pages_per_unit"]:
                raise ValueError(f"{role.capitalize()} reopening changed its immediate parent's page bound")
            parent_spec = next((item for item in parent["units"] if item["unit_id"] == spec["unit_id"]), None)
            if (parent_spec is None
                    or {name: value for name, value in spec.items() if name != "carried_checkpoint"}
                        != {name: value for name, value in parent_spec.items() if name != "carried_checkpoint"}
                    or (parent_spec.get("carried_checkpoint") is not None and parent_spec["carried_checkpoint"] != reference)
                    or (parent_spec.get("carried_checkpoint") is None and (origin_name, origin_digest) != parent_key)):
                raise ValueError(f"Carried {role} checkpoint is not linked through the exact parent scope/origin")
            if (parent["metadata_owner"] == spec["unit_id"]) != (plan["metadata_owner"] == spec["unit_id"]):
                raise ValueError(f"Carried {role} metadata authority changed from its immediate parent")
            if parent_spec.get("carried_checkpoint") is not None:
                return _member_checkpoint(job, parent, link["plan"], link["plan_sha256"], parent_spec, origin_plans)
            if role == "review":
                _review_reopen_context(plan, origin_plan)
            else:
                _translation_replan_context(plan, origin_plan, allow_same_bound=reopening)
            if (origin_plan["metadata_owner"] == spec["unit_id"]) != (plan["metadata_owner"] == spec["unit_id"]):
                raise ValueError(f"Carried {role} metadata ownership changed")
        else:
            raise ValueError("Carried checkpoints require source continuation or an explicit translation/review plan transition")
        origin_spec = next((item for item in origin_plan["units"] if item["unit_id"] == spec["unit_id"]), None)
        ignored = {"carried_checkpoint"}
        if (origin_spec is None
                or {name: value for name, value in spec.items() if name not in ignored}
                    != {name: value for name, value in origin_spec.items() if name not in ignored}):
            raise ValueError("Carried unit ownership, packet or output paths changed")
    expected = _content_checkpoint(job, origin_plan, origin_name, origin_digest, origin_spec)
    if checkpoint.get("completed") is not True or any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("Unit checkpoint differs from its complete current result/context")
    _checkpoint_origin(job, checkpoint, origin_plan)
    return checkpoint, core.load_json(_path(job, spec["result"]))


def continue_source(job, future_job: dict) -> dict:
    """Prepare a content-only source continuation; the controller publishes its intent."""
    job = Path(job).resolve(strict=True)
    plan_path, previous, previous_digest = _current_plan(job, "source")
    data = _stable_context(job, previous)
    if previous["revision"] or previous["source_digest"] is not None or (job / "source.sha256").exists():
        raise ValueError("Source continuation requires an initial unsealed source plan")
    selected = _source_model_change(data, future_job)
    if previous.get("draft") is not None:
        for name, digest in previous["draft"]["assets"].items():
            if _hash(_path(job, name)) != digest:
                raise ValueError("Imported untrusted draft asset identity changed")
    carried = {}
    origin_plans = {}
    previous_name = _relative(job, plan_path)
    for spec in previous["units"]:
        checkpoint_path = _path(job, spec["checkpoint"])
        if checkpoint_path.exists() or spec.get("carried_checkpoint") is not None:
            _member_checkpoint(job, previous, previous_name, previous_digest, spec, origin_plans)
            carried[spec["unit_id"]] = {"path": spec["checkpoint"], "sha256": _hash(checkpoint_path)}
    reopened = future_job["history"][-1].get("reopened", [])
    if any(unit_id not in carried for unit_id in reopened):
        raise ValueError("Only completed units in the active source plan may be explicitly reopened")
    for unit_id in reopened:
        del carried[unit_id]
    old_bytes = (job / "job.json").read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != previous["job_sha256"]:
        raise ValueError("Source continuation job changed during validation")
    identifier = uuid.uuid4().hex
    directory = _path(job, f"units/source/{identifier}")
    directory.mkdir(parents=True, exist_ok=False)
    previous_job_path = directory / "previous-job.json"
    previous_job_path.write_bytes(old_bytes)
    future_job_path = directory / "job-snapshot.json"
    _write_once(future_job_path, future_job)
    previous_job = {"path": _relative(job, previous_job_path), "sha256": _hash(previous_job_path)}
    job_snapshot = {"path": _relative(job, future_job_path), "sha256": _hash(future_job_path)}
    specs = []
    for old_spec in previous["units"]:
        spec = dict(old_spec)
        reference = carried.get(spec["unit_id"])
        if reference is not None:
            spec["carried_checkpoint"] = reference
        else:
            spec.pop("carried_checkpoint", None)
            spec.update(result=_relative(job, directory / "results" / f"{spec['unit_id']}.json"),
                        assets_dir=_relative(job, directory / "assets" / spec["unit_id"]),
                        checkpoint=_relative(job, directory / "checkpoints" / f"{spec['unit_id']}.json"))
        specs.append(spec)
    plan = {**previous, "plan_id": identifier, "job_sha256": job_snapshot["sha256"], "selected_model": selected,
            "units": specs, "continuation": {"plan": previous_name, "plan_sha256": previous_digest,
                                             "previous_job": previous_job, "job_snapshot": job_snapshot, "reopened": reopened}}
    destination = directory / "plan.json"
    _write_once(destination, plan)
    return {"role": "source", "plan": _relative(job, destination), "plan_sha256": _hash(destination),
            "revision": False, "base_state": "extracted", "base_round": 0, "pages": len(plan["page_ids"]),
            "admitted": list(carried), "pending": [spec["unit_id"] for spec in specs if spec["unit_id"] not in carried],
            "complete": len(carried) == len(specs), "carried": list(carried),
            "previous_job": previous_job, "job_snapshot": job_snapshot, "reopened": reopened}


def _members(job: Path, plan: dict, plan_name: str, plan_digest: str, *, cache: dict | None = None) -> tuple[list, list]:
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
    if plan.get("pending_replan") is not None and any(
            "carried_checkpoint" not in spec and len(spec["owned_pages"]) > plan["pages_per_unit"]
            for spec in plan["units"]):
        raise ValueError("New pending translation unit exceeds the reduced page bound")
    if plan["role"] == "review":
        if any(len(spec["pdf_pages"]) > 8 or len(spec["context_pdf_pages"]) > 2 for spec in plan["units"]):
            raise ValueError("Review plan exceeds bounded physical PDF page scope")
        pdf_owned = [page for item in plan["units"] for page in item["pdf_pages"]]
        if Counter(pdf_owned) != Counter(plan["pdf_page_ids"]):
            raise ValueError("Review unit plan lacks exact complete physical PDF page ownership")
    origin_plans = {} if cache is None else cache
    for spec in plan["units"]:
        _, output = _member_checkpoint(job, plan, plan_name, plan_digest, spec, origin_plans)
        checkpoints.append({"path": spec["checkpoint"], "sha256": _hash(_path(job, spec["checkpoint"]))})
        outputs.append(output)
    return checkpoints, outputs


def _merge(job: Path, plan: dict, outputs: list, *, source: dict | None = None) -> dict:
    metadata = next(output["metadata"] for output in outputs if output["unit_id"] == plan["metadata_owner"])
    if plan["role"] == "translation":
        book = deepcopy(source) if source is not None else core.load_json(job / "book-source.json")
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
    authored = set()
    for spec, output in zip(plan["units"], outputs):
        packet = _checked(job, spec["packet"], spec["packet_sha256"])
        imports = {item["id"]: item for item in packet["protected"] + packet.get("context_protected", [])}
        for item in output["protected"]:
            if imports.get(item["id"]) != item:
                authored.add(item["id"])
    referenced = set()
    for item in book["blocks"] + book["notes"]:
        referenced.update(_references(item, "protected"))
        referenced.update(token["protected"] for token in item.get("target", []) if "protected" in token)
    # Unused exact imports stay in immutable unit evidence, not the canonical symbol table.
    book["protected"] = [item for item in book["protected"] if item["id"] in referenced or item["id"] in authored]
    if plan.get("source_revision") is not None:
        _, original = _source_revision_inputs(job, plan)
        order = {item["id"]: index for index, item in enumerate(original["protected"])}
        book["protected"].sort(key=lambda item: order.get(item["id"], len(order)))
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
    archives = {}
    checkpoints, outputs = _members(job, plan, _relative(job, plan_path), digest, cache=archives)
    if role == "review":
        document = _review_report(plan, outputs)
        name = f"reviews/round-{plan['base_round']}.json"
    else:
        document = _merge(job, plan, outputs)
        if plan.get("source_revision") is not None:
            _source_revision_scope(job, plan, document, archives)
        core.validate_document("book", document)
        terms = core.load_json(job / "terms.json") if role == "translation" else None
        data = _job(job)
        source_language = data["source_language"].replace("_", "-").split("-", 1)[0].casefold()
        target_language = data["target_language"].replace("_", "-").split("-", 1)[0].casefold()
        core._validate_structure(document, job, terms, role == "translation", languages_differ=source_language != target_language)
        if role == "translation" and core._immutable(document) != core._immutable(core.load_json(job / "book-source.json")):
            raise ValueError("Assembled translation changed immutable source")
        if role == "translation":
            import render

            render._source_page_plan(document)
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
    archives = {}
    checkpoints, outputs = _members(job, plan, receipt["plan"], receipt["plan_sha256"], cache=archives)
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
    if plan.get("source_revision") is not None:
        _source_revision_scope(job, plan, book, archives)
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
