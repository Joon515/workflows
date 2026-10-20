import { createHash, randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { isAuthenticated, kNoAuth } from "@oh-my-pi/pi-coding-agent/config/model-registry";
import { SettingsManager } from "@oh-my-pi/pi-coding-agent/extensibility/legacy-pi-coding-agent-shim";
import { cfgRetryFallbackChains, cfgRetryModelFallback, cfgRetryUsageAwareFallback } from "@oh-my-pi/pi-coding-agent/session/settings";

const ROLES = ["source", "terminology", "translation", "review"] as const;
type Role = (typeof ROLES)[number];
type RecordValue = Record<string, unknown>;
interface ModelIdentity { provider: string; id: string; api: string; baseUrl: string }
interface PreparedRequest {
	request_path: string;
	request_id: string;
	request_sha256: string;
	job_path: string;
	role: Role;
	agent: string;
	provider: string;
	model: string;
	selector: string;
	prompt: string;
}
interface Run {
	request: PreparedRequest;
	parentSession: string;
	parentAgent: string;
	runtimeVersion: string;
	expectedModel: ModelIdentity;
	route: string;
	marker: string;
	tracePath: string;
	evidencePath: string;
	queue: Promise<void>;
	spawned: boolean;
	childId?: string;
	childSession?: string;
	observedChildId?: string;
	toolCallId?: string;
	toolIsError?: boolean;
	startupModel?: ModelIdentity;
	finalModel?: ModelIdentity;
	providerRequests: ModelIdentity[];
	assistantMessages: RecordValue[];
	lifecycle: RecordValue[];
	progress?: RecordValue;
	taskResult?: RecordValue;
	failure?: string;
	captureError?: string;
	finished?: boolean;
}

// Factories are rebound to children. Only opaque request IDs cross factory boundaries;
// each parent keeps its own active binding, never a process-wide "Main" binding.
const runs = new Map<string, Run>();
const controller = fileURLToPath(new URL("../../skills/book-translator/scripts/translator.py", import.meta.url));
const sha256 = (bytes: string | Uint8Array): string => createHash("sha256").update(bytes).digest("hex");
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error);
const object = (value: unknown): value is RecordValue => value !== null && typeof value === "object" && !Array.isArray(value);
const roleForAgent = (agent: string): Role | undefined => ROLES.find(role => agent === `book-${role}`);
const modelIdentity = (model: unknown): ModelIdentity => {
	if (!object(model) || !["provider", "id", "api", "baseUrl"].every(key => typeof model[key] === "string" && model[key] !== "")) {
		throw new Error("The native model must expose provider, id, api and baseUrl.");
	}
	return { provider: model.provider as string, id: model.id as string, api: model.api as string, baseUrl: model.baseUrl as string };
};
const sameModel = (left: ModelIdentity, right: ModelIdentity): boolean =>
	left.provider === right.provider && left.id === right.id && left.api === right.api && left.baseUrl === right.baseUrl;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

