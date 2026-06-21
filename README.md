# Asynchronous Local AI Document Processing Agent

A production-grade, event-driven AI Agent pipeline designed to securely ingest, parse, audit, and persist unstructured multi-page PDFs (such as medical bills and Explanations of Benefits) completely locally. 

This system moves beyond basic AI scripting by implementing an **Asynchronous Event-Driven Architecture** to eliminate HTTP request timeouts, alongside an **Automated Self-Correction Loop** to eliminate LLM mathematical hallucinations.

---

## 🏗️ System Architecture & Data Flow

Instead of a standard synchronous request-response model, this application decouples ingestion from heavy computational AI inference using an asynchronous state-machine pattern.



### End-to-End Processing Lifecycle:
1. **Ingestion Channel (`POST /process-bill/`):** The client uploads a PDF file. The FastAPI HTTP thread generates a unique UUID `task_id`, streams the binary payload onto the local filesystem, inserts a state-tracking record into MongoDB initialized to `"QUEUED"`, and immediately returns an HTTP `202 Accepted` response within milliseconds.
2. **Background Task Delegation:** The intensive execution payload is handed off out-of-band to an asynchronous background worker pool, freeing up the primary web thread to absorb further incoming traffic.
3. **Context Isolation (Page-by-Page Extraction):** To maximize accuracy on smaller local models (Llama 3 8B), the background task parses the document page-by-page. It targets specific pages with specialized workers—utilizing a `Summary Worker` schema for high-level numbers on page 1, and an `Items Worker` schema for granular tabular details on page 2.
4. **Automated Mathematical Audit (Self-Correction Layer):** The background processor programmatically executes business logic by computing the exact sum of all itemized extraction lines ($\sum \text{amount\_billed}$) and matching it against the extracted `total_amount_due`. If a mismatch is caught, an agentic loop re-prompts the local LLM with an explicit error correction instruction up to 3 times before setting a fallback flag.
5. **State Synchronization:** Once processing completes, the final structured payload is mapped into a BSON document and saved to MongoDB, updating the task status to `"COMPLETED"` or `"WARNING"`.
6. **Real-Time UI Visualization:** A reactive Streamlit front-end continuously polls the `GET /tasks/{task_id}` gateway endpoint to transition its UI from progress loaders to rich data tables and metric analytics dynamically.

---

## 🛠️ Technology Stack

- **Backend Framework:** FastAPI (Asynchronous Python framework)
- **Front-End Dashboard:** Streamlit (Pure Python reactive web application)
- **Orchestration Layer:** LangChain (Structured output bindings & LLM prompt chain tooling)
- **Local AI Engine:** Ollama running Llama 3 (Deterministic execution configuration: `temperature=0`)
- **Data Validation & Contracts:** Pydantic v2 (Strict typing, serialization, and schema definition)
- **Persistence Layer:** MongoDB via Motor (Asynchronous, non-blocking NoSQL driver)
- **File Parsing Engine:** PyPDF (Binary disk stream processing)

---

## 📂 Repository Structure

```text
local-ai-document-agent/
│
├── main.py             # FastAPI App: Ingestion endpoints & background task worker
├── app.py              # Streamlit Web App: Interactive visualization dashboard
├── .gitignore          # Excludes virtual environments, cache, and uploaded files
├── README.md           # Technical project documentation
└── uploaded_files/     # Local disk landing directory for asynchronous queues (Auto-managed)
