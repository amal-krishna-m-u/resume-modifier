# Spec 06 — Provider Backends

**Covers:** R14, R15
**Related:** [Runtime](spec-03-runtime-auth.md) · [Agents](spec-02-agent-pipeline.md) · [open-questions.md](open-questions.md) OQ-1, OQ-7

---

## 1. Why this is cheap to support

The pipeline is portable almost by accident. [spec-02 §5](spec-02-agent-pipeline.md) gives agents **no tools**: they receive content as prompt text and return JSON. Nothing uses tool loops, MCP, hooks, sessions, or file access.

That makes the provider contract the simplest one that exists — *string in, JSON out* — so supporting other providers is additive work behind the existing `RunnerBackend` interface ([spec-03 §2](spec-03-runtime-auth.md)), not a redesign.

This matters for distribution. Anthropic's terms permit a tool where *"Each end user must authenticate with their own Anthropic API key, Claude subscription plan credentials, or 3P inference provider credential"* ([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). A provider-agnostic tool where every user brings their own CLI or key is the compliant shape for sharing this; routing other people's requests through one set of credentials is not.

## 2. Measured: coding CLIs carry a harness you don't want

Every agentic coding CLI ships a large system prompt — tool schemas, sandbox rules, patch formats, repo conventions. This pipeline needs none of it but pays for it on every call.

Measured on this machine, 2026-10-06, with the prompt `"Reply with exactly: OK"`:

| Configuration | Input tokens | Note |
|---|---|---|
| `claude -p`, default | **38,841** | full Claude Code harness + user's MCP servers |
| + `--system-prompt`, `--exclude-dynamic-system-prompt-sections`, built-in tools disallowed | 18,436 | residual is MCP server tool schemas |
| + `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources ""` | **8,004** | irreducible Claude Code baseline |
| `codex exec --json`, default | 18,365 | Codex harness; 2,432 cached |
| Agent SDK, `allowed_tools=[]` only | 18,184 | **does not restrict tools** — see below |
| Agent SDK, `+ disallowed_tools=[…]` | **7,753** | matches the CLI floor |

**A stripped CLI call costs ~79% less than a default one.** At five agents per run that is the difference between ~194K and ~40K tokens of pure overhead, before any of your content.

### Reaching the floor

CLI flags, and their Agent SDK equivalents:

| Goal | CLI | `ClaudeAgentOptions` |
|---|---|---|
| Drop the Claude Code system prompt | `--system-prompt "<ours>"` | `system_prompt="<ours>"` |
| Drop dynamic prompt sections | `--exclude-dynamic-system-prompt-sections` | — (implied when not using the preset) |
| Drop MCP servers | `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` | `mcp_servers={}` |
| Drop user/project settings | `--setting-sources ""` | `setting_sources=[]` |
| Drop built-in tools | `--disallowed-tools Bash Read Write …` | `disallowed_tools=[…]` |

**The Agent SDK defaults are already lean.** `system_prompt` defaults to `None`, and Claude Code's prompt is opt-in via `{"type": "preset", "preset": "claude_code"}` — which this project never passes. Two defaults still need overriding:

- `setting_sources=None` loads user, project, and local settings, which drags in the user's MCP servers. **Pass `[]` explicitly.** This is the single largest saving (18.4K → 8.0K above).
- `allowed_tools` does *not* restrict Claude to those tools; unlisted tools fall through to `permission_mode`. Use `disallowed_tools` to actually remove them. **Measured 2026-10-06:** `allowed_tools=[]` alone cost 18,184 input tokens; adding `disallowed_tools` brought it to 7,753. The first probe written for this project had exactly this bug, which is why it is called out rather than left as a footnote.

## 3. Backends

### 3.1 `OpenAICompatRunner` — build this first

One implementation of `POST /v1/chat/completions` covers Ollama (which serves an OpenAI-compatible shape on `localhost:11434`), Groq, Together, LM Studio, vLLM, and OpenAI itself. A different provider is a `base_url` change.

Highest return of any backend: one file, no harness overhead, real schema enforcement where the provider supports it.

### 3.1a `OpenRouterRunner`

OpenRouter is the same protocol with the defaults a full-corpus run needs, so it is a named backend rather than a Settings form the user has to fill in:

- `https://openrouter.ai/api/v1`
- `OPENROUTER_API_KEY`
- 1,000,000-token window
- native JSON schema
- default model `z-ai/glm-5.3-flash`

The lab does not matter. GLM 5.3 Flash (priced 2026-10-09 at $0.15 / $0.50 per 1M tokens; 1M context; structured outputs; Artificial Analysis intelligence 41.8) is the cost/quality pick that clears the Validator bar in §6 without pinning the tool to Anthropic. A five-agent run on the current corpus is a couple of cents.

