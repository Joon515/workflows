#!/usr/bin/env python3
"""Book-domain checkpoints and state transitions; OMP owns model execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

try:
    import core
    CORE_IMPORT_ERROR = None
except ModuleNotFoundError as error:
    core = None
    CORE_IMPORT_ERROR = str(error)


STAGES = ("terminology", "translation")
ROLES = ("source", "terminology", "translation", "review")
REVIEW_CHECKS = {"coverage", "terminology", "protected_content", "source_pages", "image_relations", "footnotes", "typography", "preface"}
BUILD_CHECKS = {"compiler", "pdf_geometry", "preface", "source_boundaries", "image_relations", "inline_images", "footnotes", "references", "overflow", "pagination", "typography"}
LAYOUT = {"paper": "a5", "outer_mm": 8, "inner_min_mm": 20, "top_mm": 15, "bottom_mm": 15, "source_mark_edge_mm": 3}


def doctor() -> dict:
    result = importlib.import_module("extract").doctor()
    dependencies = {}
    for distribution, module in (("jsonschema", "jsonschema"), ("Pillow", "PIL")):
        try:
            importlib.import_module(module)
            dependencies[distribution] = {"available": True, "version": importlib.metadata.version(distribution)}
        except (ImportError, importlib.metadata.PackageNotFoundError) as error:
            dependencies[distribution] = {"available": False, "error": str(error), "action": f"Install {distribution} in the Python environment running this command"}
    tools = {name: shutil.which(name) for name in ("xelatex", "latexmk", "kpsewhich")}
    resources = {}
    required = ("ctexbook.cls", "geometry.sty", "amsmath.sty", "amssymb.sty", "graphicx.sty", "longtable.sty", "array.sty", "fvextra.sty", "tikz.sty", "footmisc.sty", "zref-savepos.sty", "zref-abspage.sty")
    fonts = ("FandolSong-Regular.otf", "FandolSong-Bold.otf", "FandolHei-Regular.otf", "FandolHei-Bold.otf", "FandolKai-Regular.otf", "FandolFang-Regular.otf", "lmroman10-regular.otf", "lmmono10-regular.otf")
    for resource in (*required, *fonts):
        found = None
        if tools["kpsewhich"]:
            try:
                probe = subprocess.run([tools["kpsewhich"], resource], capture_output=True, text=True, timeout=10)
                found = probe.stdout.strip() if probe.returncode == 0 else None
            except subprocess.SubprocessError:
                pass
        resources[resource] = found
    ready = bool(tools["xelatex"] and tools["kpsewhich"] and all(resources.values()) and all(value["available"] for value in dependencies.values()) and result["pymupdf"]["available"])
    result["python_dependencies"] = dependencies
    result["render"] = {"ready": ready, "tools": tools, "packages": {name: resources[name] for name in required}, "fonts": {name: resources[name] for name in fonts}, "latexmk_required": False, "note": "The renderer repeats XeLaTeX directly; latexmk is optional. Font coverage beyond these defaults is checked during the real build."}
    if not ready:
        result["render"]["action"] = "Supply XeLaTeX, kpsewhich, the missing listed TeX packages/fonts and Python dependencies in this environment; doctor never installs or changes global configuration"
    executable = shutil.which("omp")
    version = None
    if executable:
        try:
            probe = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
            version = probe.stdout.strip() if probe.returncode == 0 else None
        except subprocess.SubprocessError:
            pass
    result["omp"] = {"executable": executable, "version": version, "note": "Use ordinary tasks in the current OMP session; the book controller never routes models, resolves authentication or launches inference"}
    return result



def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contained(job: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Job path must be relative and contained: {name}")
    result = (job / candidate).resolve()
    if not result.is_relative_to(job.resolve()):
        raise ValueError(f"Job path escapes its directory: {name}")
    return result


def validate_job_record(data: dict, *, configuring: bool = False) -> None:
    """Configuration may replace old selectors; execution always admits every stored choice."""
    view = data
    if configuring and isinstance(data.get("models"), dict):
        # Preserve every field/key/type for schema checks. Only outgoing selector
        # strings are neutralized in this validation view, never in persisted data.
        models = {role: ({**selected, "provider": "", "model": ""}
                         if isinstance(selected, dict) and isinstance(selected.get("provider"), str)
                         and isinstance(selected.get("model"), str) else selected)
                  for role, selected in data["models"].items()}
        view = {**data, "models": models}
    core.validate_document("job", view)


def load_job(job: Path, *, configuring: bool = False) -> dict:
    data = core.load_json(job / "job.json")
    validate_job_record(data, configuring=configuring)
    source = contained(job, data["source_file"])
    if not source.is_file() or digest_file(source) != data["source_sha256"]:
        raise ValueError("Original source evidence is missing or changed; initialize a new job")
    if data["round"] > data["max_rounds"]:
        raise ValueError("Job round exceeds its configured limit")
    return data


def save_job(job: Path, data: dict, event: str, *, configuring: bool = False, **details) -> None:
    data["history"].append({"event": event, "at": datetime.now(timezone.utc).isoformat(), **details})
    validate_job_record(data, configuring=configuring)
    core.save_json(job / "job.json", data)


@contextmanager
def mutation_lock(job: Path):
    import fcntl
    with (job / ".controller.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another controller operation owns this job") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def invalidate_output(job: Path) -> None:
    output = job / "output.pdf"
    if output.is_symlink() or output.is_file():
        output.unlink()
    elif output.exists():
        raise ValueError("output.pdf is not a generated regular file")


def invalidate_build(job: Path) -> None:
    invalidate_output(job)
    verification = contained(job, "build/verification.json")
    if verification.is_file():
        verification.unlink()


def source_inventory_coverage(job: Path) -> None:
    """Conserve ordered original locators while allowing legal source-page ID renaming."""
    extraction = core.extraction_inventory(job)
    if extraction is None:
        return
    pages = core.load_json(contained(job, "book-source.json")).get("source_pages")
    if (not isinstance(pages, list) or not pages
            or any(not isinstance(page, dict) or not isinstance(page.get("id"), str)
                   or not page["id"] for page in pages)
            or len({page["id"] for page in pages}) != len(pages)
            or [page.get("locator") for page in pages] != [page["locator"] for page in extraction["pages"]]):
        raise ValueError("Source must conserve every original extraction page locator exactly once in order")


def source_digest(job: Path) -> str:
    core.validate_book(job, translated=False)
    source_inventory_coverage(job)
    seal = (job / "source.sha256").read_text(encoding="utf-8").strip()
    if len(seal) != 64 or any(char not in "0123456789abcdef" for char in seal):
        raise ValueError("Invalid source seal; explicitly seal the reviewed source")
    receipt = latest_role_receipt(job, load_job(job), "source")
    if receipt.get("source_snapshot_digest") != seal:
        raise ValueError("Sealed source lacks a matching complete source content checkpoint")
    return seal


def current_build(job: Path) -> dict:
    core.validate_book(job, translated=True)
    digest = core.content_digest(job)
    report = core.load_json(contained(job, "build/verification.json"))
    checks = report.get("checks")
    if report.get("content_digest") != digest or report.get("passed") is not True:
        raise ValueError("Build is stale or failed; rebuild the current manuscript")
    if not isinstance(checks, dict) or not BUILD_CHECKS.issubset(checks) or any(checks[key] is not True for key in BUILD_CHECKS):
        raise ValueError("Build verification lacks successful required checks")
    pdf = contained(job, "build/book.pdf")
    if not pdf.is_file() or not pdf.stat().st_size:
        raise ValueError("Current built PDF is missing or empty")
    with pdf.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("Built artifact is not a PDF")
    pdf_digest = digest_file(pdf)
    if report.get("pdf_sha256") != pdf_digest:
        raise ValueError("Build PDF is stale or changed since verification; rebuild before review")
    return {"content_digest": digest, "pdf_sha256": pdf_digest, "verification_sha256": digest_file(job / "build/verification.json")}


def latest_stage_receipt(job: Path, data: dict, stage: str) -> dict:
    event = next((item for item in reversed(data["history"]) if item.get("event") == f"stage_{stage}"), None)
    if not event:
        raise ValueError(f"No complete {stage} content checkpoint; hand-staged files cannot advance this workflow")
    receipt_path = contained(job, event.get("receipt", ""))
    if not receipt_path.is_file() or digest_file(receipt_path) != event.get("receipt_sha256"):
        raise ValueError(f"Missing or changed {stage} content checkpoint")
    receipt = core.load_json(receipt_path)
    selected = data["models"][stage]
    selector = core.admit_model(**selected)
    if receipt.get("stage") != stage or receipt.get("completed") is not True:
        raise ValueError(f"Invalid {stage} content checkpoint")
    if receipt.get("selector") != selector or any(receipt.get(key) != selected[key] for key in ("provider", "model")):
        raise ValueError(f"{stage.capitalize()} checkpoint does not match configured model choice")
    if receipt.get("source_digest") != source_digest(job):
        raise ValueError(f"{stage.capitalize()} checkpoint belongs to an earlier source seal")
    validate_checkpoint(job, receipt, stage)
    return receipt


def terminology_ready(job: Path, data: dict) -> dict:
    receipt = latest_stage_receipt(job, data, "terminology")
    terms = core.load_json(job / "terms.json")
    core.validate_document("terms", terms)
    handoff = (job / "handoff.md").read_text(encoding="utf-8")
    if not handoff.strip() or not receipt.get("terms_sha256") == digest_file(job / "terms.json") or receipt.get("handoff_sha256") != digest_file(job / "handoff.md"):
        raise ValueError("Terminology/handoff changed after admitted stage execution; rerun terminology")
    return receipt


def translation_ready(job: Path, data: dict) -> tuple[dict, dict]:
    terminology_ready(job, data)
    receipt = latest_stage_receipt(job, data, "translation")
    build = current_build(job)
    # Authorship binds immutable content; compiler metadata may change PDF bytes on a rebuild.
    if receipt.get("round") != data["round"] or receipt.get("content_digest") != build["content_digest"]:
        raise ValueError("Translation receipt is stale; current content lacks admitted stage provenance")
    if "authoring_receipt" in receipt:
        event = next((item for item in data["history"] if item.get("event") == "translation_content_authored"
                      and item.get("receipt") == receipt["authoring_receipt"]
                      and item.get("receipt_sha256") == receipt.get("authoring_receipt_sha256")), None)
        if event is None:
            raise ValueError("Translation lacks its immutable authoring proof")
        proof = translation_authoring_proof(job, data, event)
        provenance = ("plan", "plan_sha256", "unit_checkpoints", "merged_document", "merged_document_sha256",
                      "merged_document_digest", "execution", "content_digest") if proof.get("execution") == "units" else ("task", "content_digest")
        if receipt["round"] != proof["base_round"] + 1 or any(receipt.get(key) != proof.get(key) for key in provenance):
            raise ValueError("Translation receipt differs from its authoring proof")
    return receipt, build


def init_job(source: Path, job: Path, title: str | None, source_language: str, target_language: str, max_rounds: int = 3) -> dict:
    source = source.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".pdf", ".epub", ".mobi", ".djvu", ".djv"}:
        raise ValueError("Source must be a PDF, EPUB, MOBI or DjVu file")
    if isinstance(max_rounds, bool) or max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    if not source_language.strip() or not target_language.strip():
        raise ValueError("Source and target languages must be explicit")
    job.mkdir(parents=True, exist_ok=False)
    try:
        (job / "evidence").mkdir()
        copy = job / "evidence" / f"source{source.suffix.lower()}"
        shutil.copyfile(source, copy)
        data = {"version": 1, "title": title or source.stem, "source_language": source_language, "target_language": target_language,
                "source_file": copy.relative_to(job).as_posix(), "source_sha256": digest_file(copy), "max_rounds": max_rounds, "round": 0,
                "state": "initialized", "models": {role: {"provider": "", "model": ""} for role in ROLES},
                "layout": dict(LAYOUT), "history": []}
        save_job(job, data, "initialized")
        return data
    except Exception:
        # Only this newly created directory belongs to this operation.
        shutil.rmtree(job)
        raise


def extract_job(job: Path, ocr: str = "auto", language: str = "eng", dpi: int = 200) -> dict:
    data = load_job(job)
    require_models(data)
    if data["state"] != "initialized":
        raise ValueError("Extraction requires a fresh initialized job; do not overwrite source evidence")
    result = importlib.import_module("extract").extract(contained(job, data["source_file"]), job, ocr=ocr, language=language, dpi=dpi)
    data["state"] = "extracted"
    save_job(job, data, "extracted", extraction_sha256=digest_file(job / "extraction.json"))
    return result


def archive_reviews(job: Path, data: dict, previous_seal: str) -> str | None:
    """Move only journal-owned review pairs; preserve arbitrary user files and audit links."""
    records = []
    for event in data["history"]:
        number = event.get("round")
        if event.get("event") != "review_submitted" or not isinstance(number, int):
            continue
        relative = f"reviews/round-{number}.receipt.json"
        if event.get("receipt") != relative:
            continue
        receipt = contained(job, relative)
        report = contained(job, f"reviews/round-{number}.json")
        if not receipt.is_file() or digest_file(receipt) != event.get("receipt_sha256") or not report.is_file():
            raise ValueError("Cannot archive missing or changed journal-owned review records")
        records.append((event, receipt, report))
    if not records:
        return None
    archive = contained(job, f"reviews/archive/source-{previous_seal[:16]}-{uuid.uuid4().hex[:12]}")
    archive.mkdir(parents=True, exist_ok=False)
    for event, receipt, report in records:
        receipt.rename(archive / receipt.name)
        report.rename(archive / report.name)
        event["receipt"] = (archive / receipt.name).relative_to(job).as_posix()
    return archive.relative_to(job).as_posix()



def seal_job(job: Path, reseal: bool = False) -> dict:
    data = load_job(job)
    already = (job / "source.sha256").exists()
    if already and not reseal:
        raise ValueError("Source is already sealed; use seal-source --reseal for deliberate correction")
    if not already and reseal:
        raise ValueError("No source seal exists; omit --reseal for the first seal")
    if not already and data["state"] != "extracted":
        raise ValueError("Extract and inspect the source before sealing")
    previous_seal = (job / "source.sha256").read_text(encoding="ascii").strip() if already else None
    source_inventory_coverage(job)
    snapshot = core.source_snapshot_digest(job)
    if previous_seal == snapshot:
        raise ValueError("Source seal is unchanged; resealing cannot reset the review-round limit")
    source_receipt = latest_role_receipt(job, data, "source")
    if (source_receipt.get("source_snapshot_digest") != snapshot
            or source_receipt.get("source_document_sha256") != digest_file(job / "book-source.json")
            or source_receipt.get("revision") is not reseal):
        raise ValueError("Source correction lacks a current complete source checkpoint; record source with explicit revision intent")
    source_event = next(item for item in reversed(data["history"]) if item.get("event") == "role_source")
    seal = core.seal_source(job)
    archive = archive_reviews(job, data, previous_seal) if already else None
    invalidate_build(job)
    data["state"] = "source_ready"
    # A deliberate source revision starts a new pipeline, with old receipts retained for audit.
    data["round"] = 0
    save_job(job, data, "source_resealed" if already else "source_sealed", source_digest=seal, archived_reviews=archive,
             source_receipt=source_event["receipt"], source_receipt_sha256=source_event["receipt_sha256"])
    return data


def require_models(data: dict) -> None:
    missing = [role for role in ROLES if not data["models"].get(role, {}).get("provider") or not data["models"].get(role, {}).get("model")]
    if missing:
        raise ValueError("Ask the user to select exact provider/model IDs for every workflow role before source work or inference; unselected: " + ", ".join(missing))


def configure_model(job: Path, stage: str, provider: str, model: str) -> dict:
    if stage not in ROLES:
        raise ValueError("Unknown workflow role")
    selector = core.admit_model(provider, model)
    selected = {"provider": provider, "model": model}
    data = load_job(job, configuring=True)
    if data["models"].get(stage) == selected:
        return {"selector": selector, "changed": False}
    data["models"][stage] = selected
    invalidate_output(job)
    if stage in STAGES and data["state"] not in {"initialized", "extracted", "source_ready"}:
        if stage == "terminology":
            data["state"] = "source_ready"
        else:
            data["state"] = "exhausted" if data["round"] >= data["max_rounds"] else "changes_requested" if data["round"] else "terminology_ready"
    save_job(job, data, "model_configured", configuring=True, stage=stage, selector=selector)
    return {"selector": selector, "changed": True}


def role_readiness(job: Path, role: str, *, revise: bool = False) -> tuple[dict, dict, str, str | None, dict]:
    """Check book-stage prerequisites without preparing or authorizing execution."""
    if role not in ROLES or (revise and role not in {"source", "terminology"}):
        raise ValueError("Revision requires source or terminology; choose one of the four workflow roles")
    data = load_job(job)
    require_models(data)
    selected = data["models"][role]
    selector = core.admit_model(**selected)
    sealed = (job / "source.sha256").exists()
    bindings = {}
    seal = None
    if role == "source":
        if revise:
            if not sealed:
                raise ValueError("Source revision requires an existing seal; initial source must omit --revise")
        elif data["state"] != "extracted" or sealed:
            raise ValueError("Source requires an extracted, unsealed job; use --revise for sealed source correction")
        if sealed:
            seal = (job / "source.sha256").read_text(encoding="ascii").strip()
            bindings["source_seal_sha256"] = digest_file(job / "source.sha256")
    else:
        if role == "terminology":
            if revise:
                if data["state"] != "terminology_ready" or data["round"] != 0:
                    raise ValueError("Terminology revision requires terminology_ready at round 0 before translation")
                latest_stage_receipt(job, data, "terminology")
                event = next(item for item in reversed(data["history"]) if item.get("event") == "stage_terminology")
                bindings.update(prior_receipt=event["receipt"], prior_receipt_sha256=event["receipt_sha256"])
            elif data["state"] != "source_ready":
                raise ValueError("Terminology requires source_ready")
        elif role == "translation":
            if data["state"] not in {"terminology_ready", "changes_requested"}:
                raise ValueError("Translation requires terminology_ready or changes_requested; submit the current review first")
            if data["round"] >= data["max_rounds"]:
                raise ValueError("Review/translation round limit exhausted")
            terminology_ready(job, data)
            event = next(item for item in reversed(data["history"]) if item.get("event") == "stage_terminology")
            bindings.update(terminology_receipt=event["receipt"], terminology_receipt_sha256=event["receipt_sha256"],
                            terms_sha256=digest_file(job / "terms.json"), handoff_sha256=digest_file(job / "handoff.md"))
        else:
            if data["state"] != "translated":
                raise ValueError("Review requires translated state")
            _, bindings["build"] = translation_ready(job, data)
        seal = source_digest(job)
        bindings["source_seal_sha256"] = digest_file(job / "source.sha256")
    return data, selected, selector, seal, bindings


def plan_units(job: Path, role: str, pages_per_unit: int, *, draft: Path | None = None, revise: bool = False) -> dict:
    job = Path(job).resolve(strict=True)
    _, _, _, seal, bindings = role_readiness(job, role, revise=revise)
    return importlib.import_module("units").create_plan(
        job, role, pages_per_unit=pages_per_unit, draft_path=draft, revise=revise,
        readiness={"source_digest": seal, "bindings": bindings})


def validate_checkpoint(job: Path, receipt: dict, role: str) -> None:
    """Validate book checkpoint bindings, not provider events or native journals."""
    if receipt.get("execution") == "units":
        importlib.import_module("units").validate_aggregate(job, receipt, role)
        return
    if (receipt.get("kind") not in {"book-role-checkpoint", "translation-content-authored", "translation-completed"}
            or receipt.get("stage") != role or receipt.get("role") != role
            or receipt.get("source_file_sha256") != load_job(job)["source_sha256"]):
        raise ValueError("Invalid book role checkpoint")
    selected = {key: receipt.get(key) for key in ("provider", "model")}
    if receipt.get("selector") != core.admit_model(**selected):
        raise ValueError("Book checkpoint model reference is inconsistent")
    importlib.import_module("units").task_metadata(receipt.get("task"), role, selected)


def latest_role_receipt(job: Path, data: dict, role: str) -> dict:
    event = next((item for item in reversed(data["history"]) if item.get("event") == f"role_{role}"), None)
    if event is None:
        raise ValueError(f"No complete {role} content checkpoint")
    path = contained(job, event.get("receipt", ""))
    if not path.is_file() or digest_file(path) != event.get("receipt_sha256"):
        raise ValueError(f"Missing or changed {role} checkpoint")
    receipt = core.load_json(path)
    selected = data["models"][role]
    expected_kind = "unit-role-completed" if receipt.get("execution") == "units" else "book-role-checkpoint"
    if (receipt.get("kind") != expected_kind or receipt.get("role") != role or receipt.get("completed") is not True
            or receipt.get("selector") != core.admit_model(**selected)
            or any(receipt.get(key) != selected[key] for key in ("provider", "model"))
            or receipt.get("source_file_sha256") != data["source_sha256"]):
        raise ValueError(f"Invalid {role} content checkpoint")
    validate_checkpoint(job, receipt, role)
    return receipt


def checkpoint_unit(job: Path, role: str, unit_id: str, task_result: Path) -> dict:
    job = Path(job).resolve(strict=True)
    data = load_job(job)
    require_models(data)
    result = importlib.import_module("units").checkpoint_unit(job, role, unit_id, core.load_json(task_result))
    return {**result, "state": data["state"], "round": data["round"], "role": role}


def import_checkpoints(job: Path, role: str, plan: Path) -> dict:
    job = Path(job).resolve(strict=True)
    data = load_job(job)
    require_models(data)
    return importlib.import_module("units").import_checkpoints(job, role, plan)


def assemble_units(job: Path, role: str) -> dict:
    """Publish complete book content before applying the existing stage transitions."""
    job = Path(job).resolve(strict=True)
    unit_module = importlib.import_module("units")
    progress = unit_module.status(job, role)
    revision = progress["revision"]
    data, selected, selector, seal, bindings = role_readiness(job, role, revise=revision)
    if progress["pending"]:
        raise ValueError("Every planned unit must be checkpointed before whole-role assembly")
    if any(item.get("unit_plan") == progress["plan"] for item in data["history"]):
        raise ValueError("Unit plan already consumed; use pending translation finalization after a build failure")
    original_job = digest_file(job / "job.json")
    aggregate = unit_module.assemble_units(job, role)
    expected = {"kind": "unit-role-completed", "execution": "units", "completed": True,
                "role": role, "stage": role, "provider": selected["provider"], "model": selected["model"],
                "selector": selector, "source_file_sha256": data["source_sha256"],
                "source_digest": seal, "revision": revision, "base_state": data["state"], "base_round": data["round"],
                "plan": progress["plan"], "plan_sha256": progress["plan_sha256"]}
    if digest_file(job / "job.json") != original_job or any(aggregate.get(key) != value for key, value in expected.items()):
        raise ValueError("Unit aggregate differs from current book/model/context")
    if role == "source":
        source_inventory_coverage(job)
        if (aggregate.get("source_document_sha256") != digest_file(job / "book-source.json")
                or aggregate.get("source_snapshot_digest") != core.source_snapshot_digest(job)):
            raise ValueError("Assembled source lacks exact current document/snapshot bindings")
    elif role == "translation":
        event = next(item for item in reversed(data["history"]) if item.get("event") == "stage_terminology")
        aggregate.update(kind="translation-content-authored", completed=False, authoring_complete=True,
                         content_digest=core.content_digest(job), job_path=str(job),
                         job_context_sha256=translation_context_digest(data),
                         terminology_receipt=event["receipt"], terminology_receipt_sha256=event["receipt_sha256"],
                         terms_sha256=bindings["terms_sha256"], handoff_sha256=bindings["handoff_sha256"])
    else:
        _, build = translation_ready(job, data)
        report_path = contained(job, f"reviews/round-{data['round']}.json")
        report = core.load_json(report_path)
        core.validate_document("review", report)
        if (report["round"] != data["round"] or aggregate.get("round") != data["round"]
                or aggregate.get("review_sha256") != digest_file(report_path)
                or any(report.get(key) != build[key] for key in ("content_digest", "pdf_sha256"))
                or any(aggregate.get(key) != value for key, value in build.items())):
            raise ValueError("Assembled review describes a different manuscript/PDF/build")
    validate_checkpoint(job, aggregate, role)
    invalidate_output(job)
    receipt_path = contained(job, f"provenance/{role}-units-{uuid.uuid4().hex}.json")
    core.save_json(receipt_path, aggregate)
    details = {"receipt": receipt_path.relative_to(job).as_posix(), "receipt_sha256": digest_file(receipt_path),
               "unit_plan": aggregate["plan"], "unit_plan_sha256": aggregate["plan_sha256"]}
    if role == "translation":
        save_job(job, data, "translation_content_authored", **details, round=data["round"], state=data["state"])
        return {**finalize_translation(job), "role": role}
    save_job(job, data, f"role_{role}", **details)
    return {"state": data["state"], "round": data["round"], "role": role, "receipt": str(receipt_path),
            "provider": selected["provider"], "model": selected["model"], "execution": "units"}


def checkpoint_role(job: Path, role: str, task_result: Path, *, revise: bool = False) -> dict:
    """Checkpoint complete small-role book artifacts after an ordinary native task."""
    job = Path(job).resolve(strict=True)
    data, selected, selector, seal, bindings = role_readiness(job, role, revise=revise)
    unit_module = importlib.import_module("units")
    if role in {"source", "translation", "review"} and unit_module.page_count(job) > 8:
        raise ValueError("Whole-role checkpoint exceeds eight source pages; checkpoint and assemble bounded units")
    task = unit_module.task_metadata(core.load_json(task_result), role, selected)
    receipt = {"version": 1, "kind": "book-role-checkpoint", "role": role, "stage": role, "completed": True,
               **selected, "selector": selector, "task": task, "source_digest": seal,
               "revision": revise, "source_file_sha256": data["source_sha256"], "bindings": bindings}
    if role == "source":
        source_inventory_coverage(job)
        receipt.update(source_document_sha256=digest_file(job / "book-source.json"),
                       source_snapshot_digest=core.source_snapshot_digest(job))
    elif role == "terminology":
        core.validate_document("terms", core.load_json(job / "terms.json"))
        if not (job / "handoff.md").read_text(encoding="utf-8").strip():
            raise ValueError("Terminology did not produce a substantive handoff")
        receipt.update(terms_sha256=digest_file(job / "terms.json"), handoff_sha256=digest_file(job / "handoff.md"))
    elif role == "translation":
        event = next(item for item in reversed(data["history"]) if item.get("event") == "stage_terminology")
        receipt.update(kind="translation-content-authored", completed=False, authoring_complete=True,
                       content_digest=core.content_digest(job), job_path=str(job),
                       job_context_sha256=translation_context_digest(data), base_state=data["state"], base_round=data["round"],
                       terminology_receipt=event["receipt"], terminology_receipt_sha256=event["receipt_sha256"],
                       terms_sha256=bindings["terms_sha256"], handoff_sha256=bindings["handoff_sha256"])
    else:
        build = bindings["build"]
        report_path = contained(job, f"reviews/round-{data['round']}.json")
        report = core.load_json(report_path)
        core.validate_document("review", report)
        if report["round"] != data["round"] or any(report.get(key) != build[key] for key in ("content_digest", "pdf_sha256")):
            raise ValueError("Review describes different manuscript/PDF identities")
        receipt.update(round=data["round"], **build, review_sha256=digest_file(report_path))
    validate_checkpoint(job, receipt, role)
    invalidate_output(job)
    directory = contained(job, "provenance")
    directory.mkdir(exist_ok=True)
    receipt_path = directory / f"{role}-{'authored-' if role == 'translation' else ''}{uuid.uuid4().hex}.json"
    core.save_json(receipt_path, receipt)
    details = {"receipt": receipt_path.relative_to(job).as_posix(), "receipt_sha256": digest_file(receipt_path)}
    if role == "translation":
        save_job(job, data, "translation_content_authored", **details, round=data["round"], state=data["state"])
        return {**finalize_translation(job), "role": role}
    if role == "terminology":
        data["state"] = "terminology_ready"
        save_job(job, data, "stage_terminology", **details, round=data["round"], revision=revise)
    else:
        save_job(job, data, f"role_{role}", **details)
    return {"state": data["state"], "round": data["round"], "role": role, "receipt": str(receipt_path),
            "provider": selected["provider"], "model": selected["model"]}


def translation_context_digest(data: dict) -> str:
    """Bind the exact pre-authoring controller context, including its audit history."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def translation_authoring_proof(job: Path, data: dict, event: dict) -> dict:
    path = contained(job, event.get("receipt", ""))
    if not path.is_file() or digest_file(path) != event.get("receipt_sha256"):
        raise ValueError("Missing or changed translation authoring checkpoint")
    proof = core.load_json(path)
    selected = data["models"]["translation"]
    selector = core.admit_model(**selected)
    if (proof.get("kind") != "translation-content-authored" or proof.get("stage") != "translation"
            or proof.get("completed") is not False or proof.get("authoring_complete") is not True
            or proof.get("selector") != selector
            or any(proof.get(key) != selected[key] for key in ("provider", "model"))):
        raise ValueError("Invalid complete translation authoring checkpoint")
    base_round = proof.get("base_round")
    if (type(base_round) is not int or base_round < 0 or proof.get("base_state") not in {"terminology_ready", "changes_requested"}
            or event.get("round") != base_round or event.get("state") != proof["base_state"]):
        raise ValueError("Invalid translation authoring base state/round")
    base = {**data, "state": proof["base_state"], "round": base_round,
            "history": data["history"][:data["history"].index(event)]}
    if proof.get("job_path") != str(job.resolve()) or proof.get("job_context_sha256") != translation_context_digest(base):
        raise ValueError("Translation authoring job/model/context changed")
    if proof.get("source_digest") != source_digest(job) or proof.get("content_digest") != core.content_digest(job):
        raise ValueError("Translation authoring manuscript/source/layout/assets changed")
    terminology_ready(job, data)
    terminology_event = next(item for item in reversed(data["history"]) if item.get("event") == "stage_terminology")
    if (proof.get("terminology_receipt") != terminology_event.get("receipt")
            or proof.get("terminology_receipt_sha256") != terminology_event.get("receipt_sha256")
            or proof.get("terms_sha256") != digest_file(job / "terms.json")
            or proof.get("handoff_sha256") != digest_file(job / "handoff.md")):
        raise ValueError("Translation authoring terminology context changed")
    validate_checkpoint(job, proof, "translation")
    return proof


