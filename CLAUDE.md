# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is the **Day06 project scaffold** for a Chinese-language LangChain/LangGraph course (Week 15: 多 Agent、Agent Skills 与 MCP). The repo root **is** the `day06_multi_agent/` project described in the courseware — the doc's `day06_multi_agent/knowledge/` maps to `knowledge/` here.

**Status: mostly unimplemented.** The data, knowledge files and courseware are in place; the Python application is not.

| Present | Missing (must be built) |
| --- | --- |
| `data/*.json` — 4 business datasets, verbatim copies from Day05 | `knowledge_base.py` — parse/OCR/chunk/embed/permission-filtered retrieval |
| `knowledge/` — 10 docs (`public/`, `hr/`) + `day05_knowledge_manifest.json` | `build_index.py` — `build_vector_store()` entrypoint |
| `docs/` — Day05 (single-agent baseline) and Day06 courseware | `business_tools.py` — `RunContext`, `login_as()`, 7 business tools |
| `vector_store/` — empty; Chroma index goes here | `multi_agent.py` — specialists, Agent-as-Tool wrappers, Supervisor, sessions |
| `main.py` — PyCharm template boilerplate, replace entirely | `main.py` — the CLI entrypoint |
| `pyproject.toml` — `dependencies = []`, no `requirements.txt`, no `.env.example` | `.env.example`, `requirements.txt` |

`konwledge_base.py` is an empty, misspelled stub. The courseware module is **`knowledge_base`** — create that name and delete the typo.

`docs/Day06_多Agent综合项目：新员工助手升级.md` is the authoritative spec (architecture, exact code for `multi_agent.py`/`main.py`, fixed acceptance scenarios, troubleshooting table). `docs/Day05_综合案例：新员工助手Agent.md` holds the single-agent baseline, permission matrix, and the JSON field reference (附录 A). Read them before implementing.

The courseware states explicitly that nothing here has been verified to run — no dependency imports, index build, agent invocation, thread resumption, or acceptance run has been performed (§16.2). Do not claim otherwise without actually running it.

## Commands

```bash
uv sync                              # or: python -m pip install -r requirements.txt (file doesn't exist yet)
python build_index.py                # must run before main.py; writes vector_store/ + index_manifest.json
python main.py                       # interactive CLI
```

There is no test suite, no linter config, and no CI. Verification is by the fixed acceptance scenarios in Day06 §12.1: check the Supervisor's Agent-Tool calls, the specialists' business-Tool calls, the final answer, **and** the actual state of `data/day05_device_requests.json` — all four must agree.

CLI verbs: `/logout` switches accounts (new `RunContext`, new Supervisor, new `thread_id`), `/quit` exits. Write operations print an `interrupt()` payload and prompt `y`/`n`.

Environment (`.env`, gitignored — copy from `.env.example`): `MODEL_PROVIDER`, `MODEL_NAME`, `API_KEY`, `BASE_URL`, `EMBEDDING_MODEL`. `EMBEDDING_MODEL` is a Hugging Face model name (default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`) and is downloaded on first index build; `API_KEY`/`BASE_URL` are for the chat model only. Reference project uses `langchain-openai`, so an OpenAI-compatible endpoint is the mainline path — swapping `MODEL_PROVIDER` alone does not install the needed integration package.

Test accounts: `zhang_wei` (`employee`, 产品部) and `wang_fang` (`hr`, 人力资源部). 27 user records, 10 login-enabled.

## Architecture

Supervisor + Agent-as-Tool. The Supervisor holds **only** Agent Tools; specialists hold only their own business Tools. Specialists are never given each other's tools.

```
messages → Supervisor ─┬─ ask_knowledge_agent        → search_company_knowledge
                       ├─ ask_employee_service_agent → find_department, find_public_employee,
                       │                               list_requestable_devices,
                       │                               create_device_request, query_device_requests
                       └─ ask_hr_agent (hr only)     → query_device_requests, approve_device_request
```

**Four data planes, deliberately not merged** (Day06 §4.3):

| Plane | Holds | Mechanism |
| --- | --- | --- |
| `messages` | user's natural language | LangGraph state |
| Runtime Context | trusted `user_id` / `role` / `department_id` | `RunContext` frozen dataclass, injected by the app |
| Checkpoint | per-thread message history + interrupt position | `InMemorySaver` keyed by `thread_id` |
| Business data | request IDs, statuses | the JSON files in `data/` |

Account switching creates a new Context, Supervisor and `thread_id`, so conversation history does not carry over — but HR still reads the same shared business data.

**Agent Tool visibility is not permission.** There are two layers: (1) the role-filtered Agent Tool set on the Supervisor, which only reduces mis-routing; (2) the business Tool itself re-reading `runtime.context.role` before touching data. The second layer is the real protection. `approve_device_request` must return `permission_denied` for an employee even if it is somehow called.

The Supervisor must **rewrite** the task before delegating — resolve pronouns and omitted details from thread history into a self-contained `task` string. A specialist that cannot stand alone should ask for clarification rather than guess. Specialists receive only the sub-task and trusted context, never the Supervisor's full history or another specialist's prompt.

`specialist_result()` returns only `{agent, answer, business_tools}` — not the specialist's message list.

## Invariants when editing

- **Identity comes from login data only.** Chat claims like "我是 HR" must never alter `RunContext`. `login_as()` reads `day05_users.json`; `frozen=True` blocks field mutation.
- **Filter knowledge at retrieval time**, not after. Once unauthorized text reaches the model context, the boundary is already crossed. Use `allowed_roles` — `access_scope` is display-only, and directory names carry no authority.
- **Never wrap an Agent Tool in a broad `try/except`.** Inner write tools suspend with LangGraph `interrupt()`; catching that signal breaks human confirmation and resumption. `Command(resume={"approved": ...})` must reuse the original `thread_id` and context.
- **`chat()` submits only the new turn.** The checkpointer replays history from `thread_id`; re-sending prior messages duplicates the conversation.
- **Only `data/day05_device_requests.json` is mutated.** The other three JSONs and everything under `knowledge/` are read-only. To reset, re-copy from Day05.
- **Keep the `day05_` filename prefixes.** They look stale but are intentional — the course reuses Week14/Day05 artifacts verbatim.

## Data and knowledge contracts

- IDs are stable join keys: `USR-` / `DEPT-` / `DEV-` / `REQ-`. Resolve `applicant_user_id`, `reviewer_user_id`, `device_id`, `department_id` against their source files rather than denormalizing names.
- Request status is exactly `pending` / `approved` / `rejected`. Approved or rejected requests cannot be reviewed again. Approval means the request was reviewed, **not** that hardware was issued.
- `knowledge_base.py` exposes `build_vector_store()`, `search_knowledge()`, and `INDEX_MANIFEST_PATH`; `main.py` checks the latter to fail early when the index is missing.
- Manifest `parser_mode` drives the parse path: `text` / `document_text` / `pdf_text` / `html_text` parse normally; `ocr_required` (a text-layer-free scanned PDF) needs OCR; `multimodal_required` (the PNG office map) needs an image-capable model to preserve spatial relations. OCR/multimodal output is machine-recognized text — label it as such, never treat it as ground truth.
- Chunks inherit `document_id`, title, path, version, status and `allowed_roles` from their source document.

## Environment

Windows, Python 3.13 (`.python-version`, `pyproject.toml`), bash shell. Courseware and in-repo docs are Chinese; code identifiers, JSON keys and tool names are English.
