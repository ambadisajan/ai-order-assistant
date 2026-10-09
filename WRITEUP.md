# Engineering Write-Up: AI Order Assistant

## 1. Architecture Overview

The **AI Order Assistant** is designed as a decoupled, multi-tier system that emphasizes data accuracy, modularity, and strong security boundaries:

```
[ React + Vite Frontend ]
           │
           │ HTTP POST /api/chat (JSON)
           ▼
[ FastAPI Backend (Port 8000) ]
   ├── Pydantic Input Validation (Length & non-empty sanitization)
   ├── CORS Middleware (Restricts origins)
   └── OrderAssistantAgent
           │
           ├── 1. Sends User Prompt + Tools Definition Schema to LLM
           │      (OpenAI / Compatible Provider)
           │
           ├── 2. LLM autonomously generates Tool Call (e.g., calculate_order_metrics)
           │
           ├── 3. Backend dispatches call to tools.py / OrderDataStore
           │      (Executes deterministic Python math on orders.csv)
           │
           ├── 4. Tool outputs formatted into JSON & returned to LLM
           │
           └── 5. LLM crafts final natural-language summary grounded in real data
```

### Architectural Decisions
- **Separation of Concerns**: The FastAPI server manages HTTP routing, validation, and error translation. The `OrderDataStore` owns raw CSV parsing and mathematical aggregations. The `OrderAssistantAgent` handles LLM communication and the multi-step tool-calling lifecycle.
- **Stateless Agent with History Passing**: The backend accepts `conversation_history` as an array of messages, allowing conversation persistence across turns without requiring database sessions in the initial phase.
- **FastAPI Async Pipeline**: All endpoints and OpenAI client calls leverage asynchronous I/O (`AsyncOpenAI`, async FastAPI handlers), allowing high-throughput request handling.

---

## 2. Dataset Schema & Alignment

The application strictly aligns with the Torcue technical screening dataset in `backend/data/orders.csv`:

| Column | Type | Description |
| :--- | :--- | :--- |
| `order_id` | String | Unique identifier (e.g., `ORD-1001`) |
| `order_date` | String (ISO) | Order date formatted as `YYYY-MM-DD` |
| `customer_name` | String | Full name of the customer (e.g., `Rahul Sharma`) |
| `city` | String | Delivery city (e.g., `Hyderabad`, `Chennai`, `Bengaluru`) |
| `product` | String | Purchased item name (e.g., `Wireless Mouse`, `Standing Desk`) |
| `category` | String | Product category (`Electronics`, `Accessories`, `Stationery`, `Furniture`) |
| `quantity` | Integer | Units ordered |
| `unit_price_inr` | Float | Unit price in Indian Rupees |
| `total_inr` | Float | Total amount in Indian Rupees (`quantity * unit_price_inr`) |
| `payment_method` | String | Payment method (`UPI`, `Debit Card`, `Credit Card`, `Cash on Delivery`, `Net Banking`) |
| `status` | String | Fulfillment status (`delivered`, `cancelled`, `returned`, `processing`, `shipped`) |

> [!IMPORTANT]
> The dataset contains **no customer email addresses**. The backend does not invent or assume email fields; search and aggregation tools operate exclusively over genuine columns.

---

## 3. Tool Selection & Design

The agent is equipped with three purpose-built tools:

| Tool | Purpose | Key Parameters |
| :--- | :--- | :--- |
| `get_order_details` | Point lookup for an exact order ID | `order_id` (string) |
| `search_orders` | Multi-criteria filtering of order records | `status`, `customer`, `category`, `city`, `product`, `payment_method`, `month`, `start_date`, `end_date`, `limit` |
| `calculate_order_metrics` | Aggregates order volume, cancelled counts, revenues, monthly category breakdown, and top spenders | `status`, `customer`, `category`, `city`, `payment_method`, `month`, `start_date`, `end_date` |

### Why This Toolset?
1. **Granularity over Monolithic Retrieval**: The tools expose constrained, strongly typed interfaces tailored to specific user intents.
2. **Defensive Lookups & Graceful Handling**:
   - `get_order_details` normalizes IDs (`ord-1001` matches `ORD-1001`). When an ID does not exist, it returns `{"found": false, "message": "Order with ID '...' was not found"}`, directing the LLM to inform the user instead of hallucinating.
   - `search_orders` returns `{"count": 0, "orders": []}` when no rows match, allowing the assistant to report zero results clearly.