def finalize_translation(job: Path) -> dict:
    """Rebuild admitted pending content without inference; never release or reuse a PDF."""
    data = load_job(job)
    if data["state"] not in {"terminology_ready", "changes_requested"}:
        raise ValueError("Finalization requires pending translation at terminology_ready or changes_requested")
    if data["round"] >= data["max_rounds"]:
        raise ValueError("Review/translation round limit exhausted")
    event = data["history"][-1] if data["history"] else {}
    if event.get("event") != "translation_content_authored":
        raise ValueError("No current admitted pending translation authoring proof; hand-staged files cannot be finalized")
    proof = translation_authoring_proof(job, data, event)
    if data["state"] != proof["base_state"] or data["round"] != proof["base_round"]:
        raise ValueError("Pending translation authoring state/round changed")
    if any(item.get("event") == "stage_translation" and item.get("authoring_receipt") == event["receipt"] for item in data["history"]):
        raise ValueError("Translation authoring proof already finalized; replay is prohibited")
    original_job = digest_file(job / "job.json")
    invalidate_output(job)
    importlib.import_module("render").build(job)
    build = current_build(job)
    if digest_file(job / "job.json") != original_job:
        raise ValueError("Controller context changed during translation build")
    translation_authoring_proof(job, data, event)
    receipt = {**proof, **build, "kind": "translation-completed", "completed": True,
               "round": data["round"] + 1, "authoring_receipt": event["receipt"],
               "authoring_receipt_sha256": event["receipt_sha256"]}
    receipt_path = contained(job, f"provenance/translation-{uuid.uuid4().hex}.json")
    core.save_json(receipt_path, receipt)
    data["round"] += 1
    data["state"] = "translated"
    save_job(job, data, "stage_translation", receipt=receipt_path.relative_to(job).as_posix(),
             receipt_sha256=digest_file(receipt_path), round=data["round"], revision=False,
             authoring_receipt=event["receipt"], authoring_receipt_sha256=event["receipt_sha256"])
    return {"state": data["state"], "round": data["round"], "receipt": str(receipt_path),
            "provider": proof["provider"], "model": proof["model"]}





