# OMP contract and model boundary

## Provenance

[SOURCE] Baseline: can1357/oh-my-pi commit `eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac`, coding-agent package 18.11.3. [OBSERVED] Installed `omp --version` reported `omp/18.10.3`. These are separate versions; runtime evidence is recorded in verification.md. No causal claim about AI-development effectiveness follows from source inspection or registration.

## Explicit portable activation

[SOURCE] The Agent Plugins 1.0.0 layout uses root plugin.json and immediate skills/<name>/SKILL.md directories: [manifest and scanner](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/discovery/agent-plugins.ts#L1-L103). [SOURCE] `--plugin-dir` registers launch-local roots: [flag](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/cli/flag-tables.ts#L234-L239), [initialization](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/main.ts#L1816-L1819). Copying translator/ under an arbitrary .agents/ or .omp/ child directory does not register it. Launch from the target project:

```sh
omp --plugin-dir .agents/translator
# Or the other supported copy location:
omp --plugin-dir .omp/translator
```

Then use the interactive `/skill:book-translator` command with the actual task, or explicitly read the registered skill body in that session. [SOURCE] Interactive command expansion is [dedicated](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/modes/skill-command.ts#L52-L73); positional startup messages use a [different path](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/main.ts#L796-L813). Do not claim positional `/skill:` expansion was exercised. `--skills` filters discovered names; it is not a path loader. Utility `skill list/read` dispatch is not launch-time plugin-registration proof. The supplied verify_install.py uses actual RPC get_available_commands with positive and negative copy controls, without submitting an inference prompt.

## Why stages are not model-declaring skills

[SOURCE] Standard skill frontmatter does not accept a model key: [validation](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/discovery/agent-plugin-format.ts#L89-L157). OMP native task agents are a different mechanism; normal model-facing task input does not expose a model field: [schema](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/task/types.ts#L48-L121). This package supplies stage instructions, not misleading portable agent definitions or a system-prompt fork.

[SOURCE] Task resolution can override agent choices and use a parent/default model: [selection](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/config/model-resolver.ts#L1277-L1327), [authentication fallback](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/config/model-resolver.ts#L1692-L1762), [retry chain](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/task/executor.ts#L253-L341). Consequently a non-OpenAI frontmatter selector under an OpenAI parent is insufficient for this workflow.

## Launcher trust boundary

[INFERENCE] Terminology and translation use fresh independent OMP sessions with explicit provider/model admission. core.admit_model allows only direct anthropic/claude-* and google/gemini-* selectors, deliberately excluding unknown providers, aliases, aggregators, auto and OpenAI/GPT/Codex identities. This is a conservative supported subset, not a claim that every other provider is OpenAI. The launcher checks the exact resolved model before the first prompt, pins auxiliary roles, disables prewalk/extensions and uses a temporary isolated HOME, agent directory and working directory. It forwards only the selected direct provider credential, not the caller's auth store, proxy/base-URL overrides or global configuration. No global settings edit is required. Unsupported executed versions fail closed until their contract is exercised and maintained.

[SOURCE] Runtime config overlays merge with lower layers; an empty fallbackChains object is not proof of clearing existing chains: [overlay loading](https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/config/settings.ts#L2487-L2528). Isolation avoids borrowing lower-layer credentials and model routing. The built-in tools retained by the launcher support reading/writing artifacts and researching terminology; task delegation is not enabled. Stage instructions forbid model switching or calling a different model through shell/network tools.

The launcher is configuration and resolved-identity enforcement, not a hostile-agent sandbox or independent network attestation. An agent with shell/network access could bypass an instruction; a compromised executable or endpoint could misreport identity. Genuine request-level enforcement requires a separately trusted SDK/egress adapter admitting endpoint/model pairs. This package does not silently install such an extension or claim it exists. Source sealing and review receipts likewise detect stale/accidental changes, not a malicious writer with access to all artifacts. Preserve the coordinator's dynamic defaults; do not copy its rendered system prompt or complete tool inventory into this skill.