function enqueue(run: Run, action: () => Promise<void>): void {
	run.queue = run.queue.then(action);
	void run.queue.catch(error => { run.captureError = errorText(error); });
}
function record(run: Run, type: string, data: unknown): void {
	const line = JSON.stringify({ type, timestamp: Date.now(), data }) + "\n";
	enqueue(run, () => fs.appendFile(run.tracePath, line, "utf8"));
}
function childRun(ctx: ExtensionContext): Run | undefined {
	const session = ctx.sessionManager.getSessionId();
	for (const run of runs.values()) {
		if (run.childId === ctx.agent.id && run.childSession === session && !run.finished) return run;
	}
	return undefined;
}
function snapshot(run: Run): RecordValue {
	return {
		version: 1, kind: "native-role-evidence",
		request_id: run.request.request_id, request_sha256: run.request.request_sha256,
		job_path: run.request.job_path, role: run.request.role, agent: run.request.agent,
		child_id: run.childId, runtime_version: run.runtimeVersion,
		parent_session_id: run.parentSession, parent_agent_id: run.parentAgent, child_session_id: run.childSession,
		selected_model: { provider: run.request.provider, id: run.request.model },
		startup_model: run.startupModel, final_model: run.finalModel,
		provider_requests: run.providerRequests, assistant_messages: run.assistantMessages,
		lifecycle: run.lifecycle, progress: run.progress, task_result: run.taskResult,
		task_tool: { tool_call_id: run.toolCallId, is_error: run.toolIsError },
		route: run.route, failure: run.failure,
		trace: path.relative(run.request.job_path, run.tracePath).split(path.sep).join("/"),
	};
}
function persistEvidence(run: Run): void {
	const evidence = clone(snapshot(run));
	enqueue(run, async () => {
		evidence.trace_sha256 = sha256(await fs.readFile(run.tracePath));
		const temporary = `${run.evidencePath}.writing-${randomUUID()}`;
		try {
			await fs.writeFile(temporary, JSON.stringify(evidence, null, 2) + "\n", { encoding: "utf8", flag: "wx" });
			await fs.rename(temporary, run.evidencePath);
		} finally {
			await fs.rm(temporary, { force: true });
		}
	});
}
async function verifyRequest(request: PreparedRequest): Promise<void> {
	if (!ROLES.includes(request.role) || request.agent !== `book-${request.role}` ||
		!/^[-a-zA-Z0-9_]+$/.test(request.request_id) || !request.prompt ||
		request.selector !== `${request.provider}/${request.model}`) {
		throw new Error("The controller returned an invalid native request.");
	}
	const job = await fs.realpath(request.job_path);
	const provenance = await fs.realpath(path.join(job, "provenance"));
	const requestFile = await fs.realpath(request.request_path);
	const relative = path.relative(provenance, requestFile);
	if (job !== request.job_path || provenance !== path.join(job, "provenance") || requestFile !== request.request_path || !relative || relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error("The immutable request must be contained in the real job provenance directory.");
	}
	const bytes = await fs.readFile(requestFile);
	if (sha256(bytes) !== request.request_sha256) throw new Error("The immutable native request hash changed.");
	const saved = JSON.parse(bytes.toString("utf8"));
	for (const key of ["request_id", "job_path", "role", "agent", "provider", "model", "selector", "prompt"] as const) {
		if (saved[key] !== request[key]) throw new Error(`Native request mismatch: ${key}`);
	}
}

