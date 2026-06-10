<div align="center">

# A2A Contract

**English** · [简体中文](README.zh-CN.md)

**One shared contract for a support agent and a data agent.**

Business questions → Controlled queries → Streaming progress → Verifiable results


[![Contract](https://img.shields.io/badge/Contract-v1.12-0891b2?style=flat-square)](a2a-streaming-contract.md) [![Transport](https://img.shields.io/badge/Transport-JSON--RPC_2.0_%2B_SSE-475569?style=flat-square)](#how-the-projects-work-together) [![Schema](https://img.shields.io/badge/Schema-JSON_Schema_2020--12-7c3aed?style=flat-square)](schema/)

[Interaction](#how-the-projects-work-together) · [Tech stack](#tech-stack-and-responsibilities) · [Design](#key-design-decisions) · [Integration](#quick-start) · [Validation](#validation-and-current-limits)

</div>

When a customer asks “Where is my order?”, the support agent must decide when to query business data, show progress while waiting, and determine whether the result supports an answer. This repository defines that service boundary: **how requests are sent, how events are consumed, how results are trusted, and how both sides upgrade together**.

| Repository | Role | Core capabilities |
| --- | --- | --- |
| [AI Helpdesk](https://github.com/heyemlee/ai-helpdesk) | Support orchestration · A2A client | Intent recognition, hybrid retrieval, specialist routing, answer guards and human tickets |
| [AI SQL Agent](https://github.com/heyemlee/ai-sql-agent) | Data queries · A2A server | Schema retrieval, cross-database planning, SQL generation, authorization, read-only execution and result checks |
| **A2A Contract** | Shared interface contract | Protocol documentation, JSON Schema, golden fixtures and consumer test requirements |

The applications run independently. Both test suites reference this repository as a versioned dependency; no separate “contract service” needs to be deployed.

## How the projects work together

![A2A request sequence between AI Helpdesk and AI SQL Agent](docs/diagrams/a2a-sequence.en.svg)

[Interactive HTML](docs/diagrams/a2a-sequence.en.html) · [Editable JSON](docs/diagrams/a2a-sequence.en.archify.json) · [Integration details and source evidence — Chinese](docs/a2a-integration.md)

Generated with [Archify](https://github.com/tt-a1i/archify). GitHub displays the SVG directly. Download and open the HTML in a browser to zoom, inspect nodes, switch themes and export.

**The diagram shows a successful request with A2A streaming enabled. Helpdesk still defaults to `POST /query`; switching the transport is explicit.** A query may involve multiple databases and progress events, condensed here into one logical interaction.

1. **Recognize and delegate.** Helpdesk determines whether the question needs business data and delegates through the `order_data_query` tool. Knowledge questions can use the knowledge base directly.
2. **Discover capabilities.** The client reads `/.well-known/agent.json` and selects `message/stream` or `message/send` based on `capabilities.streaming`.
3. **Execute with controls.** SQL Agent retrieves the business schema, plans the query, generates SQL and executes it under authorization and read-only constraints. Helpdesk forwards query stages to the console as SSE `progress` events.
4. **Verify and answer.** After receiving both the artifact and a `completed + final:true` terminal event, the client evaluates execution status, risk and degradation fields. Helpdesk uses that evidence to answer, fall back or hand off to a human.

| Transport | Purpose | Response |
| --- | --- | --- |
| `POST /query` | Current default, direct request | JSON response with the same result trust semantics |
| `POST /a2a` · `message/send` | A2A path when streaming is unavailable | JSON-RPC Task containing a result artifact |
| `POST /a2a` · `message/stream` | Visible query progress | JSON-RPC over SSE: task, progress, artifact, then terminal event |

## Tech stack and responsibilities

| Layer | Technology | Role in the system |
| --- | --- | --- |
| Support console | React 18 · TypeScript 5 · Vite 6 · Tailwind CSS 4 · TanStack Query 5 | Conversations, progress, tickets and operational views; POST SSE consumed through `fetch` |
| Services and orchestration | Python · FastAPI · Pydantic 2 · asyncio | Typed requests, async I/O and support specialist orchestration; SQL Agent has its own query pipeline |
| Support knowledge retrieval | PostgreSQL + pgvector · tsvector · RRF · reranking | Fuse semantic and exact-term retrieval, then assess ranking and evidence sufficiency |
| Query reasoning | YAML business semantics · BM25 + vector retrieval · SchemaGraph | Narrow the schema context, represent table relationships and plan cross-database steps with intermediate results |
| Query execution and controls | SQLGlot AST · MCP execution layer · SQLite / PostgreSQL | Table/column authorization, SQL validation, read-only execution, timeouts, row caps and repair |
| Model integration | Anthropic / OpenAI-compatible protocols · HTTPX | Intent recognition, answers and SQL generation; the model protocol is not an authorization boundary |
| State and observability | Redis · SQLite / PostgreSQL · OpenTelemetry · Prometheus · Grafana / Tempo / Loki | Helpdesk manages transient state and the monitoring stack; both services record queries, steps and correlation identifiers |
| Cross-service protocol | HTTP · JSON-RPC 2.0 · SSE · JSON Schema | Separate requests, events, result structure and business trust across transports |
| Contract validation | Python · jsonschema · referencing · pytest | Shared fixtures cover valid, invalid and structurally valid but untrustworthy payloads |

Exact versions live in the application manifests: [Helpdesk backend](https://github.com/heyemlee/ai-helpdesk/blob/main/backend/requirements.txt), [frontend](https://github.com/heyemlee/ai-helpdesk/blob/main/frontend/package.json), and [SQL Agent](https://github.com/heyemlee/ai-sql-agent/blob/main/pyproject.toml). This table describes the whole system; this contract repository only needs Python, `jsonschema` and `referencing` for its self-check.

## Key design decisions

| Design | Rule | Problem addressed |
| --- | --- | --- |
| **Separate protocol completion from business success** | An artifact alone is insufficient; a completed terminal event is also required. Business logic then evaluates `execution_status` | Interrupted streams, partial results and failed queries must not become complete answers |
| **Conservative trust assessment** | Missing or mistyped `has_risk` / `degraded` fields are untrusted; the string `"false"` is not accepted as a boolean | Loose coercion must not turn malformed data into trusted facts |
| **Shared semantics across three transports** | Normalized results from `stream`, `send` and `/query` use the same trust rules | Changing transport must not silently change the evidence standard |
| **Bounded fallback** | Unsupported streaming or pre-stream `-32004` can fall back to `send`; failures after the stream opens are not replayed | Avoid duplicate execution, quota charges and accumulated waiting time |
| **Layered timeouts** | Streaming defaults to 20 seconds of silence and a 90-second hard cap; configure the outer tool budget accordingly | Distinguish a slow query making progress from a stalled call |
| **Verifiable evolution** | Pin a tag or commit, share schemas and fixtures, and update both consumers when the contract changes | Prevent one service from interpreting new results through an old contract |

`execution_status` distinguishes `success`, `partial_success`, `no_data`, `failed` and `not_applicable`. A successful query with no records needs a different answer from a query that never succeeded. Truncated results cannot support claims about totals or complete aggregates. See the [authoritative contract — Chinese](a2a-streaming-contract.md) for the full rules.

## Quick start

### 1. Pin the contract

From an application repository root:

```bash
git clone --depth 1 --branch v1.13 https://github.com/heyemlee/a2a-contract.git .contract
export A2A_CONTRACT_DIR="$PWD/.contract"
export A2A_CONTRACT_REQUIRED=1
```

Both consumers read the same `schema/` and `fixtures/index.json`. Do not copy them into the application repositories or depend on a moving `main`. If `.contract` already exists, follow the [upgrade procedure — Chinese](docs/maintenance.md#升版本的时候).

### 2. Enable A2A collaboration

Example Helpdesk backend environment when both services run locally:

```dotenv
SQL_AGENT_URL=http://127.0.0.1:8000
SQL_AGENT_TRANSPORT=a2a
SQL_AGENT_TIMEOUT_S=90
SQL_AGENT_A2A_SEND_TIMEOUT_S=45
SQL_AGENT_A2A_SILENCE_S=20
SQL_AGENT_A2A_HARD_S=90
```

Set `AI_SQL_A2A_STREAMING=true` in SQL Agent. If API key authentication is enabled, configure the matching `SQL_AGENT_API_KEY` in Helpdesk. Start each application using its own README. Container deployments need a service address reachable from the calling container.

Here, `SQL_AGENT_TIMEOUT_S=90` gives the outer tool a 92-second budget, covering the 90-second streaming cap while keeping `send` at 45 seconds. Changing only the transport leaves the default 47-second outer budget in place and can cut streaming requests short. See the [timeout and integration guide — Chinese](docs/a2a-integration.md).

## Validation and current limits

Run in this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install jsonschema referencing
.venv/bin/python tools/check_contract.py
```

The self-check covers **schemas, fixtures, links and version consistency**. Both applications must also implement the [six consumer test groups, A–F — Chinese](CONSUMER-TESTS.md). Negative cases must check both schema rejection and whether the caller falls back toward an untrusted verdict.

- **Validation status.** Historical acceptance relies on local checks and verifiable commits. On 2026-06-03, this repository still had zero GitHub Actions runs; an existing workflow is not evidence of an enforced CI gate. Historical account restrictions and the local fallback process are documented in the [maintenance guide — Chinese](docs/maintenance.md#自检).
- **Identity boundary.** Helpdesk isolates user memory and downstream sessions, but queries business data under a shared service identity by default. Data visibility follows the service key's policy, not end-user business-data isolation. See the [Helpdesk identity integration requirements — Chinese](https://github.com/heyemlee/ai-helpdesk/blob/main/docs/integrations/sql-agent-identity-requirements.md).
- **Accuracy boundary.** A correct protocol does not guarantee correct SQL semantics. SQL Agent's 2026-05-06 evaluation still missed the cross-database accuracy and silent-error release gates; see the [measurement record](https://github.com/heyemlee/ai-sql-agent/blob/main/benchmark/baseline/2026-09-09/README.md).

## Documentation

The detailed contract and operational guides currently remain in Chinese. The English and Chinese READMEs reference the same authoritative documents, schemas and fixtures.

| Entry | Contents |
| --- | --- |
| [Authoritative contract](a2a-streaming-contract.md) | Effective status, event structures, result semantics, failures and bilateral changes |
| [A2A integration guide](docs/a2a-integration.md) | Transport paths, timeout budgets, identity boundaries and source links pinned to commits |
| [Consumer tests](CONSUMER-TESTS.md) | Six required test groups for both applications |
| [Schemas](schema/) · [Fixture index](fixtures/index.json) | Executable structural constraints and shared samples |
| [Maintenance and releases](docs/maintenance.md) | Stable paths, upgrade order, version history and incident lessons |
| [Diagram provenance](docs/diagrams/README.md) | Archify version, generation commands and validation records |

## Current version

| Tag | Change |
| --- | --- |
| `v1.13` | The server stops at the next checkpoint once a caller disconnects; adds the `canceled` terminal state with a terminal-event schema and fixtures; rate limits answer 429 with JSON-RPC `-32029` instead of `-32001`. The caller changes no code, only its pins and tests |

See the [version history — Chinese](docs/maintenance.md#版本). README and diagram updates do not change the contract version, schemas, fixtures or stable paths used by consumers.
