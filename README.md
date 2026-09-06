# 🇯🇵 NihongoChat (日本語 Chat)

> **AI Japanese Learning Agent with Gemini chat, Telegram study automation, and approval-gated Hermes Agent maintenance**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini_3.5_Flash-8E75B2?style=for-the-badge&logo=google&logoColor=white)
![Hermes Agent](https://img.shields.io/badge/Hermes_Agent-Autonomous_Repair-black?style=for-the-badge)
![Langfuse](https://img.shields.io/badge/Langfuse_Observability-FF4500?style=for-the-badge&logo=langfuse&logoColor=white)

---

## 🚀 Overview

**NihongoChat** is a Japanese-learning chat service with three deliberately separated automation systems: the chat application, a daily Telegram study digest, and guarded code maintenance.

Gemini handles chat and learning utilities. Runtime failures can start a bounded Hermes repair, while quality and performance signals create proposals that require explicit Telegram approval before Hermes may edit or commit code.

---

## 🔥 Key Architectural Features

### 1. ⚡ Asynchronous Pipeline Redesign (5s Response Latency)
- Replaced synchronous `[Chat ➔ Translation ➔ Furigana]` execution with an **instant chat output pipeline**.
- Translation and readings (Furigana) are fetched asynchronously in parallel via `Promise.all`, cutting user-perceived latency from **11s down to 5s (54% Reduction)**.

### 2. ☁️ Asynchronous Learning Utilities
- Gemini executes session summarization, grammar error extraction, and negative-feedback analysis through FastAPI `BackgroundTasks`.
- No on-device model server or model weights are required.

### 3. ⚙️ Hermes Agent Self-Healing Loop (Autonomous Code Repair)
- Runtime exceptions are sanitized and written to a durable, fingerprint-deduplicated incident queue. The web service never launches Hermes or performs Git operations.
- A separate macOS LaunchAgent polls the queue every 60 seconds and runs at most three persisted attempts per incident and code revision.
- Each attempt follows root-cause analysis, regression-test-first repair, and full verification inside a standalone Git clone outside the user home. Three failures discard that clone without touching service code.
- Hermes runs under macOS Seatbelt (`sandbox-exec`): all writes are limited to the isolated clone and a temporary credential-free home, while reads from the real user home are denied except for the exact project virtualenv and Hermes runtime. Outbound network access is limited to a loopback-only inference proxy.
- The proxy holds the Nous credential outside the agent sandbox. The default repair model is `meituan/longcat-2.0:free`; set `NIHONGO_REPAIR_MODEL=openai/gpt-5.6-sol` after adding Nous credits if Sol is required.
- Automatic repair refuses to run when the Git worktree is dirty, so unrelated user changes cannot be overwritten.
- Runtime repair never commits or pushes; success and failure are reported to Telegram.

### 4. 📈 Approval-Gated Continuous Improvement
- Every generated conversation response is scored asynchronously by an LLM-as-a-Judge.
- A no-LLM observer checks measured quality, duplicate responses, p95 latency, and explicit negative feedback every day at 21:00 KST.
- Threshold violations create a persisted proposal under `scratch/improvement/` and send it to Telegram. No code is changed at this stage.
- Reply `승인 IMP-... <approval-token>` in Telegram to let Hermes reproduce the issue, add a test, make the minimum change, verify the full suite, and create one Git commit. The token binds approval to the exact proposal and Git base commit.
- The paired Hermes Telegram gateway authenticates the remote sender and passes the bound token to the guarded CLI; direct CLI access is inside the trusted local-OS-user boundary.
- Reply `거절 IMP-...` to close the proposal. Approved work runs in a standalone clone under the same credential-free Seatbelt sandbox; failed or unsafe changes are discarded, and only a verified commit is applied.
- The agent follows RED-GREEN-REFACTOR, checks related call paths, edits only inside the repository, and runs focused and full tests.
- A file lock suppresses overlapping repairs. Incident prompts and results are saved under `scratch/self_healing/`.

### 5. 🌅 Daily Telegram Learning Digest
- At 08:00 KST, a no-agent cron job extracts exactly 10 distinct words from saved conversations.
- Each item includes a hiragana reading, Korean meaning, Japanese example, and Korean translation.
- Validation rejects duplicate words, romaji readings, malformed output, and lists that do not contain exactly 10 items.
- The daily payload is persisted before delivery. Retries reuse the exact same payload, and previously sent words are excluded from later digests.
- This job is separate from all code-repair and improvement workflows.

### 6. 🎭 MCP Prompts (Model Context Protocol) Standardization
- Standardizes roleplay scenarios (Café ordering, Airport check-in, Convenience store, Hotel desk) using the **Model Context Protocol (MCP)** specification.
- Dynamically switches system prompt instructions based on user-selected scenarios and custom argument inputs.

### 7. 📊 Langfuse Observability
- Integrated `@observe` decorators across core API endpoints (`/api/chat`, `/api/translate`, `/api/furigana`).
- Provides 100% visibility into latency breakdown, token costs, and full conversation traces via the Langfuse US Cloud dashboard.

### 8. 💬 Human-in-the-Loop Feedback Self-Refinement
- Captures **thumbs up (👍) / thumbs down (👎)** user feedback.
- Gemini analyzes explicit negative-feedback reasons into 1-sentence behavioral rules (`disliked_pattern_...`), which are injected into subsequent system prompts.

---

## 🏗️ System Architecture

```text
1. Frontend Layer (Vanilla JS)
   │  ├── Chat UI & Interactive Furigana / Translation Toggle
   │  └── Like/Dislike Human Feedback Buttons
   ▼
2. Core FastAPI Gateway Layer (main.py)
   │  ├── Security Guardrail (Prompt Injection Scan & Output Redaction)
   │  ├── MCP Prompts Module (mcp_prompts.py)
   │  ├── Langfuse Observability (@observe Tracing)
   │  └── Agentic Tool-Calling (Google Search Tool)
   ▼
3. AI Engine Layer
   │  ├── ☁️ Google Gemini 3.5 Flash (Main Chat & Fast Output)
   │  ├── ☁️ Google Gemini (Background Summary / Grammar / Feedback)
   │  └── ⚙️ Hermes Agent CLI (Runtime Repair + Approved Improvements)
   ▼
4. Persistence Layer (database.py)
      └── 💾 SQLite DB - nihongo_chat.db (sessions, messages, memories, summaries, facts, feedbacks)
```

---

## 📁 Directory Structure

```text
Japanese/
├── main.py                     # FastAPI gateway, routes & background task orchestrator
├── autonomous_repair.py        # Runtime exception → Hermes Agent repair runner
├── runtime_repair_worker.py    # Durable incident queue maintenance worker
├── continuous_improvement.py   # Metrics → proposal → approval → verified commit
├── sandboxed_hermes.py          # Seatbelt-confined credential-free Hermes runner
├── morning_digest.py            # Recent chats → validated Telegram study digest
├── notifications.py             # Telegram delivery via configured Hermes gateway
├── mcp_prompts.py              # MCP standard roleplay prompt definitions
├── database.py                 # SQLite database manager (6 tables persistence)
├── security_filters.py         # 2-step security guardrail (Prompt injection & data redaction)
├── templates/
│   └── index.html              # Main web UI template
├── static/
│   ├── app.js                  # Async UI controller & event handlers
│   └── style.css               # Dark mode & glassmorphism stylesheet
└── scratch/
    ├── self_healing/           # Ignored runtime incident prompts and logs
    └── improvement/            # Ignored approval-gated proposal state
```

---

## 🛠️ Getting Started

### 1. Prerequisites
- Python 3.11+
- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) installed and authenticated for autonomous repair

### 2. Environment Setup & Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables (`.env`)
Create a `.env` file in the project root:
```env
GEMINI_API_KEY="your-google-gemini-api-key"
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="https://us.cloud.langfuse.com"
```

### 4. Launch Application Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` in your web browser to launch **NihongoChat**! 🚀

### 5. Automation Status
```bash
hermes gateway status
hermes cron list
```

Default schedules use the Mac's local KST timezone:
- `0 8 * * *`: 10-word morning digest → Telegram
- `0 21 * * *`: improvement observer → Telegram only when a proposal exists

Approved improvement commands are intentionally guarded:
```bash
.venv/bin/python continuous_improvement.py approve IMP-YYYYMMDD-xxxxxxxx
.venv/bin/python continuous_improvement.py reject IMP-YYYYMMDD-xxxxxxxx
```

---

## 📄 Commit Conventions
This repository follows **Conventional Commits** standard specifications:
- `feat:` New features
- `fix:` Bug fixes
- `refactor:` Code refactoring and structural enhancements
- `docs:` Documentation updates and README edits
