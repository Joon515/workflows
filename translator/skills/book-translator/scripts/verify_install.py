#!/usr/bin/env python3
"""Exercise copied skill, native agents and hook activation without model prompts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


AGENTS = tuple(f"book-{role}" for role in ("source", "terminology", "translation", "review"))
TOOLS = ("book_translator_prepare", "book_translator_finish")
HANDLERS = ("before_subagent_spawn", "before_agent_start", "session_start", "tool_result")


def extension_loader(executable):
    """Resolve the SDK shipped with this actual omp executable, not a checkout."""
    for parent in Path(executable).resolve().parents:
        candidate = parent / "src/extensibility/extensions/loader.ts"
        if candidate.is_file():
            return candidate
    raise RuntimeError("The installed omp SDK extension loader is required for hook activation inspection")


def inspect_hook(bun, loader, project, hook, environment, active):
    # Use the same native loader as -e. Factory registration complements the
    # actual CLI session-start/tool discovery below; it does not prove inference.
    program = """
const { discoverAndLoadExtensions } = await import(LOADER);
const loaded = await discoverAndLoadExtensions(PATHS, CWD, undefined, undefined, {ambient:false});
if (loaded.errors.length) throw new Error(JSON.stringify(loaded.errors));
const tools = [...new Set(loaded.extensions.flatMap(extension => [...extension.tools.keys()]))];
const handlers = [...new Set(loaded.extensions.flatMap(extension => [...extension.handlers.keys()]))];
console.log('BOOK_TRANSLATOR_HOOK_PROBE=' + JSON.stringify({tools, handlers, extensions:loaded.extensions.map(extension => extension.path)}));
"""
    program = (program.replace("LOADER", json.dumps(loader.as_uri()))
               .replace("PATHS", json.dumps([str(hook)] if active else []))
               .replace("CWD", json.dumps(str(project))))
    result = subprocess.run([bun, "--eval", program], cwd=project, env=environment,
                            check=True, text=True, capture_output=True, timeout=60)
    prefix = "BOOK_TRANSLATOR_HOOK_PROBE="
    rows = [line[len(prefix):] for line in result.stdout.splitlines() if line.startswith(prefix)]
    if len(rows) != 1:
        raise RuntimeError("Native extension loader returned no unique inspection result: " + result.stderr)
    inspected = json.loads(rows[0])
    assert all((name in inspected["tools"]) == active for name in TOOLS), inspected
    assert all((name in inspected["handlers"]) == active for name in HANDLERS), inspected
    return inspected


def main():
    executable, bun = shutil.which("omp"), shutil.which("bun")
    if not executable or not bun:
        raise SystemExit("omp and bun must be on PATH")
    loader = extension_loader(executable)
    plugin = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="book-translator-install-") as temporary:
        for container in (".agents", ".omp"):
            root = Path(temporary) / container[1:]
            project = root / "project"
            project.mkdir(parents=True)
            home = root / "home"
            home.mkdir()
            agent = root / "agent"
            agent.mkdir()
            copied = project / container / "translator"
            shutil.copytree(plugin, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            hook = copied / "hooks/pre/translator.ts"
            environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(home),
                           "PI_CODING_AGENT_DIR": str(agent), "TERM": "dumb"}
            version = subprocess.run([executable, "--version"], cwd=project, env=environment,
                                     check=True, text=True, capture_output=True, timeout=30).stdout.strip()
            for active in (False, True):
                command = [executable, "--mode", "rpc", "--model", "anthropic/claude-sonnet-4-5",
                           "--no-session", "--no-title", "--no-lsp", "--no-extensions"]
                if active:
                    command += ["--plugin-dir", str(copied), "-e", str(hook)]
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
                assert catalog.get("success") is True, catalog
                assert state.get("success") is True, state
                found = [row for row in catalog["data"]["commands"]
                         if row["name"] == "skill:book-translator"]
                assert len(found) == int(active), (active, found)
                assert not found or found[0]["source"] == "skill", found
                tools = state["data"]["dumpTools"]
                names = {tool["name"] for tool in tools}
                assert all((name in names) == active for name in TOOLS), (active, names)
                task = next(tool for tool in tools if tool["name"] == "task")
                native_agents = [name for name in AGENTS if name in task["description"]]
                assert len(native_agents) == len(AGENTS) * int(active), (active, native_agents)
                assert state["data"]["messageCount"] == 0, state
                assert state["data"]["isStreaming"] is False, state
                inspected = inspect_hook(bun, loader, project, hook, environment, active)
                print(json.dumps({"check": "copied-native-workflow-activation", "container": container,
                                  "active": active, "version": version, "commands": found,
                                  "native_agents": native_agents,
                                  "native_tools": [name for name in TOOLS if name in names],
                                  "hook_handlers": [name for name in HANDLERS if name in inspected["handlers"]],
                                  "model_prompts": 0, "forwarded_credentials": 0}))


if __name__ == "__main__":
    main()