3. **Monthly Category Aggregations**: `calculate_order_metrics` natively computes `category_revenue_by_month` and isolates the `highest_spending_customer` directly in Python.

---

## 4. Accuracy Guardrails & Anti-Hallucination Policy

Language models are notoriously prone to arithmetic hallucinations. To guarantee 100% financial accuracy:

1. **Python-Enforced Mathematics**:
   - The LLM never computes sums or counts. It invokes `calculate_order_metrics`, and Python's `OrderDataStore` computes exact sums from the CSV records.
2. **Clear Revenue & Cancelled Orders Definition**:
   - **Net Revenue (INR)**: Strictly sums `total_inr` for active/fulfilled orders (`delivered`, `shipped`, `processing`, `returned`). Excludes cancelled orders.
   - **Cancelled Orders**: Filtered by `status.lower() == 'cancelled'`, counted explicitly, and their lost value tracked under `cancelled_revenue_inr`.
   - **Gross Revenue (INR)**: `net_revenue_inr + cancelled_revenue_inr`.
   - **Customer Spending**: Calculated as net spend (excluding cancelled orders) alongside order counts and cancelled order counts per customer.
3. **Strict System Prompt Guardrails**:
   - Explicit instructions that the model must NEVER invent order numbers, prices, or statuses.
   - Compulsory tool usage: whenever asked about any order data or metrics, the model must invoke the relevant tool.

---

## 5. Validation, Error Handling, and Security

### Request Validation
- `ChatRequest` uses Pydantic's `@field_validator` to reject empty strings and whitespace-only payloads.
- Enforces `min_length=1` and `max_length=2000` to prevent token-exhaustion denial-of-service attempts.
- Conversation history is capped at 50 messages to prevent unbounded context growth.

### Error Handling Strategy
- **Missing API Key (`HTTP 503 Service Unavailable`)**: If `OPENAI_API_KEY` is empty or left as placeholder, the API intercepts this before making any network call, providing an actionable diagnostic message.
- **Provider Failures (`HTTP 502 Bad Gateway`)**: Catches `AuthenticationError`, `RateLimitError`, `APIConnectionError`, and `APIStatusError`, shielding internal stack traces from clients.
- **Invalid Payload (`HTTP 422 Unprocessable Entity`)**: Formats validation errors into human-readable details.
- **Unknown Exceptions (`HTTP 500 Internal Server Error`)**: Global catch-all handler logs the traceback securely on the server and returns a clean error response.

---

## 6. Verification & Test Suite

The backend contains **25 pytest tests** across two suites:
- `backend/tests/test_tools.py` (16 tests):
  - Check that all 60 orders load from `orders.csv`.
  - Order lookup by ID, case insensitivity, unknown order ID handling, empty ID validation.
  - Search filtering by status (48 delivered, 7 cancelled, 3 returned), customer (`Rahul Sharma`), category & city (Chennai Electronics), product (`Standing Desk`), payment method (`UPI`), and month (`2026-06`, `2026-07`).
  - Graceful empty search results handling.
  - Mathematical verification of total orders (60), cancelled orders (7), active orders (53), net revenue (₹397,678), gross revenue (₹470,312), and cancelled revenue (₹72,634).
  - Monthly category revenue verification (`2026-06` Electronics, Accessories, Stationery, Furniture).
  - Highest-spending customer (`Rohan Das` with ₹112,282 net spend) and cancellation exclusion (`Vikram Reddy`).
  - Unknown tool invocation handling.
- `backend/tests/test_api.py` (9 tests):
  - Health check endpoint verification (60 orders loaded).
  - Validation rejections for empty messages and length > 2,000 characters.
  - Missing message field rejection.
  - HTTP 503 response on missing API key.
  - HTTP 502 response on downstream 401/429 provider errors.
  - End-to-end tool-calling execution flow with mocked provider responses matching the new schema.
  - CORS header responses.

All 25 tests pass locally:
```
======================= 25 passed in 0.14s =======================
```

---

## 7. Recommended Future Enhancements

1. **Streaming Function Calling (Server-Sent Events)**: Stream LLM token responses and emit tool-execution state events in real time.
2. **Export Capabilities**: Allow the assistant to generate downloadable CSV or PDF summaries of filtered order queries.
3. **Role-Based Access Control (RBAC)**: Restrict customer support agents to customer-facing details, while reserving full revenue metrics for manager roles.
4. **Vector / Semantic Search**: Add vector embeddings for product catalog search to allow natural queries like "show orders with ergonomic gear".