def submit_review(job: Path, report_path: Path) -> dict:
    data = load_job(job)
    if data["state"] != "translated" or data["round"] < 1:
        raise ValueError("Review requires a completed admitted translation round")
    _, build = translation_ready(job, data)
    report = core.load_json(report_path)
    core.validate_document("review", report)
    if report["round"] != data["round"]:
        raise ValueError("Review round does not match the current translation round")
    if any(report.get(key) != build[key] for key in ("content_digest", "pdf_sha256")):
        raise ValueError("Review describes different or stale manuscript/PDF artifacts; review the current build")
    checks = report.get("checks", {})
    if report["verdict"] == "pass" and (set(checks) != REVIEW_CHECKS or not all(value is True for value in checks.values()) or report["findings"]):
        raise ValueError("Passing review requires all checks true and no findings")
    directory = contained(job, "reviews")
    directory.mkdir(exist_ok=True)
    canonical = directory / f"round-{data['round']}.json"
    receipt_path = directory / f"round-{data['round']}.receipt.json"
    reviewer = latest_role_receipt(job, data, "review")
    if (reviewer.get("round") != data["round"] or reviewer.get("review_sha256") != digest_file(report_path)
            or any(reviewer.get(key) != value for key, value in build.items())):
        raise ValueError("Review lacks a current complete reviewer checkpoint for this exact PDF")
    reviewer_event = next(item for item in reversed(data["history"]) if item.get("event") == "role_review")
    if receipt_path.exists():
        raise ValueError("This round already has a submitted review; replay/replacement is prohibited")
    if Path(report_path).resolve() != canonical.resolve():
        shutil.copyfile(report_path, canonical)
    if digest_file(canonical) != reviewer["review_sha256"]:
        raise ValueError("Review report changed during coordinator submission")
    receipt = {"version": 1, "round": data["round"], "source_digest": source_digest(job), **build,
               "review_sha256": digest_file(canonical), "reviewer_receipt": reviewer_event["receipt"],
               "reviewer_receipt_sha256": reviewer_event["receipt_sha256"]}
    core.save_json(receipt_path, receipt)
    invalidate_output(job)
    data["state"] = "approved" if report["verdict"] == "pass" else "exhausted" if data["round"] >= data["max_rounds"] else "changes_requested"
    save_job(job, data, "review_submitted", round=data["round"], verdict=report["verdict"], receipt=receipt_path.relative_to(job).as_posix(), receipt_sha256=digest_file(receipt_path))
    return {"state": data["state"], "round": data["round"]}


