# 🇯🇵 NihongoChat (日本語 Chat)

> **Hybrid AI Japanese Learning Agent featuring $0 Operating Cost, 0.5s Low Latency, Real-Time Local RAG, and Autonomous Codex & Hermes Self-Healing Loop**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini_3.5_Flash-8E75B2?style=for-the-badge&logo=google&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama_Hermes_3_8B-black?style=for-the-badge&logo=ollama&logoColor=white)
![Langfuse](https://img.shields.io/badge/Langfuse_Observability-FF4500?style=for-the-badge&logo=langfuse&logoColor=white)

---

## 🚀 Overview

**NihongoChat** is an advanced hybrid AI agent pipeline built to solve critical bottlenecks in conversational AI applications: **high response latency (11s)**, **accumulating cloud API costs**, **lack of real-time local context**, and **manual code debugging overhead**.

By decoupling conversation generation from auxiliary text processing, NihongoChat reduced user-perceived latency by **54% (down to 0.5s)**. Background tasks like session summarization, grammar error parsing, and negative feedback analysis are offloaded to a **local Ollama Hermes 3 (8B)** LLM, achieving **$0 background operating cost**. Furthermore, an autonomous **Codex + Hermes Self-Healing Loop** automatically diagnoses runtime exceptions and user feedback, generating fix blueprints (`fix_blueprint.txt`) and mutating code autonomously.

---

## 🔥 Key Architectural Features

### 1. ⚡ Asynchronous Pipeline Redesign (0.5s Response Latency)
- Replaced synchronous `[Chat ➔ Translation ➔ Furigana]` execution with an **instant chat output pipeline**.
- Translation and readings (Furigana) are fetched asynchronously in parallel via `Promise.all`, cutting user-perceived latency from **11s down to 0.5s**.

### 2. 🤖 Local Hermes 0-Cost Background Utility
- Embedded local **Hermes 3 8B (via Ollama)** to handle heavy background utilities at zero cloud API cost.
- Executes session summarization, grammar error extraction, and negative user feedback analysis asynchronously via FastAPI `BackgroundTasks`.

### 3. ⚙️ Codex & Hermes Self-Healing Loop (Autonomous Code Repair)
- Upon runtime exceptions or dislike feedback, local Hermes analyzes stack traces at $0 cost to generate a structured **`scratch/fix_blueprint.txt`**.
- The **Codex / Code Mutation Engine (OpenAI Codex / Gemini)** receives the blueprint and automatically rewrites clean, bug-free Python code.

### 4. 🕷️ OpenClaw Scraper & Real-Time RAG
- Automatically collects trending topics from Yahoo! Japan RSS feeds into an SQLite database (`live_trends`).
- Dynamically injects real-time Japanese trend context into the System Prompt for enhanced local relevance.

### 5. 🎭 MCP Prompts (Model Context Protocol) Standardization
- Standardizes roleplay scenarios (Café ordering, Airport check-in, Convenience store, Hotel desk) using the **Model Context Protocol (MCP)** specification.
- Dynamically switches system prompt instructions based on user-selected scenarios and custom argument inputs.

### 6. 📊 100% Langfuse Observability
- Integrated `@observe` decorators across core API endpoints (`/api/chat`, `/api/translate`, `/api/furigana`).
- Provides 100% visibility into latency breakdown, token costs, and full conversation traces via the Langfuse US Cloud dashboard.

### 7. 💬 Human-in-the-Loop Feedback Self-Refinement
- Captures **thumbs up (👍) / thumbs down (👎)** user feedback.
- Hermes analyzes negative feedback to extract 1-sentence behavioral rules (`disliked_pattern_...`), which are injected into subsequent System Prompts for continuous self-refinement.

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
3. Hybrid AI Agent Engine Layer
   │  ├── ☁️ Google Gemini 3.5 Flash (Main Chat & Fast Output)
   │  ├── 🤖 Local Hermes Agent (0-Cost Background Summary / Grammar / Feedback)
   │  ├── 🕷️ OpenClaw Scraper (Yahoo! Japan Live Trends RAG)
   │  └── ⚙️ Codex Engine (Hermes Blueprint-Based Self-Healing Loop)
   ▼
4. Persistence Layer (database.py)
      └── 💾 SQLite DB - nihongo_chat.db (sessions, messages, memories, summaries, facts, trends, feedbacks)
```

---

## 📁 Directory Structure

```text
Japanese/
├── main.py                     # FastAPI gateway, routes & background task orchestrator
├── hermes_client.py            # Local Ollama Hermes 3 8B integration (Summaries, Grammar, Feedback)
├── codex_hermes_loop.py        # Autonomous Hermes diagnosis + Codex code repair loop
├── openclaw_collector.py       # Yahoo! Japan real-time trend scraper & DB loader
├── mcp_prompts.py              # MCP standard roleplay prompt definitions
├── database.py                 # SQLite database manager (7 tables persistence)
├── security_filters.py         # 2-step security guardrail (Prompt injection & data redaction)
├── templates/
│   └── index.html              # Main web UI template
├── static/
│   ├── app.js                  # Async UI controller & event handlers
│   └── style.css               # Dark mode & glassmorphism stylesheet
└── scratch/
    ├── fix_blueprint.txt       # Auto-generated repair blueprint by Hermes
    └── test_codex_hermes_healing.py  # Self-healing loop simulation test runner
```

---

## 🛠️ Getting Started

### 1. Prerequisites
- Python 3.11+
- [Ollama](https://ollama.com/) installed locally with `hermes3:8b` model pulled:
  ```bash
  ollama pull hermes3:8b
  ```

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
OPENAI_API_KEY="your-openai-api-key"   # Optional: For Genuine OpenAI Codex Engine
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="https://us.cloud.langfuse.com"
```

### 4. Launch Application Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` in your web browser to launch **NihongoChat**! 🚀

---

## 📄 Commit Conventions
This repository follows **Conventional Commits** standard specifications:
- `feat:` New features
- `fix:` Bug fixes
- `refactor:` Code refactoring and structural enhancements
- `docs:` Documentation updates and README edits
