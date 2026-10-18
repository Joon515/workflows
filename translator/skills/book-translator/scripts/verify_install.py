#!/usr/bin/env python3
"""Exercise copied plugin registration without sending a model prompt."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    executable = shutil.which("omp")
    if not executable:
        raise SystemExit("omp must be on PATH")
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
            environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(home),
                           "PI_CODING_AGENT_DIR": str(agent), "TERM": "dumb"}
            version = subprocess.run([executable, "--version"], cwd=project, env=environment,
                                     check=True, text=True, capture_output=True, timeout=30).stdout.strip()
            for active in (False, True):
                command = [executable, "--mode", "rpc", "--model", "anthropic/claude-sonnet-4-5",
                           "--no-session", "--no-title", "--no-lsp", "--no-extensions"]
                if active:
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
                assert catalog.get("success") is True, catalog
                assert state.get("success") is True, state
                found = [row for row in catalog["data"]["commands"]
                         if row["name"] == "skill:book-translator"]
                assert len(found) == int(active), (active, found)
                assert not found or found[0]["source"] == "skill", found
                assert state["data"]["messageCount"] == 0, state
                assert state["data"]["isStreaming"] is False, state
                print(json.dumps({"check": "copied-plugin-registration", "container": container,
                                  "active": active, "version": version, "commands": found,
                                  "model_prompts": 0}))


if __name__ == "__main__":
    main()
