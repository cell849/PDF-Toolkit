# AI Development Instructions — Local PDF Toolkit

These are project-level instructions for AI coding assistants operating on this repository. They are designed to control scope, token/credit consumption, and code quality. Follow higher-priority system and user instructions if they differ.

## Project context

- Windows-first personal desktop converter, fully offline at runtime.
- Initial implementation: Python + PySide6, PyMuPDF, Pillow, pytest.
- Conversion capabilities are registered adapters with a shared contract.
- The authoritative scope and milestones are `PROJECT_PLAN.md` and `FEATURES.md`.
- Correctness, user data safety, conversion fidelity, and maintainability take precedence over adding features.

## Model routing: smallest capable model first

| Class | Examples | Preferred model / effort |
| --- | --- | --- |
| S — Trivial | Rename, one-file UI text, clear typo, small config, narrow mechanical test | GPT-6 Luna, low or medium |
| M — Standard | Bounded feature, new converter adapter, UI integration, ordinary debugging | GPT-6.1 Sol, medium |
| L — Complex | Cross-component refactor, performance/concurrency redesign, difficult failure analysis | GPT-6.1 Sol, high or extra-high |
| X — Exceptional | Architectural ambiguity with major consequences, critical security decisions, repeated failure with Sol | GPT-6 Astra, only with a stated reason and user approval |

### Model use rules

1. Default to Sol for substantive project work; use Luna for small, clearly scoped work.
2. Do not use Astra merely because the project is important, the context is long, or there are many files.
3. Before proposing an escalation, attempt a bounded diagnosis and appropriate tests. Escalate when the problem exceeds the current model's demonstrated capability or the risk/uncertainty is genuinely high.
4. State the reason, expected benefit, and cheaper alternative when requesting Astra.
5. A project instruction does **not** guarantee that a running main agent can switch its own model. If the environment does not support routing, recommend the model to the user before a new task. Never claim a model switch occurred unless confirmed.
6. Where an orchestrator or explicit subagent configuration supports model selection, prefer Luna for small independent scans and Sol for demanding delegated work. Respect available models and permissions.
7. Favor successful completion with measured quality over minimizing tokens at the expense of rework.

## Subagent delegation

- **Default: one agent.** No delegation for S tasks or a sequential chain of dependent steps.
- Delegate only when at least two substantial, independent workstreams can proceed concurrently and the expected time/quality gain plausibly exceeds coordination/token overhead.
- Start with at most two subagents, unless the user approves more.
- Give each agent a bounded task, specific files/modules, clear deliverable, and verification requirements.
- Never allow two agents to edit the same file concurrently. The main agent owns shared interfaces and integration.
- For examples: one independent agent may investigate PDF renderer options while another reviews benchmark criteria; don't split a tiny button fix into three agents.
- The main agent must inspect, integrate, and test delegated results. Subagent reports do not equal completed implementation.
- If delegation tools are unavailable or not authorized, continue with one agent; do not simulate parallel agents through redundant calls.

## Planning and execution

- S tasks: act directly, with no formal plan unless dependencies are unclear.
- M tasks: state a compact plan only when useful, then implement and verify.
- L/X tasks: propose boundaries, failure modes, and a reviewable plan before changing architecture.
- Only work on the approved milestone and explicit user request. Suggest extra features separately.
- Inspect relevant existing code before editing, keep changes small, and preserve unrelated user edits.
- Prefer established native libraries over handwritten PDF/image codecs.
- Do not perform unrelated rewrites, dependency upgrades, or cosmetic churn.

## Implementation quality

- Never modify originals; use temp output files and safe collision behavior.
- Verify file type and parser acceptance; do not trust extension alone.
- Keep heavy conversion work off the UI thread and bound concurrency/memory.
- Avoid shell interpolation; invoke CLI binaries with argument arrays.
- Treat documents as untrusted and give clear failures for unsupported, corrupt, or encrypted files.
- No network calls, telemetry, cloud processing, or AI at application runtime unless a future user decision explicitly changes that requirement.
- Add meaningful tests for feature behavior and important errors. Don't write redundant tests just to inflate coverage.
- Benchmark before claiming performance improvements. Record inputs, runtime, memory, and environment.
- Verify packaging/licensing before sharing binaries with others.

## Completion format

For completed coding tasks, report concisely:

1. What changed and why.
2. Test/benchmark commands run and their result.
3. Known limitations or failures.
4. Any needed user decision.

Do not claim to have run tests, used a model, delegated work, or verified behavior unless that actually happened.

## Feature decision policy

- `FEATURES.md` is the backlog. The assistant may propose a feature, estimate its complexity, or ask for prioritization.
- Do not automatically implement backlog items outside the currently approved milestone.
- Every feature requires a user-visible use case, converter capability definition, acceptance criteria, and tests proportional to risk.
- Prefer a complete PDF-to-JPEG vertical slice over many partially implemented conversion formats.
