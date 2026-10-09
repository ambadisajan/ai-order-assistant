# AI Order Assistant

A production-grade, full-stack AI Order Assistant designed for customer support and e-commerce analytics. It integrates a **FastAPI** backend with genuine **native LLM tool calling**, deterministic Python data calculations on the Torcue technical screening dataset (`backend/data/orders.csv`), and a modern **React + Vite** frontend.

---

## Key Features

- **Native LLM Tool Calling**: Uses OpenAI-compatible function calling where the model independently selects tools based on user queries.
- **Deterministic Accuracy & Anti-Hallucination**: Financial metrics, revenue calculations, cancellation counts, and order statuses are strictly computed in Python using `backend/data/orders.csv`. The LLM never invents numbers.
- **Torcue Screening Dataset Schema**:
  - Columns: `order_id, order_date, customer_name, city, product, category, quantity, unit_price_inr, total_inr, payment_method, status`
  - Total records: 60 orders across Indian cities with INR currency.
- **Clear Revenue Policy**:
  - **Net Revenue (INR)**: Calculated strictly on non-cancelled orders (`delivered`, `shipped`, `processing`, `returned`). Excludes cancelled orders.
  - **Cancelled Orders**: Quantified and tracked explicitly (`cancelled_orders` count and `cancelled_revenue_inr`).
  - **Gross Revenue (INR)**: Provided as total gross sum of all matching orders.
  - **Category Revenue by Month**: Tracked across months (`YYYY-MM`) for active fulfilled orders.
  - **Highest-Spending Customer**: Computed with accurate cancellation exclusion.
- **Input Validation & Security Guardrails**:
  - Request body validation with Pydantic: rejects empty/whitespace messages and messages exceeding 2,000 characters.
  - API keys loaded from environment variables (`.env`), never exposed to the frontend.
  - Restrictive CORS configuration.
  - Graceful handling of unknown order IDs, empty search results, missing API credentials (HTTP 503), and downstream provider errors (HTTP 502).
- **Comprehensive Pytest Suite**: 25 verified unit and integration tests covering dataset loading (60 orders), tool lookups, search filters, metric calculations, input validation, and API error states.

---

## Project Structure

```
ai-order-assistant/
├── .gitignore                    # Excludes secrets, venv, node_modules, build artifacts
├── README.md                     # Setup guide and usage documentation
├── WRITEUP.md                    # Architecture, design decisions, and guardrails
├── backend/
│   ├── .env.example              # Environment variables template for backend
│   ├── requirements.txt          # Python dependencies
│   ├── data/
│   │   └── orders.csv            # Ground-truth Torcue dataset (60 orders)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py             # Pydantic BaseSettings & CORS management
│   │   ├── models.py             # ChatRequest, ChatResponse, Order schemas
│   │   ├── data_store.py         # CSV loader, search, and deterministic math
│   │   ├── tools.py              # OpenAI function schemas & execution dispatcher
│   │   ├── agent.py              # Tool-calling agent loop with guardrails
│   │   └── main.py               # FastAPI application & error handlers
│   └── tests/
│       ├── conftest.py           # Pytest fixtures and test client setup
│       ├── test_tools.py         # Unit tests for lookup, search, and metrics
│       └── test_api.py           # Integration tests for validation & API errors
└── frontend/
    ├── .env.example              # Environment variables template for frontend
    ├── package.json              # Frontend dependencies and scripts
    ├── vite.config.js            # Vite configuration
    └── src/                      # React components and chat UI
```

---

## Prerequisites

- **Python**: 3.10 or higher
- **Node.js**: v18 or higher (tested on v24) and npm
- **LLM API Key**: OpenAI API key (or any OpenAI-compatible API key such as Groq, Ollama, or Gemini OpenAI endpoint)

---

## Backend Setup & Execution

### 1. Navigate to the backend directory
```bash
cd backend
```

### 2. Create and activate a Python virtual environment
- **On Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
- **On macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 3. Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables
Copy `.env.example` to `.env`:
- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

Open `.env` and configure your API key:
```env
OPENAI_API_KEY=your_actual_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
PORT=8000
HOST=0.0.0.0
DATA_PATH=data/orders.csv
```

### 5. Run the Pytest test suite
```bash
pytest -v
```
*Expected: 25 passed tests in < 0.25 seconds.*

### 6. Start the FastAPI backend server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Interactive Swagger API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check endpoint: [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## Frontend Setup & Execution

### 1. Navigate to the frontend directory
```bash
cd ../frontend
```

### 2. Install dependencies
```bash
npm install
```

### 3. Configure environment variables
Copy `.env.example` to `.env`:
- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

### 4. Start the Vite development server
```bash
npm run dev
```
Open your browser at [http://localhost:5173](http://localhost:5173).

---

## API Specification

### `GET /api/health`
Checks server health and reports the number of loaded order records.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "orders_count": 60,
  "model": "gpt-4o-mini"
}
```

### `POST /api/chat`
Processes conversational queries via the native function-calling agent.

**Request Body:**
```json
{
  "message": "What is the status of order ORD-1001?",
  "conversation_history": []
}
```

**Response (200 OK):**
```json
{
  "reply": "Order ORD-1001 was placed by Rahul Sharma on 2026-06-01 for 2 Wireless Mouse units (₹1598) via Debit Card. Its current status is **delivered** in Hyderabad.",
  "tools_used": [
    {
      "tool_name": "get_order_details",
      "arguments": {
        "order_id": "ORD-1001"
      },
      "result": {
        "found": true,
        "order": {
          "order_id": "ORD-1001",
          "order_date": "2026-06-01",
          "customer_name": "Rahul Sharma",
          "city": "Hyderabad",
          "product": "Wireless Mouse",
          "category": "Electronics",
          "quantity": 2,
          "unit_price_inr": 799.0,
          "total_inr": 1598.0,
          "payment_method": "Debit Card",
          "status": "delivered"
        }
      }
    }
  ]
}
```

**Error Responses:**
- `422 Unprocessable Entity`: Empty message, message > 2000 characters, or invalid JSON.
- `502 Bad Gateway`: Downstream AI provider connection failure, rate limit, or invalid key.
- `503 Service Unavailable`: `OPENAI_API_KEY` missing or unconfigured.

---

## Tools Implemented

1. `get_order_details`: Fetches order by `order_id` (case-insensitive). Returns `{"found": false}` for unknown IDs.
2. `search_orders`: Filters orders by `status`, `customer`, `category`, `city`, `product`, `payment_method`, `month`, and `date range`.
3. `calculate_order_metrics`: Computes total orders, cancellation counts, net revenue in INR, gross revenue in INR, category revenue by month, and highest-spending customer calculations.