def accept_job(job: Path) -> Path:
    data = load_job(job)
    invalidate_output(job)
    if data["state"] != "approved":
        raise ValueError("Acceptance requires a current passing submitted review")
    _, build = translation_ready(job, data)
    event = next((item for item in reversed(data["history"]) if item.get("event") == "review_submitted"), None)
    if not event or event.get("round") != data["round"] or event.get("verdict") != "pass":
        raise ValueError("No passing review provenance for the current round")
    receipt_path = contained(job, event["receipt"])
    if digest_file(receipt_path) != event.get("receipt_sha256"):
        raise ValueError("Review receipt changed after submission")
    receipt = core.load_json(receipt_path)
    report_path = contained(job, f"reviews/round-{data['round']}.json")
    report = core.load_json(report_path)
    core.validate_document("review", report)
    reviewer_path = contained(job, receipt.get("reviewer_receipt", ""))
    if not reviewer_path.is_file() or digest_file(reviewer_path) != receipt.get("reviewer_receipt_sha256"):
        raise ValueError("Submitted reviewer checkpoint is missing or changed")
    reviewer = core.load_json(reviewer_path)
    validate_checkpoint(job, reviewer, "review")
    if (reviewer.get("round") != data["round"] or reviewer.get("review_sha256") != digest_file(report_path)
            or reviewer.get("selector") != core.admit_model(**data["models"]["review"])
            or any(reviewer.get(key) != value for key, value in build.items())):
        raise ValueError("Submitted review no longer matches reviewer/model/build checkpoint bindings")
    if any(report.get(key) != build[key] for key in ("content_digest", "pdf_sha256")):
        raise ValueError("Authored review artifact identity is stale; acceptance refused")
    if receipt.get("round") != data["round"] or receipt.get("source_digest") != source_digest(job) or report.get("round") != data["round"] or report.get("verdict") != "pass" or digest_file(report_path) != receipt.get("review_sha256") or any(receipt.get(key) != value for key, value in build.items()):
        raise ValueError("Review, build or PDF is stale/changed; acceptance refused")
    output = job / "output.pdf"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".accepted-", suffix=".pdf", dir=job, delete=False) as stream:
            temporary = Path(stream.name)
        shutil.copyfile(contained(job, "build/book.pdf"), temporary)
        if digest_file(temporary) != build["pdf_sha256"]:
            raise ValueError("PDF changed during acceptance; no output was released")
        save_job(job, data, "accepted", round=data["round"], content_digest=build["content_digest"], pdf_sha256=build["pdf_sha256"])
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output


