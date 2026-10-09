import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent import MissingApiKeyError, OrderAssistantAgent, ProviderError
from app.config import get_settings
from app.data_store import OrderDataStore
from app.models import ChatRequest, ChatResponse, ErrorDetail

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("order_assistant.api")

# Global instances initialized during lifespan
data_store: OrderDataStore = None
agent: OrderAssistantAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize application resources at startup and clean up at shutdown."""
    global data_store, agent
    settings = get_settings()
    logger.info("Initializing OrderDataStore from: %s", settings.data_path)
    data_store = OrderDataStore(data_path=settings.data_path)
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    logger.info("OrderDataStore loaded with %d orders.", len(data_store.orders))
    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="AI Order Assistant API",
    version="1.0.0",
    description="Backend API powering the full-stack AI Order Assistant with native tool calling.",
    lifespan=lifespan
)

# Configure CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Format Pydantic validation errors clearly."""
    error_messages = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        error_messages.append(f"{loc}: {msg}")
    joined_msg = "; ".join(error_messages)
    logger.warning("Request validation failed: %s", joined_msg)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": joined_msg, "error_type": "VALIDATION_ERROR"}
    )


@app.exception_handler(MissingApiKeyError)
async def missing_api_key_handler(request: Request, exc: MissingApiKeyError) -> JSONResponse:
    """Return informative error when AI provider API key is not configured."""
    logger.warning("Missing API key request attempt: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "error_type": "MISSING_API_KEY"}
    )


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    """Return 502 Bad Gateway when downstream AI provider fails."""
    logger.error("Downstream AI provider error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": str(exc), "error_type": "PROVIDER_ERROR"}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all unhandled exception handler to avoid leaking tracebacks."""
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred.", "error_type": "INTERNAL_SERVER_ERROR"}
    )


@app.get("/api/health", summary="Health Check")
async def health_check():
    """Verify backend health and order dataset loading status."""
    return {
        "status": "healthy",
        "orders_count": len(data_store.orders) if data_store else 0,
        "model": settings.openai_model
    }


@app.get("/api/orders", summary="List and Filter Orders")
async def list_orders(
    status: Optional[str] = None,
    customer: Optional[str] = None,
    category: Optional[str] = None,
    city: Optional[str] = None,
    product: Optional[str] = None,
    payment_method: Optional[str] = None,
    month: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
):
    """Retrieve orders from the dataset with optional filtering."""
    if not data_store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order data store is not ready."
        )
    orders = data_store.search_orders(
        status=status,
        customer=customer,
        category=category,
        city=city,
        product=product,
        payment_method=payment_method,
        month=month,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    return {
        "count": len(orders),
        "total": len(data_store.orders),
        "orders": orders
    }


@app.get("/api/analytics", summary="Get Dataset Analytics and Metrics")
async def get_analytics(
    status: Optional[str] = None,
    category: Optional[str] = None,
    city: Optional[str] = None,
    month: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Calculate authoritative business metrics from orders.csv."""
    if not data_store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order data store is not ready."
        )
    metrics = data_store.calculate_order_metrics(
        status=status,
        category=category,
        city=city,
        month=month,
        start_date=start_date,
        end_date=end_date
    )
    # Include top 5 highest-value orders from the dataset
    all_sorted = sorted(data_store.orders, key=lambda x: x["total_inr"], reverse=True)
    metrics["highest_value_orders"] = all_sorted[:5]
    return metrics


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    summary="Process User Chat Message",
    responses={
        422: {"model": ErrorDetail, "description": "Validation error"},
        502: {"model": ErrorDetail, "description": "AI provider failure"},
        503: {"model": ErrorDetail, "description": "AI API key missing"}
    }
)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint orchestrating LLM tool calling against orders.csv."""
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order assistant agent is not ready."
        )

    logger.info(
        "Received chat request (message length: %d chars, history items: %d)",
        len(request.message),
        len(request.conversation_history)
    )

    current_settings = get_settings()
    overall_timeout = current_settings.request_timeout * (current_settings.max_tool_iterations + 1)

    try:
        reply_text, tools_used = await asyncio.wait_for(
            agent.process_chat(
                user_message=request.message,
                conversation_history=request.conversation_history
            ),
            timeout=overall_timeout
        )
    except asyncio.TimeoutError:
        logger.error("Chat request timed out after %s seconds", overall_timeout)
        raise ProviderError(
            f"The request timed out after {int(overall_timeout)} seconds while waiting for the AI provider. "
            "Please try your request again."
        )

    logger.info("Chat request completed successfully (tools executed: %d)", len(tools_used))

    return ChatResponse(
        reply=reply_text,
        tools_used=tools_used
    )
