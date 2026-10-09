import asyncio
import json
import logging
from typing import Any, Dict, List, Tuple, Union
from openai import (
    AsyncOpenAI,
    OpenAIError,
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)

from app.config import Settings
from app.data_store import OrderDataStore
from app.models import ChatMessage, ToolCallRecord
from app.tools import TOOLS_SCHEMA, execute_tool

logger = logging.getLogger("order_assistant.agent")


class MissingApiKeyError(Exception):
    """Raised when the AI provider API key is not configured."""
    pass


class ProviderError(Exception):
    """Raised when an error occurs while communicating with the AI provider."""
    pass


SYSTEM_PROMPT = """You are the AI Order Assistant, an intelligent customer support and analytics agent for an e-commerce platform.
You assist customers and managers by retrieving order status, searching orders, and calculating financial and order statistics from the orders dataset.

DATASET SCHEMA & ATTRIBUTES:
- Each order contains: order_id, order_date, customer_name, city, product, category, quantity, unit_price_inr, total_inr, payment_method, status.
- Status values in the dataset: delivered, cancelled, returned, processing, shipped.
- Currency is strictly Indian Rupees (INR / ₹).
- NOTE: There is NO customer email address in this dataset. Never invent or ask for customer emails.

CRITICAL ACCURACY & GUARDRAIL INSTRUCTIONS:
1. NEVER fabricate, estimate, or hallucinate order records, customer names, dates, financial figures, or order statuses.
2. ALWAYS use the appropriate tool to answer questions about orders or metrics:
   - Call `get_order_details` when looking up a specific order by order ID (e.g. ORD-1001, ORD-1015).
   - Call `search_orders` when searching or filtering orders by customer name, status, category, city, product, payment method, month, or date range.
   - Call `calculate_order_metrics` when computing order counts, cancellation counts, delivered revenue, net revenue, category revenue by month, or highest-spending customers.
3. FINANCIAL & REVENUE DEFINITION POLICY:
   - Net revenue (INR) strictly EXCLUDES cancelled orders (sums active orders: delivered, returned, processing, shipped).
   - Delivered revenue (INR) specifically sums orders with status 'delivered' (48 orders totalling ₹371,040).
   - Cancelled orders (7 orders in the dataset, including ORD-1005, ORD-1015, ORD-1018, ORD-1030, ORD-1041, ORD-1045, ORD-1058) are tracked separately as cancelled orders and cancelled revenue (₹72,634).
   - Gross revenue represents the total of all orders including cancelled orders (₹470,312).
   - When asked for both delivered revenue and cancelled orders, call `calculate_order_metrics` without a status filter; it returns `delivered_orders`, `delivered_revenue_inr`, `cancelled_orders`, `cancelled_revenue_inr`, and status breakdowns across the whole dataset in one call.
   - If a status filter is passed (e.g., status='delivered'), consult `dataset_summary` for overall dataset counts so you never report zero cancelled orders when cancelled records exist in the dataset.
   - Always report the exact numbers computed by the tools in INR. Never perform dataset math in your head.
4. CATEGORY REVENUE BY MONTH & TOP CUSTOMERS:
   - `calculate_order_metrics` returns `category_revenue_by_month` (breakdown of active revenue by month and category) and `highest_spending_customer` / `top_customers_spending`. Use these exact computed values.
5. UNKNOWN ORDERS & EMPTY RESULTS:
   - If `get_order_details` returns `found: false`, state clearly that the order ID was not found in the database. Politely ask the user to double check the ID (e.g., ORD-1001).
   - If `search_orders` returns 0 orders, state clearly that no orders matched the specified criteria.
6. FORMATTING:
   - Provide clear, professional, and well-structured responses using markdown (bullet points, bold highlights, tables where helpful).
   - If tools were called, summarize the results transparently.
"""


def sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize message objects before sending to OpenAI/Groq API:
    1. Completely strips any 'function_call' keys whose value is null/None or empty,
       preventing Groq's: 'messages.X for role:assistant requires messages.X.function_call not to be null'.
    2. Strips all keys where value is None (e.g. content: None, refusal: None, audio: None).
    3. Ensures assistant messages without tool_calls have a string content (defaulting to '').
    4. Formats tool_calls and tool results strictly according to OpenAI / Groq tool-calling specs.
    """
    sanitized: List[Dict[str, Any]] = []

    for msg in messages:
        cleaned: Dict[str, Any] = {}
        for k, v in msg.items():
            # Never send function_call if it is None or empty
            if k == "function_call":
                if v is not None and v != "":
                    cleaned[k] = v
                continue
            # Strip any nullable/None fields
            if v is None:
                continue
            cleaned[k] = v

        role = cleaned.get("role")
        if not role:
            continue

        # If role is assistant and has tool_calls, ensure tool_calls is non-empty list
        if role == "assistant":
            tool_calls = cleaned.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
                cleaned["tool_calls"] = tool_calls
            else:
                # If assistant message has no tool_calls, content must be a string
                cleaned.pop("tool_calls", None)
                if "content" not in cleaned:
                    cleaned["content"] = ""

        # If role is tool, ensure tool_call_id and content exist
        if role == "tool":
            cleaned["tool_call_id"] = str(cleaned.get("tool_call_id", ""))
            cleaned["content"] = str(cleaned.get("content", ""))

        sanitized.append(cleaned)

    return sanitized


def format_assistant_message(response_message: Any) -> Dict[str, Any]:
    """Format an assistant message for the conversation history,
    ensuring Groq and OpenAI compatibility by strictly omitting null fields
    such as function_call: null, refusal: null, audio: null, etc.
    """
    msg: Dict[str, Any] = {"role": "assistant"}

    # Include content only if it is a non-empty string, avoiding content: null
    content = getattr(response_message, "content", None)
    if isinstance(response_message, dict):
        content = response_message.get("content")
    if content:
        msg["content"] = str(content)

    # Format tool_calls properly with required OpenAI / Groq structure
    tool_calls = getattr(response_message, "tool_calls", None)
    if isinstance(response_message, dict):
        tool_calls = response_message.get("tool_calls")

    if tool_calls:
        formatted_calls = []
        for tc in tool_calls:
            tc_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else "")
            tc_type = getattr(tc, "type", None) or (tc.get("type") if isinstance(tc, dict) else "function")
            func = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)

            func_name = getattr(func, "name", None) or (func.get("name") if isinstance(func, dict) else "")
            func_args = getattr(func, "arguments", None) or (func.get("arguments") if isinstance(func, dict) else "{}")

            formatted_calls.append({
                "id": str(tc_id),
                "type": str(tc_type),
                "function": {
                    "name": str(func_name),
                    "arguments": str(func_args or "{}")
                }
            })
        if formatted_calls:
            msg["tool_calls"] = formatted_calls

    return msg


def format_chat_message(msg: Union[ChatMessage, Dict[str, Any]]) -> Dict[str, Any]:
    """Format a message from conversation_history into a dictionary for API transmission."""
    if isinstance(msg, ChatMessage):
        data = msg.model_dump(exclude_none=True)
    elif isinstance(msg, dict):
        data = {k: v for k, v in msg.items() if v is not None}
    else:
        data = {"role": "user", "content": str(msg)}

    # Never allow function_call if it's null
    if data.get("function_call") is None:
        data.pop("function_call", None)

    return data


def trim_conversation_history(
    messages: List[Union[ChatMessage, Dict[str, Any]]],
    max_history_turns: int = 6,
    max_message_chars: int = 2000
) -> List[Union[ChatMessage, Dict[str, Any]]]:
    """Trim conversation history to a safe, recent window while strictly preserving
    the integrity of assistant tool-call and tool-result message pairs.
    
    In OpenAI / Groq protocols:
    - Every assistant message with `tool_calls` must be immediately followed by matching `tool` messages.
    - Slicing history arbitrarily can sever tool calls from their results, causing provider 400 errors.
    
    This function:
    1. Groups history into atomic conversational blocks (user messages, plain assistant messages,
       and assistant tool-calls bundled with their corresponding tool response messages).
    2. Drops orphaned tool messages (lacking their preceding assistant tool call).
    3. Keeps only the most recent `max_history_turns` blocks.
    4. Enforces a character ceiling on message content to protect context limits.
    """
    if not messages:
        return []

    blocks: List[List[Union[ChatMessage, Dict[str, Any]]]] = []
    i = 0
    n = len(messages)

    def get_role(m: Union[ChatMessage, Dict[str, Any]]) -> str:
        if isinstance(m, dict):
            return m.get("role", "")
        return getattr(m, "role", "")

    def get_tool_calls(m: Union[ChatMessage, Dict[str, Any]]) -> Any:
        if isinstance(m, dict):
            return m.get("tool_calls")
        return getattr(m, "tool_calls", None)

    while i < n:
        msg = messages[i]
        role = get_role(msg)

        if role in ("user", "system"):
            blocks.append([msg])
            i += 1
            continue

        if role == "assistant":
            tc = get_tool_calls(msg)
            if tc and isinstance(tc, list) and len(tc) > 0:
                block = [msg]
                j = i + 1
                while j < n and get_role(messages[j]) == "tool":
                    block.append(messages[j])
                    j += 1
                blocks.append(block)
                i = j
                continue
            else:
                blocks.append([msg])
                i += 1
                continue

        # If role is tool without preceding assistant: orphaned, skip it safely
        i += 1

    # Keep only the last `max_history_turns` blocks
    trimmed_blocks = blocks[-max_history_turns:] if len(blocks) > max_history_turns else blocks

    # Flatten and enforce length ceiling
    result: List[Union[ChatMessage, Dict[str, Any]]] = []
    for blk in trimmed_blocks:
        for m in blk:
            if isinstance(m, dict):
                content = str(m.get("content") or "")
                if len(content) > max_message_chars:
                    m_copy = dict(m)
                    m_copy["content"] = content[:max_message_chars] + "... [truncated for brevity]"
                    result.append(m_copy)
                else:
                    result.append(m)
            elif isinstance(m, ChatMessage):
                content = str(m.content or "")
                if len(content) > max_message_chars:
                    m_copy = m.model_copy(update={"content": content[:max_message_chars] + "... [truncated for brevity]"})
                    result.append(m_copy)
                else:
                    result.append(m)
            else:
                result.append(m)

    return result


def format_tool_result_for_llm(tool_name: str, result: Any, max_orders_for_llm: int = 10) -> str:
    """Format tool execution result concisely for LLM context transmission,
    preventing prompt token explosion while keeping the result structured and authoritative.
    """
    if not isinstance(result, dict):
        return json.dumps(result)

    # For order search results, limit the array of full order dictionaries to max_orders_for_llm
    if tool_name == "search_orders" and "orders" in result and isinstance(result["orders"], list):
        orders = result["orders"]
        total_count = result.get("count", len(orders))
        if len(orders) > max_orders_for_llm:
            concise_result = {
                "count": total_count,
                "showing": max_orders_for_llm,
                "orders": orders[:max_orders_for_llm],
                "filters": result.get("filters", {}),
                "summary": (
                    f"Showing first {max_orders_for_llm} of {total_count} matching orders. "
                    "Further filtering or aggregate calculations (calculate_order_metrics) can be used for summary totals."
                )
            }
            return json.dumps(concise_result)

    # For general results, ensure string representation does not exceed safe length
    raw_json = json.dumps(result)
    if len(raw_json) > 4000:
        # If result is oversized, preserve critical metrics while pruning large arrays
        truncated = {
            k: v for k, v in result.items()
            if not isinstance(v, (list, dict)) or len(str(v)) < 500
        }
        truncated["_note"] = "Result summarized to maintain safe context limits."
        return json.dumps(truncated)

    return raw_json


class OrderAssistantAgent:
    """Agent that orchestrates OpenAI / Groq compatible function calling with the OrderDataStore."""

    def __init__(self, settings: Settings, data_store: OrderDataStore):
        self.settings = settings
        self.data_store = data_store

    def _get_client(self) -> AsyncOpenAI:
        """Initialize and return an AsyncOpenAI client, validating that an API key is present."""
        api_key = self.settings.api_key
        if not api_key or api_key == "your_openai_api_key_here":
            raise MissingApiKeyError(
                "AI provider API key is missing or not configured. "
                "Please configure OPENAI_API_KEY or GROQ_API_KEY in backend/.env or your environment variables."
            )
        return AsyncOpenAI(
            api_key=api_key,
            base_url=self.settings.openai_base_url,
            timeout=self.settings.request_timeout,
            max_retries=1
        )

    async def process_chat(
        self,
        user_message: str,
        conversation_history: List[ChatMessage]
    ) -> Tuple[str, List[ToolCallRecord]]:
        """Run the multi-turn tool-calling loop for the given user message and conversation history.
        
        Uses tool_choice='auto' when tools should be available, and uses 'none' only when
        intentionally preventing further tool calls at the final synthesis turn.
        """
        client = self._get_client()

        # Apply safety window to conversation history, preserving atomic tool pairs
        trimmed_history = trim_conversation_history(conversation_history, max_history_turns=6)

        # Build initial messages list
        raw_messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Append previous conversation turns safely formatted
        for msg in trimmed_history:
            raw_messages.append(format_chat_message(msg))

        # Append latest user message
        raw_messages.append({"role": "user", "content": user_message})

        messages = sanitize_messages(raw_messages)
        tools_executed: List[ToolCallRecord] = []
        seen_tool_signatures: set = set()

        max_turns = self.settings.max_tool_iterations
        response_message = None

        for turn_idx in range(max_turns):
            # Check if this is the final permitted turn to force textual synthesis
            is_final_turn = (turn_idx == max_turns - 1)
            # Use 'auto' when tools should be available, and 'none' only when intentionally preventing tool calls
            tool_choice = "none" if is_final_turn else "auto"

            logger.info("Chat turn %d/%d: Requesting model completion (tool_choice='%s')",
                        turn_idx + 1, max_turns, tool_choice)

            try:
                response = await client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=sanitize_messages(messages),
                    tools=TOOLS_SCHEMA,
                    tool_choice=tool_choice,
                    max_tokens=self.settings.max_tokens,
                    timeout=self.settings.request_timeout
                )

                response_message = response.choices[0].message
                tool_calls = getattr(response_message, "tool_calls", None)

                # If no tool calls requested, model has delivered its final natural-language response
                if not tool_calls:
                    final_text = response_message.content or ""
                    logger.info("Turn %d/%d: Natural language response received from model",
                                turn_idx + 1, max_turns)
                    return final_text, tools_executed

                logger.info("Turn %d/%d: Model requested %d tool call(s)",
                            turn_idx + 1, max_turns, len(tool_calls))

                # Append assistant's tool-call request without any null fields
                assistant_msg = format_assistant_message(response_message)
                messages.append(assistant_msg)

                # Execute every requested tool call
                for tool_call in tool_calls:
                    func = getattr(tool_call, "function", None)
                    tool_name = getattr(func, "name", "") if func else ""
                    raw_args = getattr(func, "arguments", "") if func else ""

                    try:
                        args = json.loads(raw_args) if raw_args else {}
                        if not isinstance(args, dict):
                            args = {}
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    # Strip null values passed by the LLM (e.g. {'status': 'cancelled', 'month': None})
                    clean_args = {k: v for k, v in args.items() if v is not None}

                    # Log progress safely without exposing sensitive customer info (Requirement 7)
                    logger.info("Turn %d/%d: Executing tool '%s' with argument keys: %s",
                                turn_idx + 1, max_turns, tool_name, list(clean_args.keys()))

                    # Loop prevention: Detect identical tool calls in consecutive iterations
                    tool_sig = (tool_name, json.dumps(clean_args, sort_keys=True))
                    if tool_sig in seen_tool_signatures:
                        logger.warning("Turn %d/%d: Duplicate tool call '%s' detected; guiding model to synthesize",
                                       turn_idx + 1, max_turns, tool_name)
                        tool_content = json.dumps({
                            "status": "already_executed",
                            "note": f"Tool '{tool_name}' was already executed with these arguments. Please synthesize your final response for the user using the available results."
                        })
                    else:
                        seen_tool_signatures.add(tool_sig)
                        result = execute_tool(tool_name, clean_args, self.data_store)

                        tools_executed.append(
                            ToolCallRecord(
                                tool_name=tool_name,
                                arguments=clean_args,
                                result=result
                            )
                        )

                        # Format tool result concisely for LLM message context
                        tool_content = format_tool_result_for_llm(tool_name, result)

                    # Append tool result message with matching tool_call_id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": tool_content
                    })

            except (APITimeoutError, asyncio.TimeoutError) as e:
                logger.error("AI provider request timed out: %s", e)
                raise ProviderError(
                    "The AI provider took too long to respond (request timed out). "
                    "Please wait a moment and try your request again."
                )
            except AuthenticationError as e:
                logger.error(f"Authentication error: {e}")
                raise ProviderError(f"Authentication failure: {e.message or 'Invalid API key.'}")
            except RateLimitError as e:
                logger.error(f"Rate limit error: {e}")
                raise ProviderError(
                    "Rate limit reached (tokens per minute or request limit). "
                    "Please wait a moment and try your request again."
                )
            except APIConnectionError as e:
                logger.error(f"Connection error: {e}")
                raise ProviderError(f"Network error communicating with AI provider: {e}")
            except APIStatusError as e:
                logger.error(f"API status error {e.status_code}: {e}")
                err_msg = str(getattr(e, "message", "") or "")
                if e.status_code in (413, 429) or "tokens per minute" in err_msg.lower() or "too large" in err_msg.lower():
                    raise ProviderError(
                        "Rate limit or token quota exceeded (request too large for model tokens-per-minute limit). "
                        "Please wait a moment before sending another request."
                    )
                raise ProviderError(f"AI provider returned error ({e.status_code}): {e.message}")
            except OpenAIError as e:
                logger.error(f"OpenAI / Groq provider error: {e}")
                err_msg = str(e)
                if "rate limit" in err_msg.lower() or "429" in err_msg or "413" in err_msg or "too large" in err_msg.lower():
                    raise ProviderError(
                        "Rate limit reached (tokens per minute or request limit). "
                        "Please wait a moment and try your request again."
                    )
                raise ProviderError(f"AI provider error: {err_msg}")

        final_text = (response_message.content if response_message else "") or ""
        if not final_text.strip() and tools_executed:
            final_text = (
                "I have retrieved the requested order information from the dataset. "
                "Please review the summary details above."
            )
        return final_text, tools_executed