def continue_source(job: Path, provider: str, model: str) -> dict:
    """Change future model intent while retaining completed initial source content."""
    job = Path(job).resolve(strict=True)
    selector = core.admit_model(provider, model)
    data, _, previous_selector, _, _ = role_readiness(job, "source")
    selected = {"provider": provider, "model": model}
    future = {**data, "models": {role: dict(selected) for role in ROLES},
              "history": data["history"] + [{"event": "source_model_continued",
                  "at": datetime.now(timezone.utc).isoformat(), "selector": selector,
                  "previous_selector": previous_selector}]}
    validate_job_record(future)
    reference = importlib.import_module("units").continue_source(job, future)
    previous_job = contained(job, reference["previous_job"]["path"])
    snapshot = contained(job, reference["job_snapshot"]["path"])
    if digest_file(job / "job.json") != reference["previous_job"]["sha256"]:
        raise ValueError("Source continuation job changed before publication")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".source-model-", dir=job, delete=False) as stream:
            temporary = Path(stream.name)
        shutil.copyfile(snapshot, temporary)
        os.replace(temporary, job / "job.json")
        try:
            core.save_json(job / "units/source/active.json",
                           {key: reference[key] for key in ("plan", "plan_sha256")})
        except Exception:
            shutil.copyfile(previous_job, temporary)
            os.replace(temporary, job / "job.json")
            raise
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {**reference, "selector": selector, "models": future["models"],
            "state": future["state"], "round": future["round"]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    init = sub.add_parser("init")
    init.add_argument("source", type=Path)
    init.add_argument("job", type=Path)
    init.add_argument("--title")
    init.add_argument("--source-language", required=True)
    init.add_argument("--target-language", required=True)
    init.add_argument("--max-rounds", type=int, default=3)
    for name in ("extract", "seal-source", "validate", "render", "build", "configure-model", "continue-source", "checkpoint-role", "checkpoint-unit", "import-checkpoints", "finalize-translation", "plan-units", "unit-status", "assemble-units", "review", "accept", "status"):
        action = sub.add_parser(name)
        action.add_argument("job", type=Path)
        if name == "extract":
            action.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
            action.add_argument("--language", default="eng")
            action.add_argument("--dpi", type=int, default=200)
        elif name == "seal-source":
            action.add_argument("--reseal", action="store_true")
        elif name == "validate":
            action.add_argument("--source", action="store_true")
        elif name in {"configure-model", "continue-source"}:
            if name == "configure-model":
                action.add_argument("stage", choices=ROLES)
            action.add_argument("--provider", required=True)
            action.add_argument("--model", required=True)
        elif name == "checkpoint-role":
            action.add_argument("role", choices=ROLES)
            action.add_argument("--task-result", type=Path, required=True)
            action.add_argument("--revise", action="store_true")
        elif name in {"checkpoint-unit", "import-checkpoints", "plan-units", "unit-status", "assemble-units"}:
            action.add_argument("role", choices=("source", "translation", "review"))
            if name == "checkpoint-unit":
                action.add_argument("unit_id")
                action.add_argument("--task-result", type=Path, required=True)
            elif name == "import-checkpoints":
                action.add_argument("--plan", type=Path, required=True)
            elif name == "plan-units":
                action.add_argument("--pages-per-unit", type=int, required=True)
                action.add_argument("--draft", type=Path)
                action.add_argument("--revise", action="store_true")
        elif name == "review":
            action.add_argument("report", type=Path)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            output = doctor()
        elif CORE_IMPORT_ERROR:
            raise ValueError(f"Missing controller dependency: {CORE_IMPORT_ERROR}; run doctor")
        elif args.command == "init":
            output = init_job(args.source, args.job.absolute(), args.title, args.source_language, args.target_language, args.max_rounds)

        else:
            job = args.job.resolve(strict=True)
            # Workers may validate/build without changing the controller journal.
            if args.command in {"validate", "render", "build", "status", "unit-status"}:
                data = load_job(job)
                if args.command == "unit-status":
                    require_models(data)
                    output = importlib.import_module("units").status(job, args.role)
                elif args.command == "status":
                    output = {"state": data["state"], "round": data["round"], "max_rounds": data["max_rounds"], "models": data["models"], "output_exists": (job / "output.pdf").is_file()}
                    output["current_build"] = None
                    if (job / "build/verification.json").is_file():
                        try:
                            output["current_build"] = current_build(job)
                        except (ValueError, RuntimeError, OSError) as error:
                            output["build_error"] = str(error)
                elif args.command == "validate":
                    core.validate_book(job, translated=not args.source)
                    output = {"valid": True, "source_only": args.source}
                else:
                    invalidate_output(job)
                    path = getattr(importlib.import_module("render"), args.command)(job)
                    output = {"path": str(path)}
                    if args.command == "build":
                        output.update(current_build(job))
                        output["verification"] = str(job / "build/verification.json")
            else:
                with mutation_lock(job):
                    if args.command == "extract":
                        output = extract_job(job, args.ocr, args.language, args.dpi)
                    elif args.command == "seal-source":
                        output = seal_job(job, args.reseal)
                    elif args.command == "configure-model":
                        output = configure_model(job, args.stage, args.provider, args.model)
                    elif args.command == "continue-source":
                        output = continue_source(job, args.provider, args.model)
                    elif args.command == "checkpoint-role":
                        output = checkpoint_role(job, args.role, args.task_result, revise=args.revise)
                    elif args.command == "checkpoint-unit":
                        output = checkpoint_unit(job, args.role, args.unit_id, args.task_result)
                    elif args.command == "import-checkpoints":
                        output = import_checkpoints(job, args.role, args.plan)
                    elif args.command == "plan-units":
                        output = plan_units(job, args.role, args.pages_per_unit, draft=args.draft, revise=args.revise)
                    elif args.command == "assemble-units":
                        output = assemble_units(job, args.role)
                    elif args.command == "finalize-translation":
                        output = finalize_translation(job)
                    elif args.command == "review":
                        output = submit_review(job, args.report)
                    elif args.command == "accept":
                        output = {"path": str(accept_job(job))}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, ImportError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