Same Settings list, same protocol: `qwen/qwen3.8-flash` ($0.15 / $0.47) and `deepseek/deepseek-v4.1-flash` (intelligence 39.5, $0.30 / $1.20). Skip the cheapest DeepSeek Flash SKUs (intelligence ~24): they are fine for drafting and too weak for silent misses in Selector/Validator. `anthropic/claude-haiku-5.5` remains available and is slightly cheaper per token if you want it.

### 3.2 `ClaudeSdkRunner` / `ClaudeCliRunner`

Per [spec-03](spec-03-runtime-auth.md). Subscription auth without an API key; ~8K tokens/call when configured per §2.

### 3.3 `CodexCliRunner`

`codex exec --json --skip-git-repo-check --ephemeral -s read-only -`, with the prompt on **stdin** (a corpus-sized prompt would exceed the per-argument limit on Linux). `--ephemeral` keeps Codex from writing a session file per call — every call carries the whole career record. `--ignore-user-config` is deliberately **not** used: it drops the person's model setting and Codex falls back to a default that ChatGPT accounts cannot use. Emits newline-delimited JSON events; the reply is the `item.completed` event whose `item.type` is `agent_message`, and `turn.completed` carries `usage`.

Failures arrive as `error` / `turn.failed` events (the API's JSON error is a string inside Codex's own `message`), not necessarily as a non-zero exit; the runner reads them, and classifies login problems as an auth error naming `codex login`. `healthcheck` runs `codex login status`. Verified working 2026-10-06: `gpt-5.5`, 272,000-token context, and a strict-JSON prompt returned a bare parseable object with no prose and no code fences.

### 3.4 Not recommended

**Antigravity CLI** — free tier is roughly 20 requests/day, [down from 250 in March 2026](https://antigravity.im/limits). A five-agent run plus chat revisions exhausts a day's quota in a few passes.

**Gemini CLI** — [retired for free, Pro, and Ultra personal accounts on 18 June 2026](https://www.tembo.io/blog/gemini-cli-pricing).

## 4. Capability declaration

Each backend declares its capabilities, and the orchestrator refuses work a backend cannot do correctly:

```python
@dataclass(frozen=True)
class BackendCapabilities:
    min_context_tokens: int      # usable window after harness overhead
    harness_overhead: int        # measured tokens per call
    native_json_schema: bool     # provider-enforced structured output
    prompt_caching: bool
    cost_per_run: str            # "subscription" | "free" | "metered"
```

### The context gate is non-negotiable

Full-corpus selection requires the entire knowledge base in one prompt ([spec-02 §2](spec-02-agent-pipeline.md)). A backend whose window cannot hold `corpus_tokens + harness_overhead + headroom` **must refuse to start**, naming the shortfall.

It must not chunk. Chunked selection silently reintroduces the lossy retrieval that [AC-R11.3](PRD.md) forbids, and the resulting omissions are invisible — the exact failure this product exists to prevent. A loud refusal is correct; graceful degradation here is not graceful.

This is the real constraint on local models: a 7B model with an 8K window cannot run this pipeline on a realistic corpus, regardless of how good it is.

## 5. JSON handling

Providers differ in how reliably they return parseable JSON, so the runner normalizes:

1. Use provider-native schema enforcement when `native_json_schema` is true.
2. Otherwise parse directly; on failure strip code fences and retry the parse.
3. On continued failure, re-prompt once with the parse error included.
4. On second failure, fail the stage loudly — never pass a half-parsed object downstream.

Codex and Claude both returned clean bare JSON in testing; smaller local models are where steps 2–4 earn their place.

## 6. Which agent tolerates a weak model

Not uniform, and the asymmetry matters:

| Agent | Tolerance | Why |
|---|---|---|
| Analyst | Medium | Errors show up as odd requirements, visible on review |
| Selector | Low | Misses are silent — the core failure mode |
| Recall | Low | Its whole job is catching what the Selector missed |
| Writer | Medium | Weak output reads as bland bullets, which is obvious |
| **Validator** | **Lowest** | A weak validator rationalizes unsupported claims as supported |

Selection and writing degrade *visibly*. The Validator degrades *invisibly* — and you find out in an interview. Anyone running this on constrained hardware should point the strongest available model at the Validator, not the cheapest.

## 7. Configuration

```toml
[runtime]
backend = "claude_sdk"          # claude_sdk | claude_cli | codex_cli | openrouter | openai_compat | fake
                                # claude_sdk is the default, per OQ-1

[runtime.openai_compat]
base_url = "http://localhost:11434/v1"
model    = "qwen2.5:14b"

[runtime.backend_models]        # one model per backend; empty = that CLI's own default
claude_sdk  = "opus"
codex_cli   = "gpt-5.5"
openrouter  = "z-ai/glm-5.3-flash"

[runtime.models]
default   = "<backend default>"
validator = "<strongest available>"   # see §6
```

The Settings screen reads and writes this file (`GET/PUT /api/settings`, `POST /api/settings/test`); `RUNNER_BACKEND` overrides it for one process. Backend selection never touches agent or pipeline code (AC-R15.1). An auth failure names the backend and the credential it expected (AC-R15.3).
