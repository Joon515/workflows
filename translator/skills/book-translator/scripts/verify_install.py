#!/usr/bin/env python3
"""Verify retained-package and complete project resource layouts without inference."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit


AGENTS = tuple(f"book-{role}" for role in ("source", "terminology", "translation", "review"))
SKILL = Path("skills/book-translator")
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def package_root(script=None):
    """Require the retained translator distribution, not a materialized .omp tree."""
    # Do not resolve symlinks: invoking the installed skill must fail closed even
    # when its whole directory points back to a valid retained distribution.
    script = Path(os.path.abspath(script if script is not None else __file__))
    root = script.parents[3]
    if (root.name != "translator"
            or script.relative_to(root) != SKILL / "scripts/verify_install.py"
            or not (root / "plugin.json").is_file()
            or not (root / "README.md").is_file()
            or not (root / SKILL / "SKILL.md").is_file()
            or any(not (root / "agents" / f"{name}.md").is_file() for name in AGENTS)):
        raise RuntimeError("Run verify_install.py from the retained translator/ distribution, "
                           "not from project .omp/skills/book-translator; no consumer .omp tree is a package")
    if json.loads((root / "plugin.json").read_text(encoding="utf-8")).get("name") != "book-translator":
        raise RuntimeError(f"Unrecognized translator distribution: {root}")
    return root


def materialize_project(copied, project, symlinks=False):
    """In disposable verification projects, materialize four agents and one full skill."""
    copied = package_root(Path(copied) / SKILL / "scripts/verify_install.py")
    project = Path(os.path.abspath(project))
    pairs = [(copied / "agents" / f"{name}.md", project / ".omp/agents" / f"{name}.md")
             for name in AGENTS]
    pairs.append((copied / SKILL, project / ".omp" / SKILL))
    # Inspect every destination and parent before making even a directory.
    # lexists includes dangling links; existing unrelated siblings are allowed.
    conflicts = [str(target) for _, target in pairs if os.path.lexists(target)]
    for parent in (project / ".omp", project / ".omp/agents", project / ".omp/skills"):
        if os.path.lexists(parent) and (parent.is_symlink() or not parent.is_dir()):
            conflicts.append(str(parent))
    if conflicts:
        raise FileExistsError("Resource destinations must all be absent: " + ", ".join(conflicts))
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if symlinks:
            target.symlink_to(os.path.relpath(source, target.parent), target_is_directory=source.is_dir())
        elif source.is_dir():
            shutil.copytree(source, target, ignore=COPY_IGNORE)
        else:
            shutil.copy2(source, target)
    return project / ".omp"


def skill_inventory(skill):
    """Inventory every shipped skill file, excluding only Python bytecode caches."""
    return {str(path.relative_to(skill)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(skill.rglob("*"))
            if path.is_file() and "__pycache__" not in path.relative_to(skill).parts
            and path.suffix not in (".pyc", ".pyo")}


def inspect_resources(copied, materialized):
    """Assert byte completeness and links interpreted from materialized lexical paths."""
    skill = materialized / SKILL
    inventory = skill_inventory(skill)
    if inventory != skill_inventory(copied / SKILL):
        raise RuntimeError(f"Materialized skill inventory/hash mismatch: {skill}")
    agents = {}
    documents = [materialized / "agents" / f"{name}.md" for name in AGENTS]
    for document in documents:
        digest = hashlib.sha256(document.read_bytes()).hexdigest()
        if digest != hashlib.sha256((copied / "agents" / document.name).read_bytes()).hexdigest():
            raise RuntimeError(f"Materialized agent hash mismatch: {document}")
        agents[document.name] = digest
    documents += sorted(skill.rglob("*.md"))
    references = []
    for document in documents:
        for match in re.finditer(r"(?<!!)\[[^\]]*\]\(([^\s)]+)\)", document.read_text(encoding="utf-8")):
            target = match.group(1)
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            # Normalize '..' lexically BEFORE filesystem traversal. Resolving the
            # source realpath first would conceal a broken installed-skill link.
            lexical = Path(os.path.abspath(document.parent / unquote(parsed.path)))
            if not lexical.exists():
                raise RuntimeError(f"Missing materialized lexical reference: {document}: {target} -> {lexical}")
            references.append({"document": str(document), "target": target,
                               "lexical_target": str(lexical)})
    return {"skill_files": inventory, "agent_files": agents, "lexical_references": references}


def inspect_runtime(skill, project, environment):
    """Import shipped modules and run doctor through the selected skill path."""
    scripts = skill / "scripts"
    probe = ("import importlib,json,pathlib,sys; sys.path.insert(0,sys.argv[1]); "
             "modules=[importlib.import_module(name) for name in "
             "('core','extract','render','translator','units')]; "
             "assert all(pathlib.Path(module.__file__).absolute().parent == pathlib.Path(sys.argv[1]) "
             "for module in modules); "
             "print(json.dumps({module.__name__:module.__file__ for module in modules}))")
    imports = subprocess.run([sys.executable, "-B", "-c", probe, str(scripts)], cwd=project,
                             env=environment, text=True, capture_output=True, timeout=60)
    if imports.returncode:
        raise RuntimeError(imports.stderr or imports.stdout)
    doctor = subprocess.run([sys.executable, "-B", str(scripts / "translator.py"), "doctor"],
                            cwd=project, env=environment, text=True, capture_output=True, timeout=120)
    if doctor.returncode:
        raise RuntimeError(doctor.stderr or doctor.stdout)
    return {"imports": json.loads(imports.stdout), "doctor": json.loads(doctor.stdout)}


def inspect_frontmatter(copied):
    """Check portable definitions; actual name discovery is inspected through the CLI."""
    definitions = {}
    for name in AGENTS:
        text = (copied / "agents" / f"{name}.md").read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise RuntimeError(f"Missing native frontmatter: {name}")
        frontmatter = text.split("---", 2)[1]
        fields = dict(re.findall(r"^([A-Za-z]+):\s*(.*?)\s*$", frontmatter, re.MULTILINE))
        if fields.get("name") != name or fields.get("model") != '"@task"':
            raise RuntimeError(f"Expected portable native name/model frontmatter: {name}")
        definitions[name] = {"name": name, "model": "@task"}
    return definitions


def inspect_cli(executable, project, copied, environment, plugin_active):
    command = [executable, "--mode", "rpc", "--model", "anthropic/claude-sonnet-4-5",
               "--no-session", "--no-title", "--no-lsp", "--no-extensions"]
    if plugin_active:
        command += ["--plugin-dir", str(copied)]
    requests = [{"id": "commands", "type": "get_available_commands"},
                {"id": "state", "type": "get_state"}]
    result = subprocess.run(command, cwd=project, env=environment, text=True,
                            input="".join(json.dumps(row) + "\n" for row in requests),
                            capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    catalog = next(row for row in responses if row.get("id") == "commands")
    state = next(row for row in responses if row.get("id") == "state")
    if catalog.get("success") is not True or state.get("success") is not True:
        raise RuntimeError(f"CLI metadata request failed: {responses}")
    commands = [row for row in catalog["data"]["commands"]
                if row["name"] == "skill:book-translator"]
    task = next(item for item in state["data"]["dumpTools"] if item["name"] == "task")
    agents = [name for name in AGENTS if name in task["description"]]
    if state["data"]["messageCount"] != 0 or state["data"]["isStreaming"] is not False:
        raise RuntimeError("Discovery inspection must not start a model conversation")
    return commands, agents


def main():
    plugin = package_root()
    executable = shutil.which("omp")
    if not executable:
        raise SystemExit("omp must be on PATH")
    with tempfile.TemporaryDirectory(prefix="book-translator-install-") as temporary:
        for container in (".agents", ".omp"):
            for activation in ("copied-only", "plugin-dir", "project-copy", "project-symlink"):
                root = Path(temporary) / container[1:] / activation
                project, home, agent_home = (root / name for name in ("project", "home", "agent"))
                for directory in (project, home, agent_home):
                    directory.mkdir(parents=True)
                copied = project / container / "translator"
                shutil.copytree(plugin, copied, ignore=COPY_IGNORE)
                materialized = copied
                if activation in ("project-copy", "project-symlink"):
                    materialized = materialize_project(copied, project, activation == "project-symlink")
                definitions = inspect_frontmatter(materialized)
                resources = inspect_resources(copied, materialized)
                environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(home),
                               "PI_CODING_AGENT_DIR": str(agent_home), "TERM": "dumb",
                               "PYTHONDONTWRITEBYTECODE": "1"}
                runtime = inspect_runtime(materialized / SKILL, project, environment)
                version = subprocess.run([executable, "--version"], cwd=project, env=environment,
                                         check=True, text=True, capture_output=True, timeout=30).stdout.strip()
                commands, agents = inspect_cli(executable, project, copied, environment,
                                               activation == "plugin-dir")
                expected_active = activation != "copied-only"
                if len(commands) != int(expected_active) or any(row["source"] != "skill" for row in commands):
                    raise RuntimeError(f"Unexpected skill discovery for {container}/{activation}: {commands}")
                if len(agents) != len(AGENTS) * int(expected_active):
                    raise RuntimeError(f"Unexpected agent discovery for {container}/{activation}: {agents}")
                print(json.dumps({"check": "copied-native-resource-discovery", "container": container,
                                  "activation": activation, "version": version, "commands": commands,
                                  "native_agents": agents, "portable_frontmatter": definitions,
                                  "resources": resources, "runtime": runtime,
                                  "model_prompts": 0, "forwarded_credentials": 0}))


if __name__ == "__main__":
    main()
