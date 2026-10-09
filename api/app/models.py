from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """Represents a message in the conversation history, supporting user, assistant, system, and tool turns."""
    role: Literal["user", "assistant", "system", "tool"]
    content: Optional[str] = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    function_call: Optional[Any] = None


class ChatRequest(BaseModel):
    """Incoming request payload for POST /api/chat."""
    message: str = Field(
        ...,
        description="The user's query or message.",
        min_length=1,
        max_length=2000
    )
    conversation_history: List[ChatMessage] = Field(
        default_factory=list,
        max_length=50,
        description="Previous turns in the conversation for multi-turn context."
    )

    @field_validator("message")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Message cannot be empty or contain only whitespace.")
        if len(trimmed) > 2000:
            raise ValueError("Message exceeds the maximum permitted length of 2000 characters.")
        return trimmed


class ToolCallRecord(BaseModel):
    """Details of a tool executed during agent processing."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Any


class ChatResponse(BaseModel):
    """Response payload for POST /api/chat."""
    reply: str
    tools_used: List[ToolCallRecord] = Field(default_factory=list)


class Order(BaseModel):
    """Schema representing an order record matching backend/data/orders.csv."""
    order_id: str
    order_date: str
    customer_name: str
    city: str
    product: str
    category: str
    quantity: int
    unit_price_inr: float
    total_inr: float
    payment_method: str
    status: str


class ErrorDetail(BaseModel):
    """Standardized error response body."""
    detail: str
    error_type: str
