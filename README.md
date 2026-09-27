# magicpin AI Challenge — Vera Merchant AI Assistant

A stateful, low-latency, context-grounded outbound WhatsApp copilot built for the **magicpin AI Challenge**[cite: 2, 8]. The engine composes high-impact merchant-facing and customer-facing interactions across categories including dentists, salons, restaurants, gyms, and pharmacies[cite: 1, 3].

---

## 1. Approach & System Architecture

The solution uses a **Hybrid Strategic-Directive + Conversational Paraphrasing Architecture** designed to execute within the strict 30-second tick deadline while systematically maximizing scores across all 5 evaluation dimensions[cite: 1, 2]:
                 ┌──────────────────────────────────────────────┐
                 │           4-Context State Engine             │
                 │ (CategoryContext, MerchantContext, Trigger,  │
                 │               CustomerContext)               │
                 └──────────────────────┬───────────────────────┘
                                        │
                                        ▼
                 ┌──────────────────────────────────────────────┐
                 │         Strategic Directive Engine           │
                 │  - Enforces Decision Quality heuristics      │
                 │  - Injects category vocabulary & taboos      │
                 │  - Selects active catalog offers & slots     │
                 └──────────────────────┬───────────────────────┘
                                        │
                                        ▼
                 ┌──────────────────────────────────────────────┐
                 │          Conversational Paraphraser          │
                 │   (LLM naturalization, tone adaptation,      │
                 │     plagiarism avoidance, & jitter/backoff)  │
                 └──────────────────────┬───────────────────────┘
                                        │
                                        ▼
                 ┌──────────────────────────────────────────────┐
                 │       Guardrails & Compliance Validator      │
                 │  - URL suppression (Zero http/https)         │
                 │  - Anti-repetition & length compliance       │
                 │  - Structured JSON validation & deduplication│
                 └──────────────────────────────────────────────┘

### Core Execution Pillars
- **Strict Role Routing:** Enforces explicit message boundaries based on scope[cite: 1, 3]:
  - **Merchant-Facing (`customer` is null):** Addresses the owner directly as an operational peer (e.g., `"Hi Dr. Meera, Vera here."` or `"Hi Suresh, Vera here."`)[cite: 1, 3].
  - **Customer-Facing (`customer` is present):** Sent on behalf of the business (e.g., `"Hi Priya, Dr. Meera's clinic here."`)[cite: 1, 3].
- **Strategic Decision Quality:** Replaces passive metrics reporting with proactive guidance[cite: 1]. Every performance dip, surge, or external event is paired with an operational diagnosis, a contrarian or domain-grounded recommendation (e.g., reallocating ad spend during expected seasonal gym lulls; shifting from dine-in promos to delivery specials during Saturday IPL games), and a catalog action[cite: 1].
- **Verifiable Specificity:** Extracts data points directly from context payloads—trial cohorts, source citations (e.g., *JIDA Oct 2026, p.14*), batch numbers, affected customer counts, and exact catalog prices (e.g., *₹299*)—without inventing numbers[cite: 1].
- **Low-Friction Binary CTA:** Avoids ambiguous open-ended questions in favor of single-action next steps (e.g., `"Reply YES to schedule"`, `"Reply 1 for Wed, 2 for Thu"`)[cite: 1].

---

## 2. Model Choice & Tradeoffs

| Parameter | Selection | Rationale |
| :--- | :--- | :--- |
| **Model** | `gemini-3.1-flash-lite` | Delivers sub-second inference speeds to comfortably complete batch evaluations within the 30-second tick budget[cite: 2]. |
| **Temperature** | `0.4` – `0.5` | Balances strict adherence to extracted numerical facts with natural phrasing to prevent plagiarism penalties[cite: 1]. |

### Tradeoffs & Mitigations
- **Lightweight Model Reasoning:** Smaller models can struggle with complex zero-shot multi-variable reasoning and role persistence[cite: 1].  
  *Mitigation:* Python handles the heavy analytical lifting (metric extraction, offer selection, and strategic directives), allowing the LLM to focus purely on natural tone, category vocabulary, and readability.
- **Concurrent Request Throttling:** Simultaneous batch triggers during `/v1/tick` calls can trigger rate limits[cite: 2].  
  *Mitigation:* Staggered asynchronous requests using jitter and exponential backoff retry loops guarantee fault tolerance.
- **Strict 30s Deadline vs. Quality:**  
  *Mitigation:* A robust, context-grounded fallback ensures that if an upstream timeout occurs, a high-scoring, schema-compliant action is delivered immediately[cite: 2].

---

## 3. Endpoints Implemented

The service implements all 5 required endpoints under `/v1/*`[cite: 2]:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/v1/context` | Idempotently receives and updates context payloads (`category`, `merchant`, `customer`, `trigger`)[cite: 2]. |
| `POST` | `/v1/tick` | Periodic wake-up; evaluates active triggers and initiates proactive messages with low-friction CTAs[cite: 2]. |
| `POST` | `/v1/reply` | Multi-turn dialogue handler responding to simulated merchant or customer interactions (`send`, `wait`, `end`)[cite: 2]. |
| `GET` | `/v1/healthz` | Liveness probe reporting service uptime and loaded context inventory[cite: 2]. |
| `GET` | `/v1/metadata` | Identifies team credentials, active model, and architectural approach[cite: 2]. |

---

## 4. Local Setup & Execution

### Prerequisites
- Python 3.10+
- Valid LLM API Key (`LLM_API_KEY`)

### Installation
```bash
# Clone the repository
git clone <your-repo-url>
cd magicpin

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
Environment Variables (.env)
Ini, TOML
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.1-flash-lite
LLM_API_KEY=your_api_key_here
BOT_PORT=8080

Running the Server
Bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
Running the Challenge Simulator
Bash
python judge_simulator.py