export default function translatorExtension(pi: ExtensionAPI): void {
	let prepared: Run | undefined;
	const ownedRuns = new Map<string, Run>();
	const Type = pi.typebox.Type;
	const toolFailure = (error: unknown) => ({ content: [{ type: "text" as const, text: errorText(error) }], isError: true });
	const runPython = async (args: string[], signal?: AbortSignal): Promise<unknown> => {
		const result = await pi.exec("python3", [controller, ...args], { signal });
		if (result.code !== 0 || result.killed) throw new Error(result.stderr.trim() || result.stdout.trim() || `Controller exited with ${result.code}.`);
		return JSON.parse(result.stdout);
	};
	const availableModel = (ctx: ExtensionContext, request: PreparedRequest) => {
		const model = ctx.models.list().find(candidate => candidate.provider === request.provider && candidate.id === request.model);
		if (!model) throw new Error(`The explicitly selected model ${request.selector} is unavailable in this session's native registry.`);
		return model;
	};

	pi.registerTool({
		name: "book_translator_prepare", label: "Prepare book role", approval: "exec", loadMode: "essential",
		description: "Prepare one explicitly selected book role. Use the returned agent and assignment in one blocking native task, then call book_translator_finish. This does not run a model.",
		parameters: Type.Object({ job: Type.String(), role: Type.Union(ROLES.map(role => Type.Literal(role))), revise: Type.Optional(Type.Boolean()) }),
		async execute(_id, params, signal, _update, ctx) {
			try {
				if (roleForAgent(ctx.agent.name)) throw new Error("Book workers cannot prepare or delegate book roles.");
				if (prepared?.spawned && !prepared.taskResult && !prepared.failure) throw new Error("The prepared book worker has not settled.");
				const request = await runPython(["prepare-native", path.resolve(ctx.cwd, params.job), params.role, ...(params.revise ? ["--revise"] : [])], signal) as PreparedRequest;
				await verifyRequest(request);
				const selected = availableModel(ctx, request);
				const expectedModel = modelIdentity(selected);
				const settings = SettingsManager.create(ctx.cwd);
				settings.overrideModelRoles({ [`book_${request.role}`]: request.selector });
				const chains = { ...cfgRetryFallbackChains.get(settings) };
				for (const role of ROLES) chains[`book_${role}`] = [];
				cfgRetryFallbackChains.override(settings, chains);
				const run: Run = {
					request, parentSession: ctx.sessionManager.getSessionId(), parentAgent: ctx.agent.id,
					runtimeVersion: String(pi.pi.VERSION).replace(/^omp\//, ""), expectedModel,
					route: JSON.stringify({ version: 1, kind: "book-translator-route", request_id: request.request_id,
						request_sha256: request.request_sha256, role: request.role, agent: request.agent, ...expectedModel }),
					marker: `[[book-translator-run:${request.request_id}]]`,
					tracePath: path.join(request.job_path, "provenance", `native-${request.request_id}.events.jsonl`),
					evidencePath: path.join(request.job_path, "provenance", `native-${request.request_id}.evidence.json`),
					queue: Promise.resolve(), spawned: false, providerRequests: [], assistantMessages: [], lifecycle: [],
				};
				await fs.writeFile(run.tracePath, "", { encoding: "utf8", flag: "wx" });
				if (prepared && !prepared.spawned) prepared.failure = "Superseded by another explicit prepare operation.";
				prepared = run;
				ownedRuns.set(request.request_id, run);
				runs.set(request.request_id, run);
				record(run, "prepared", { request_path: request.request_path, request_sha256: request.request_sha256, selected_model: expectedModel, parent_session_id: run.parentSession });
				await run.queue;
				const details = { run: request.request_id, agent: request.agent, selector: request.selector,
					assignment: `${run.marker}\nExecute only the admitted book role. The native hook supplies its complete immutable assignment. Do not delegate, change models, or alter controller metadata.`,
					request_path: request.request_path, evidence_path: run.evidencePath };
				return { content: [{ type: "text", text: JSON.stringify(details) }], details };
			} catch (error) { return toolFailure(error); }
		},
	});

	pi.registerTool({
		name: "book_translator_finish", label: "Admit completed book role", approval: "exec", loadMode: "essential",
		description: "Flush native evidence for a settled prepared book task and ask the Python controller to admit its artifacts. Translation may build here. Worker success alone is not stage admission; this does not invoke a model.",
		parameters: Type.Object({ run: Type.String() }),
		async execute(_id, params, signal, _update, ctx) {
			try {
				const run = ownedRuns.get(params.run);
				if (!run || run.parentSession !== ctx.sessionManager.getSessionId()) throw new Error("Unknown book run in this parent session.");
				if (run.finished) throw new Error("This book run was already admitted.");
				await run.queue;
				if (run.captureError || run.failure) throw new Error(run.captureError || run.failure);
				if (!run.taskResult || run.toolIsError || run.taskResult.exitCode !== 0 || run.taskResult.error || run.taskResult.aborted) throw new Error("The native book task has no successful settled result.");
				if (!run.childId || !run.startupModel || !run.finalModel || !sameModel(run.expectedModel, run.startupModel) || !sameModel(run.expectedModel, run.finalModel)) throw new Error("The native book child identity was not proven.");
				if (run.taskResult.resolvedModelRoute !== run.route || run.taskResult.resolvedModelIsFallback === true) throw new Error("The native task's route or fallback evidence does not match the explicit selection.");
				await verifyRequest(run.request);
				persistEvidence(run);
				await run.queue;
				const result = await runPython(["complete-native", run.request.request_path, run.evidencePath], signal);
				run.finished = true;
				if (prepared === run) prepared = undefined;
				runs.delete(run.request.request_id);
				return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
			} catch (error) { return toolFailure(error); }
		},
	});

	pi.on("tool_call", (event, ctx) => {
		if (event.toolName !== "task") return;
		const items = Array.isArray(event.input.tasks) ? event.input.tasks.filter(object) : [event.input];
		const bookItems = items.filter(item => typeof item.agent === "string" && roleForAgent(item.agent));
		if (bookItems.length === 0) return;
		const run = prepared;
		if (bookItems.length !== 1 || !run || run.finished || run.failure || run.spawned || run.parentSession !== ctx.sessionManager.getSessionId()) return { block: true, reason: "Prepare exactly one fresh book role before native task dispatch." };
		const item = bookItems[0];
		if (item.agent !== run.request.agent || typeof item.task !== "string" || !item.task.includes(run.marker) || item.isolated === true || event.input.isolated === true) return { block: true, reason: "The book task must use the prepared agent/run marker in this shared native session, without isolation." };
		run.toolCallId = event.toolCallId;
		record(run, "task_call", { tool_call_id: event.toolCallId, input: event.input });
	});

	pi.on("before_subagent_spawn", async (event, ctx) => {
		if (!roleForAgent(event.agent)) return;
		const run = prepared;
		try {
			if (event.invocationKind !== "task") throw new Error("Book roles require the native task result evidence path; eval agent dispatch is not admitted.");
			if (!run || run.finished || run.failure || run.spawned || !run.toolCallId || event.agent !== run.request.agent || run.parentSession !== ctx.sessionManager.getSessionId()) throw new Error("No fresh prepared request is bound to this book task.");
			await verifyRequest(run.request);
			const selected = availableModel(ctx, run.request);
			if (!sameModel(run.expectedModel, modelIdentity(selected))) throw new Error("The selected native registry identity changed after preparation.");
			// Use the registry's native auth resolver, including its keyless sentinel. Never export credentials.
			const key = await ctx.modelRegistry.getApiKey(selected, ctx.sessionManager.getSessionId());
			if (key !== kNoAuth && !isAuthenticated(key)) throw new Error("The selected native model has no working authentication; parent-model fallback is not admitted.");
			run.spawned = true;
			record(run, "before_subagent_spawn", event);
			return { model: run.request.selector, note: run.route };
		} catch (error) {
			if (run) { run.failure = errorText(error); record(run, "spawn_blocked", { error: run.failure }); }
			return { block: true, reason: errorText(error) };
		}
	});

	pi.on("session_start", (_event, ctx) => {
		if (ctx.agent.kind !== "sub" || !roleForAgent(ctx.agent.name)) return;
		const settings = SettingsManager.create(ctx.cwd);
		cfgRetryModelFallback.override(settings, false);
		cfgRetryUsageAwareFallback.override(settings, false);
	});
	pi.on("before_agent_start", async (event, ctx) => {
		if (ctx.agent.kind !== "sub" || !roleForAgent(ctx.agent.name)) return;
		let run: Run | undefined;
		try {
			const markers = [...event.prompt.matchAll(/\[\[book-translator-run:([-a-zA-Z0-9_]+)\]\]/g)];
			if (markers.length === 0) {
				run = childRun(ctx);
				if (!run || run.failure || !sameModel(run.expectedModel, modelIdentity(ctx.model))) throw new Error("The book child has no admitted assignment for this continuation.");
				return;
			}
			if (markers.length !== 1) throw new Error("The book child requires exactly one prepared run marker; no job context was admitted.");
			run = runs.get(markers[0][1]);
			if (!run || !run.spawned || run.finished || run.failure || run.request.agent !== ctx.agent.name || ctx.agent.parentId !== run.parentAgent ||
				(run.childId !== undefined && (run.childId !== ctx.agent.id || run.childSession !== ctx.sessionManager.getSessionId())) ||
				(run.observedChildId !== undefined && run.observedChildId !== ctx.agent.id)) throw new Error("The actual native child does not match the prepared book request.");
			await verifyRequest(run.request);
			const actual = modelIdentity(ctx.model);
			if (!sameModel(run.expectedModel, actual)) throw new Error("The native child started on a different model/API/endpoint; no job context was admitted.");
			run.childId = ctx.agent.id;
			run.childSession = ctx.sessionManager.getSessionId();
			run.startupModel = actual;
			record(run, "child_admitted", { agent: ctx.agent, session_id: run.childSession, model: actual });
			await run.queue;
			return { message: { customType: "book-translator-assignment", content: run.request.prompt, display: false,
				details: { request_id: run.request.request_id, request_sha256: run.request.request_sha256, child_id: ctx.agent.id } } };
		} catch (error) {
			if (run) { run.failure = errorText(error); record(run, "child_blocked", { error: run.failure, agent: ctx.agent }); }
			ctx.abort();
			return { message: { customType: "book-translator-blocked", content: errorText(error), display: true } };
		}
	});
	pi.on("before_provider_request", (event, ctx) => {
		const run = childRun(ctx);
		if (!run) return;
		try {
			const actual = modelIdentity(ctx.model);
			if (!sameModel(run.expectedModel, actual)) throw new Error("A book provider request changed model/API/endpoint.");
			run.providerRequests.push(actual);
			record(run, "provider_request_identity", actual);
		} catch (error) { run.failure = errorText(error); ctx.abort(); }
		return event.payload;
	});
	pi.on("agent_end", (event, ctx) => {
		const run = childRun(ctx);
		if (!run || event.willContinue || event.awaitingAsyncWork) return;
		try { run.finalModel = modelIdentity(ctx.model); record(run, "child_terminal_model", run.finalModel); }
		catch (error) { run.failure = errorText(error); }
	});

	pi.events.on("task:subagent:lifecycle", data => {
		const run = prepared;
		if (!run || !object(data) || data.parentToolCallId !== run.toolCallId || data.agent !== run.request.agent || typeof data.id !== "string") return;
		if (run.observedChildId && run.observedChildId !== data.id) run.failure = "More than one native child was observed for the prepared book role.";
		run.observedChildId = data.id;
		run.lifecycle.push(clone(data));
		record(run, "lifecycle", data);
	});
	pi.events.on("task:subagent:progress", data => {
		const run = prepared;
		if (!run || !object(data) || !object(data.progress) || data.parentToolCallId !== run.toolCallId || data.agent !== run.request.agent) return;
		run.progress = clone(data.progress);
		if (data.progress.resolvedModelIsFallback === true) run.failure = "Native fallback routing was observed for the book role.";
		record(run, "progress", data);
	});
	pi.events.on("task:subagent:event", data => {
		const run = prepared;
		if (!run || !object(data) || data.id !== (run.childId ?? run.observedChildId) || !object(data.event) || run.taskResult) return;
		const event = data.event;
		if (event.type === "message_end" && object(event.message) && event.message.role === "assistant") run.assistantMessages.push(clone(event.message));
		if (["message_end", "agent_end", "tool_execution_start", "tool_execution_end", "auto_retry_start", "auto_retry_end", "retry_fallback_applied", "retry_fallback_succeeded"].includes(String(event.type))) record(run, "child_event", data);
	});
	pi.on("tool_result", async event => {
		const run = prepared;
		if (!run || event.toolName !== "task" || event.toolCallId !== run.toolCallId) return;
		try {
			const results = object(event.details) && Array.isArray(event.details.results) ? event.details.results.filter(object) : [];
			const matching = results.filter(result => result.id === (run.childId ?? run.observedChildId) && result.agent === run.request.agent);
			if (matching.length !== 1) throw new Error("The prepared book task did not return exactly one matching settled native result.");
			run.taskResult = clone(matching[0]);
			run.toolIsError = event.isError;
			record(run, "settled_task_result", { tool_call_id: event.toolCallId, is_error: event.isError, result: run.taskResult });
			persistEvidence(run);
			await run.queue;
			return { additionalContext: `Book worker ${run.request.request_id} settled; its artifacts are NOT admitted yet. Call book_translator_finish with this run ID before advancing the workflow.` };
		} catch (error) {
			run.failure = errorText(error);
			return { content: [...event.content, { type: "text", text: `Book evidence capture failed: ${run.failure}` }], isError: true };
		}
	});
}
