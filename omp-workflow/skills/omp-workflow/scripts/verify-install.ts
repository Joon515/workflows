#!/usr/bin/env bun
/**
 * Exercise the actual omp launch runtime after copying this entire plugin into
 * each supported destination. No prompt is submitted and no credentials are
 * forwarded. This proves command registration, not instruction following.
 */
import assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const executable = Bun.which("omp");
if (!executable) throw new Error("omp must be available on PATH");
const pluginRoot = await realpath(resolve(import.meta.dir, "../../.."));
const fixture = await mkdtemp(join(tmpdir(), "omp-workflow-install-"));
const model = process.env.OMP_WORKFLOW_SMOKE_MODEL || "openai/gpt-5.2";
const timeoutMs = 45_000;

type RpcResponse = {
  id?: string;
  success?: boolean;
  data?: {
    commands?: { name: string; source: string }[];
    messageCount?: number;
    isStreaming?: boolean;
  };
  error?: unknown;
};

async function run(
  args: string[],
  cwd: string,
  env: Record<string, string>,
  input = "",
): Promise<string> {
  const child = Bun.spawn([executable!, ...args], {
    cwd,
    env,
    stdin: "pipe",
    stdout: "pipe",
    stderr: "pipe",
  });
  let timedOut = false;
  const deadline = setTimeout(() => {
    timedOut = true;
    child.kill("SIGKILL");
  }, timeoutMs);
  try {
    child.stdin.write(input);
    child.stdin.end();
    const [exitCode, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ]);
    assert(!timedOut, `omp exceeded ${timeoutMs}ms: ${args.join(" ")}`);
    assert.equal(exitCode, 0, `omp failed: ${stderr.trim() || stdout.trim()}`);
    return stdout;
  } finally {
    clearTimeout(deadline);
    if (child.exitCode === null) {
      child.kill("SIGKILL");
      await child.exited;
    }
  }
}

try {
  for (const destination of [".agents", ".omp"]) {
    const project = join(fixture, destination.slice(1), "project");
    const home = join(fixture, destination.slice(1), "home");
    const agentDir = join(fixture, destination.slice(1), "agent");
    await Promise.all([project, home, agentDir].map(path => mkdir(path, { recursive: true })));
    const copy = join(project, destination, "omp-workflow");
    await cp(pluginRoot, copy, { recursive: true, force: false, errorOnExist: true });
    const env = {
      PATH: process.env.PATH || "",
      HOME: home,
      PI_CODING_AGENT_DIR: agentDir,
      TERM: "dumb",
    };
    const version = (await run(["--version"], project, env)).trim();
    for (const activated of [false, true]) {
      const args = [
        "--mode", "rpc", "--model", model,
        "--no-session", "--no-lsp", "--no-extensions", "--no-title",
        ...(activated ? ["--plugin-dir", copy] : []),
      ];
      const input = [
        { id: "commands", type: "get_available_commands" },
        { id: "state", type: "get_state" },
      ].map(command => JSON.stringify(command)).join("\n") + "\n";
      const output = await run(args, project, env, input);
      const responses = output.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line) as RpcResponse);
      const commands = responses.find(response => response.id === "commands");
      const state = responses.find(response => response.id === "state");
      assert.equal(commands?.success, true, JSON.stringify(commands));
      assert.equal(state?.success, true, JSON.stringify(state));
      assert(Array.isArray(commands.data?.commands), "Missing RPC command catalog");
      const matches = commands.data.commands.filter(command => command.name === "skill:omp-workflow");
      assert.equal(matches.length, activated ? 1 : 0, "Unexpected plugin activation or skill collision");
      if (activated) assert.equal(matches[0].source, "skill");
      assert.equal(state.data?.messageCount, 0, "Inspection must not submit a model prompt");
      assert.equal(state.data?.isStreaming, false, "Inspection must remain idle");
      console.log(JSON.stringify({
        check: "copied-plugin-registration",
        status: "PASS",
        destination,
        activated,
        version,
        model,
        skillCommands: matches,
        messageCount: state.data.messageCount,
      }));
    }
  }
} finally {
  await rm(fixture, { recursive: true, force: true });
}
