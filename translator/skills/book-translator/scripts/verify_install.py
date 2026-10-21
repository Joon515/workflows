#!/usr/bin/env python3
"""Inspect copied skill and native agent discovery through OMP, without inference."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


AGENTS = tuple(f"book-{role}" for role in ("source", "terminology", "translation", "review"))


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
    executable = shutil.which("omp")
    if not executable:
        raise SystemExit("omp must be on PATH")
    plugin = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="book-translator-install-") as temporary:
        for container in (".agents", ".omp"):
            for activation in ("copied-only", "plugin-dir", "project-agents"):
                root = Path(temporary) / container[1:] / activation
                project, home, agent_home = (root / name for name in ("project", "home", "agent"))
                for directory in (project, home, agent_home):
                    directory.mkdir(parents=True)
                copied = project / container / "translator"
                shutil.copytree(plugin, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                definitions = inspect_frontmatter(copied)
                if activation == "project-agents":
                    native = project / ".omp" / "agents"
                    native.mkdir(parents=True)
                    for name in AGENTS:
                        shutil.copy2(copied / "agents" / f"{name}.md", native / f"{name}.md")
                environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(home),
                               "PI_CODING_AGENT_DIR": str(agent_home), "TERM": "dumb"}
                version = subprocess.run([executable, "--version"], cwd=project, env=environment,
                                         check=True, text=True, capture_output=True, timeout=30).stdout.strip()
                commands, agents = inspect_cli(executable, project, copied, environment,
                                               activation == "plugin-dir")
                expected_skill = activation == "plugin-dir"
                expected_agents = activation != "copied-only"
                if len(commands) != int(expected_skill) or any(row["source"] != "skill" for row in commands):
                    raise RuntimeError(f"Unexpected skill discovery for {container}/{activation}: {commands}")
                if len(agents) != len(AGENTS) * int(expected_agents):
                    raise RuntimeError(f"Unexpected agent discovery for {container}/{activation}: {agents}")
                print(json.dumps({"check": "copied-native-resource-discovery", "container": container,
                                  "activation": activation, "version": version, "commands": commands,
                                  "native_agents": agents, "portable_frontmatter": definitions,
                                  "model_prompts": 0, "forwarded_credentials": 0}))


if __name__ == "__main__":
    main()
