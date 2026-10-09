import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from openai import AuthenticationError, RateLimitError, APIStatusError, APITimeoutError

from app.config import Settings
from app.data_store import OrderDataStore
from app.models import ChatMessage
from app.agent import (
    OrderAssistantAgent,
    format_assistant_message,
    trim_conversation_history,
    format_tool_result_for_llm,
)
import app.main as main_module


def test_health_check(client: TestClient):
    """Test health check returns healthy status and loaded order count (60)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["orders_count"] == 60


def test_chat_empty_message(client: TestClient):
    """Test chat endpoint rejects empty or whitespace-only messages with 422."""
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 422
    data = response.json()
    assert data["error_type"] == "VALIDATION_ERROR"
    assert "empty" in data["detail"].lower()


def test_chat_missing_message_field(client: TestClient):
    """Test chat endpoint rejects requests missing the required message field."""
    response = client.post("/api/chat", json={})
    assert response.status_code == 422
    data = response.json()
    assert data["error_type"] == "VALIDATION_ERROR"


def test_chat_excessively_long_message(client: TestClient):
    """Test chat endpoint rejects excessively long messages (> 2000 chars) with 422."""
    long_msg = "A" * 2001
    response = client.post("/api/chat", json={"message": long_msg})
    assert response.status_code == 422
    data = response.json()
    assert data["error_type"] == "VALIDATION_ERROR"
    assert "2000" in data["detail"]


def test_chat_missing_api_key(data_store: OrderDataStore):
    """Test chat endpoint returns 503 MISSING_API_KEY when no API key is configured."""
    unconfigured_settings = Settings(
        openai_api_key="",
        groq_api_key="",
        data_path=str(data_store.data_path)
    )
    main_module.data_store = data_store
    main_module.agent = OrderAssistantAgent(settings=unconfigured_settings, data_store=data_store)

    test_client = TestClient(main_module.app)
    response = test_client.post("/api/chat", json={"message": "What is the status of ORD-1001?"})
    assert response.status_code == 503
    data = response.json()
    assert data["error_type"] == "MISSING_API_KEY"
    assert "API_KEY" in data["detail"]


def test_chat_provider_authentication_failure(data_store: OrderDataStore):
    """Test chat endpoint returns 502 PROVIDER_ERROR when provider returns 401."""
    settings = Settings(
        openai_api_key="invalid-api-key",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_completions = AsyncMock()

        error_response = MagicMock(status_code=401)
        mock_completions.create.side_effect = AuthenticationError(
            message="Incorrect API key provided.",
            response=error_response,
            body={"error": {"message": "Incorrect API key provided."}}
        )
        mock_client.chat.completions = mock_completions
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Check order ORD-1001"})
        assert response.status_code == 502
        data = response.json()
        assert data["error_type"] == "PROVIDER_ERROR"
        assert "Authentication" in data["detail"]


def test_chat_provider_rate_limit(data_store: OrderDataStore):
    """Test chat endpoint returns 502 PROVIDER_ERROR on provider rate limits."""
    settings = Settings(
        openai_api_key="valid-looking-key",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_completions = AsyncMock()
        mock_completions.create.side_effect = RateLimitError(
            message="Rate limit reached.",
            response=MagicMock(status_code=429),
            body={"error": {"message": "Rate limit reached."}}
        )
        mock_client.chat.completions = mock_completions
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Total revenue?"})
        assert response.status_code == 502
        data = response.json()
        assert data["error_type"] == "PROVIDER_ERROR"
        assert "Rate limit" in data["detail"]


def test_format_assistant_message_excludes_function_call_and_nulls():
    """Verify format_assistant_message strictly never includes function_call: null
    or any other nullable fields that cause Groq API errors.
    """
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_xyz123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "get_order_details"
    mock_tool_call.function.arguments = '{"order_id": "ORD-1001"}'

    # Simulate an OpenAI ChatCompletionMessage with null fields
    raw_message = MagicMock()
    raw_message.role = "assistant"
    raw_message.content = None
    raw_message.function_call = None
    raw_message.refusal = None
    raw_message.audio = None
    raw_message.tool_calls = [mock_tool_call]

    formatted = format_assistant_message(raw_message)

    assert formatted["role"] == "assistant"
    assert "tool_calls" in formatted
    assert len(formatted["tool_calls"]) == 1
    assert formatted["tool_calls"][0]["id"] == "call_xyz123"
    assert formatted["tool_calls"][0]["function"]["name"] == "get_order_details"

    # Crucial Groq compatibility checks
    assert "function_call" not in formatted
    assert "content" not in formatted
    assert "refusal" not in formatted
    assert "audio" not in formatted
    for k, v in formatted.items():
        assert v is not None, f"Key '{k}' must not be null in assistant message"


def test_format_assistant_message_with_content():
    """Verify that non-empty content is preserved while omitting function_call."""
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_abc"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "calculate_order_metrics"
    mock_tool_call.function.arguments = "{}"

    raw_message = MagicMock()
    raw_message.role = "assistant"
    raw_message.content = "Checking database metrics now..."
    raw_message.function_call = None
    raw_message.tool_calls = [mock_tool_call]

    formatted = format_assistant_message(raw_message)

    assert formatted["role"] == "assistant"
    assert formatted["content"] == "Checking database metrics now..."
    assert "tool_calls" in formatted
    assert "function_call" not in formatted


def test_format_assistant_message_empty_or_null_tool_calls():
    """Verify that assistant messages with missing or null tool_calls are handled safely."""
    raw_message = MagicMock()
    raw_message.role = "assistant"
    raw_message.content = "Direct answer without tools."
    raw_message.function_call = None
    raw_message.tool_calls = None

    formatted = format_assistant_message(raw_message)

    assert formatted["role"] == "assistant"
    assert formatted["content"] == "Direct answer without tools."
    assert "tool_calls" not in formatted
    assert "function_call" not in formatted


def test_chat_tool_calling_execution_flow(data_store: OrderDataStore):
    """Test end-to-end chat flow when LLM invokes get_order_details tool with actual schema."""
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_abc123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "get_order_details"
    mock_tool_call.function.arguments = json.dumps({"order_id": "ORD-1001"})

    mock_msg_with_tool = MagicMock()
    mock_msg_with_tool.role = "assistant"
    mock_msg_with_tool.tool_calls = [mock_tool_call]
    mock_msg_with_tool.content = None
    mock_msg_with_tool.function_call = None

    mock_response_1 = MagicMock()
    mock_response_1.choices = [MagicMock(message=mock_msg_with_tool)]

    mock_msg_final = MagicMock()
    mock_msg_final.role = "assistant"
    mock_msg_final.tool_calls = None
    mock_msg_final.content = "Order ORD-1001 was delivered to Rahul Sharma in Hyderabad for ₹1598 (Wireless Mouse)."
    mock_response_2 = MagicMock()
    mock_response_2.choices = [MagicMock(message=mock_msg_final)]

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_completions = AsyncMock()
        mock_completions.create.side_effect = [mock_response_1, mock_response_2]
        mock_client.chat.completions = mock_completions
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Where is my order ORD-1001?"})
        assert response.status_code == 200
        data = response.json()
        assert "Rahul Sharma" in data["reply"]
        assert len(data["tools_used"]) == 1
        tool_used = data["tools_used"][0]
        assert tool_used["tool_name"] == "get_order_details"
        assert tool_used["arguments"] == {"order_id": "ORD-1001"}
        assert tool_used["result"]["found"] is True
        assert tool_used["result"]["order"]["order_id"] == "ORD-1001"
        assert tool_used["result"]["order"]["product"] == "Wireless Mouse"
        assert tool_used["result"]["order"]["total_inr"] == 1598.0

        # Verify that messages sent on turn 2 does NOT contain function_call: null
        call_args_turn_2 = mock_completions.create.call_args_list[1]
        sent_messages = call_args_turn_2.kwargs["messages"]
        assistant_turn = next(m for m in sent_messages if m["role"] == "assistant")
        assert "function_call" not in assistant_turn
        assert "tool_calls" in assistant_turn


def test_chat_with_conversation_history_compatibility(data_store: OrderDataStore):
    """Test multi-turn conversation history is formatted cleanly without invalid fields."""
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_msg_final = MagicMock()
    mock_msg_final.role = "assistant"
    mock_msg_final.tool_calls = None
    mock_msg_final.content = "You're welcome!"
    mock_response = MagicMock(choices=[MagicMock(message=mock_msg_final)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I assist you with orders?"},
            {"role": "user", "content": "Thank you"}
        ]

        test_client = TestClient(main_module.app)
        response = test_client.post(
            "/api/chat",
            json={"message": "Have a great day", "conversation_history": history}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "You're welcome!"

        # Verify messages sent to client
        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert len(sent_messages) == 5  # system + 3 history + 1 new user message
        for m in sent_messages:
            assert "role" in m
            assert "content" in m
            assert "function_call" not in m


def test_chat_handles_tool_call_with_null_arguments(data_store: OrderDataStore):
    """Test that when Groq/OpenAI passes null arguments (e.g. {'category': None}),
    the agent cleans them and executes successfully.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_metrics_1"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "calculate_order_metrics"
    # Arguments with null values generated by open models on Groq
    mock_tool_call.function.arguments = json.dumps({
        "status": None,
        "category": None,
        "customer": None,
        "city": None,
        "month": None
    })

    mock_msg_turn1 = MagicMock(role="assistant", tool_calls=[mock_tool_call], content=None, function_call=None)
    mock_res1 = MagicMock(choices=[MagicMock(message=mock_msg_turn1)])

    mock_msg_turn2 = MagicMock(role="assistant", tool_calls=None, content="Total orders: 60, Net revenue: ₹397,678.")
    mock_res2 = MagicMock(choices=[MagicMock(message=mock_msg_turn2)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_completions = AsyncMock()
        mock_completions.create.side_effect = [mock_res1, mock_res2]
        mock_client.chat.completions = mock_completions
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Show metrics"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools_used"]) == 1
        assert data["tools_used"][0]["tool_name"] == "calculate_order_metrics"
        # Null values must have been stripped from arguments
        assert data["tools_used"][0]["arguments"] == {}
        assert data["tools_used"][0]["result"]["total_orders"] == 60


def test_cors_headers_configured(client: TestClient):
    """Test CORS headers are returned for allowed origins."""
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_sanitize_messages_strips_null_function_call_and_nullable_fields():
    """Verify that sanitize_messages strips function_call: None and any nullable fields
    from conversation messages, directly preventing Groq error 400.
    """
    from app.agent import sanitize_messages

    dirty_messages = [
        {"role": "system", "content": "You are an assistant.", "function_call": None},
        {"role": "user", "content": "Check order ORD-1001", "refusal": None},
        {
            "role": "assistant",
            "content": None,
            "function_call": None,
            "audio": None,
            "refusal": None,
            "tool_calls": [
                {
                    "id": "call_99",
                    "type": "function",
                    "function": {"name": "get_order_details", "arguments": '{"order_id":"ORD-1001"}'}
                }
            ]
        },
        {"role": "tool", "tool_call_id": "call_99", "name": "get_order_details", "content": "{}", "function_call": None},
        {"role": "assistant", "content": None, "function_call": None}
    ]

    cleaned = sanitize_messages(dirty_messages)
    assert len(cleaned) == 5

    for msg in cleaned:
        # Crucial check: function_call must never be null/None
        assert "function_call" not in msg
        assert "refusal" not in msg
        assert "audio" not in msg
        for k, v in msg.items():
            assert v is not None, f"Field '{k}' was unexpectedly None in message: {msg}"

    # Assistant with tool_calls should have tool_calls
    asst_tool_call = cleaned[2]
    assert "tool_calls" in asst_tool_call
    assert asst_tool_call["tool_calls"][0]["id"] == "call_99"

    # Tool turn should have matching tool_call_id
    tool_turn = cleaned[3]
    assert tool_turn["role"] == "tool"
    assert tool_turn["tool_call_id"] == "call_99"

    # Assistant without tool_calls should have non-null string content
    asst_no_tools = cleaned[4]
    assert asst_no_tools["role"] == "assistant"
    assert isinstance(asst_no_tools["content"], str)


def test_conversation_history_with_tool_turns_and_tool_call_id(data_store: OrderDataStore):
    """Verify conversation_history containing user, assistant with tool_calls, and tool turns
    is parsed and forwarded with matching tool_call_id and no function_call: null.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_msg_final = MagicMock(role="assistant", tool_calls=None, content="Status is delivered.")
    mock_response = MagicMock(choices=[MagicMock(message=mock_msg_final)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "content": "Status of ORD-1001?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_hist_1",
                        "type": "function",
                        "function": {"name": "get_order_details", "arguments": '{"order_id": "ORD-1001"}'}
                    }
                ],
                "function_call": None  # Potential incoming null field
            },
            {
                "role": "tool",
                "tool_call_id": "call_hist_1",
                "content": '{"found": true, "status": "delivered"}'
            },
            {"role": "assistant", "content": "Order ORD-1001 is delivered."}
        ]

        test_client = TestClient(main_module.app)
        response = test_client.post(
            "/api/chat",
            json={"message": "What about payment method?", "conversation_history": history}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Status is delivered."

        # Verify messages forwarded to LLM client
        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        # System + 4 history items + 1 current message = 6
        assert len(sent_messages) == 6

        # Check tool turn has tool_call_id matching assistant's tool call id
        asst_msg = sent_messages[2]
        tool_msg = sent_messages[3]
        assert asst_msg["role"] == "assistant"
        assert asst_msg["tool_calls"][0]["id"] == "call_hist_1"
        assert "function_call" not in asst_msg

        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_hist_1"
        assert "function_call" not in tool_msg


def test_chat_tool_calling_flow_calculate_order_metrics_cancelled(data_store: OrderDataStore):
    """Test the complete tool calling flow for calculate_order_metrics with status=cancelled,
    verifying tool_choice='auto' on all active turns, correct tool results, and revenue calculations.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    # Turn 1: Model requests calculate_order_metrics with status="cancelled"
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_metrics_cancelled_1"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "calculate_order_metrics"
    mock_tool_call.function.arguments = json.dumps({"status": "cancelled"})

    mock_msg_turn1 = MagicMock(role="assistant", tool_calls=[mock_tool_call], content=None)
    mock_res_turn1 = MagicMock(choices=[MagicMock(message=mock_msg_turn1)])

    # Turn 2: Model synthesizes final text answer
    mock_msg_turn2 = MagicMock(
        role="assistant",
        tool_calls=None,
        content="There are 7 cancelled orders totaling ₹72,634.00 in cancelled revenue."
    )
    mock_res_turn2 = MagicMock(choices=[MagicMock(message=mock_msg_turn2)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[mock_res_turn1, mock_res_turn2])
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post(
            "/api/chat",
            json={"message": "How many orders were cancelled and what is the lost revenue?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "7 cancelled orders" in data["reply"]
        assert len(data["tools_used"]) == 1

        tool_record = data["tools_used"][0]
        assert tool_record["tool_name"] == "calculate_order_metrics"
        assert tool_record["arguments"] == {"status": "cancelled"}
        assert tool_record["result"]["cancelled_orders"] == 7
        assert tool_record["result"]["cancelled_revenue_inr"] == 72634.0

        # Verify tool_choice='auto' was passed on both calls (tools available on both turns)
        calls = mock_client.chat.completions.create.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["tool_choice"] == "auto"
        assert calls[1].kwargs["tool_choice"] == "auto"

        # Verify tool result was sent with matching tool_call_id
        turn2_messages = calls[1].kwargs["messages"]
        tool_msg = next(m for m in turn2_messages if m.get("role") == "tool")
        assert tool_msg["tool_call_id"] == "call_metrics_cancelled_1"
        assert "function_call" not in tool_msg


def test_chat_multi_step_tool_sequence_cancelled_orders(data_store: OrderDataStore):
    """Test multi-step tool sequence where model calls search_orders first,
    then calculate_order_metrics, then delivers final text answer.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    # Turn 1: Call search_orders
    tc_search = MagicMock(id="call_s1", type="function")
    tc_search.function.name = "search_orders"
    tc_search.function.arguments = json.dumps({"status": "cancelled"})
    res1 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=[tc_search], content=None))])

    # Turn 2: Call calculate_order_metrics
    tc_metrics = MagicMock(id="call_m1", type="function")
    tc_metrics.function.name = "calculate_order_metrics"
    tc_metrics.function.arguments = json.dumps({"status": "cancelled"})
    res2 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=[tc_metrics], content=None))])

    # Turn 3: Final answer
    res3 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=None, content="Summary of 7 cancelled orders."))])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[res1, res2, res3])
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post(
            "/api/chat",
            json={"message": "List and calculate all cancelled orders."}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["tools_used"]) == 2
        assert data["tools_used"][0]["tool_name"] == "search_orders"
        assert data["tools_used"][1]["tool_name"] == "calculate_order_metrics"

        # All intermediate turns must provide tool_choice='auto'
        calls = mock_client.chat.completions.create.call_args_list
        assert len(calls) == 3
        assert calls[0].kwargs["tool_choice"] == "auto"
        assert calls[1].kwargs["tool_choice"] == "auto"
        assert calls[2].kwargs["tool_choice"] == "auto"


def test_chat_final_turn_intentionally_sets_tool_choice_none(data_store: OrderDataStore):
    """Test that tool_choice='none' is only used on the final permitted turn
    to intentionally prevent infinite tool-calling loops.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    # Construct 4 tool call responses, followed by a 5th forced final text turn
    tc = MagicMock(id="call_rep", type="function")
    tc.function.name = "calculate_order_metrics"
    tc.function.arguments = "{}"

    res_tool = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=[tc], content=None))])
    res_final = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=None, content="Final forced summary."))])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        # 4 turns of tool calls, then 5th turn returns text
        mock_client.chat.completions.create = AsyncMock(side_effect=[res_tool, res_tool, res_tool, res_tool, res_final])
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Calculate metrics"})

        assert response.status_code == 200
        calls = mock_client.chat.completions.create.call_args_list
        assert len(calls) == 5

        # Turns 1-4 should have tool_choice='auto'
        for i in range(4):
            assert calls[i].kwargs["tool_choice"] == "auto"

        # Turn 5 (final turn, index 4) intentionally uses tool_choice='none'
        assert calls[4].kwargs["tool_choice"] == "none"


def test_chat_delivered_revenue_and_cancelled_orders_flow(data_store: OrderDataStore):
    """Test full chat API flow for calculating both delivered-order revenue and cancelled-order counts."""
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    # Turn 1: Model calls calculate_order_metrics without status filter
    mock_tc = MagicMock(id="call_deliv_canc_1", type="function")
    mock_tc.function.name = "calculate_order_metrics"
    mock_tc.function.arguments = json.dumps({})

    mock_msg_turn1 = MagicMock(role="assistant", tool_calls=[mock_tc], content=None)
    mock_res_turn1 = MagicMock(choices=[MagicMock(message=mock_msg_turn1)])

    # Turn 2: Model responds with authoritative metrics
    mock_msg_turn2 = MagicMock(
        role="assistant",
        tool_calls=None,
        content="Delivered orders generated ₹371,040.00 in revenue, and there are 7 cancelled orders totaling ₹72,634.00."
    )
    mock_res_turn2 = MagicMock(choices=[MagicMock(message=mock_msg_turn2)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[mock_res_turn1, mock_res_turn2])
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post(
            "/api/chat",
            json={"message": "What is the total revenue from delivered orders and the total number of cancelled orders?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["tools_used"]) == 1

        tool_exec = data["tools_used"][0]
        assert tool_exec["tool_name"] == "calculate_order_metrics"
        tool_result = tool_exec["result"]

        assert tool_result["delivered_orders"] == 48
        assert tool_result["delivered_revenue_inr"] == 371040.0
        assert tool_result["cancelled_orders"] == 7
        assert tool_result["cancelled_revenue_inr"] == 72634.0
        assert tool_result["net_revenue_inr"] == 397678.0
        assert tool_result["gross_revenue_inr"] == 470312.0

        assert "371,040" in data["reply"]
        assert "7 cancelled orders" in data["reply"]


def test_trim_conversation_history_bounds_and_preserves_atomic_tool_pairs():
    """Verify that trim_conversation_history:
    1. Keeps only the last max_history_turns blocks (e.g. 3 blocks for this test).
    2. Keeps assistant tool-calls strictly bundled with their matching tool responses.
    3. Safely drops orphaned tool messages lacking preceding assistant tool calls.
    """
    messages = [
        # Orphaned tool message at beginning
        {"role": "tool", "tool_call_id": "call_orphan", "content": "orphan result"},
        # Block 1: User message
        {"role": "user", "content": "Hello 1"},
        # Block 2: Assistant response
        {"role": "assistant", "content": "Hi 1"},
        # Block 3: User message
        {"role": "user", "content": "Lookup ORD-1001"},
        # Block 4: Assistant tool call + Tool result (atomic pair)
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_order_details", "arguments": "{}"}}]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"order_id": "ORD-1001"}'},
        # Block 5: Assistant final synthesis
        {"role": "assistant", "content": "Order ORD-1001 is delivered."},
        # Block 6: User message
        {"role": "user", "content": "Lookup ORD-1002"},
        # Block 7: Assistant tool call + Tool result (atomic pair)
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "get_order_details", "arguments": "{}"}}]
        },
        {"role": "tool", "tool_call_id": "call_2", "content": '{"order_id": "ORD-1002"}'},
    ]

    # Trim to 3 blocks
    trimmed = trim_conversation_history(messages, max_history_turns=3)

    # 3 blocks should be:
    # Block 5: Assistant ("Order ORD-1001 is delivered.")
    # Block 6: User ("Lookup ORD-1002")
    # Block 7: Assistant tool call + Tool result (2 messages)
    # Total messages = 1 + 1 + 2 = 4
    assert len(trimmed) == 4
    assert trimmed[0]["role"] == "assistant"
    assert trimmed[0]["content"] == "Order ORD-1001 is delivered."
    assert trimmed[1]["role"] == "user"
    assert trimmed[1]["content"] == "Lookup ORD-1002"
    assert trimmed[2]["role"] == "assistant"
    assert len(trimmed[2]["tool_calls"]) == 1
    assert trimmed[3]["role"] == "tool"
    assert trimmed[3]["tool_call_id"] == "call_2"


def test_trim_conversation_history_truncates_oversized_message():
    """Verify that trim_conversation_history truncates messages exceeding max_message_chars."""
    huge_text = "X" * 3000
    messages = [{"role": "user", "content": huge_text}]

    trimmed = trim_conversation_history(messages, max_history_turns=6, max_message_chars=500)
    assert len(trimmed) == 1
    content = trimmed[0]["content"]
    assert len(content) < 600
    assert "truncated for brevity" in content


def test_format_tool_result_for_llm_limits_large_order_lists():
    """Verify format_tool_result_for_llm limits search_orders lists to 10 items for LLM context,
    while preserving count metadata and filters.
    """
    sample_orders = [{"order_id": f"ORD-{1000 + i}", "product": "Item", "total_inr": 100} for i in range(48)]
    tool_result = {
        "count": 48,
        "orders": sample_orders,
        "filters": {"status": "delivered"}
    }

    formatted_json = format_tool_result_for_llm("search_orders", tool_result, max_orders_for_llm=10)
    parsed = json.loads(formatted_json)

    assert parsed["count"] == 48
    assert parsed["showing"] == 10
    assert len(parsed["orders"]) == 10
    assert "Showing first 10 of 48" in parsed["summary"]


def test_format_tool_result_for_llm_preserves_small_order_lists():
    """Verify format_tool_result_for_llm preserves order lists under limit in full."""
    sample_orders = [{"order_id": "ORD-1001", "product": "Mouse"}]
    tool_result = {
        "count": 1,
        "orders": sample_orders
    }

    formatted_json = format_tool_result_for_llm("search_orders", tool_result, max_orders_for_llm=10)
    parsed = json.loads(formatted_json)

    assert parsed["count"] == 1
    assert len(parsed["orders"]) == 1
    assert "showing" not in parsed


def test_chat_passes_max_tokens_to_completions(data_store: OrderDataStore):
    """Verify that chat completion explicitly passes max_tokens to prevent Groq from
    reserving 96,000 tokens and causing 413 rate limit exceeded errors.
    """
    settings = Settings(
        openai_api_key="sk-test",
        max_tokens=1024,
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_msg = MagicMock(role="assistant", tool_calls=None, content="Hello, I am ready to help.")
    mock_res = MagicMock(choices=[MagicMock(message=mock_msg)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_res)
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Hello"})

        assert response.status_code == 200
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1024


def test_chat_handles_413_payload_too_large_gracefully(data_store: OrderDataStore):
    """Verify that chat endpoint handles HTTP 413 / Request too large errors from Groq
    with a clear, user-friendly error message.
    """
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    error_response = MagicMock(status_code=413)
    api_error = APIStatusError(
        message="Request too large for model openai/gpt-oss-120b. Limit 8000 tokens per minute, Requested 96444.",
        response=error_response,
        body={"error": {"message": "Request too large for model openai/gpt-oss-120b. Limit 8000 tokens per minute, Requested 96444."}}
    )

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=api_error)
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Show all orders"})

        assert response.status_code == 502
        data = response.json()
        assert data["error_type"] == "PROVIDER_ERROR"
        assert "Rate limit or token quota exceeded" in data["detail"]


def test_chat_handles_api_timeout_error_gracefully(data_store: OrderDataStore):
    """Verify that chat endpoint handles provider APITimeoutError with a clear 502 error."""
    settings = Settings(
        openai_api_key="sk-test",
        request_timeout=10.0,
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=APITimeoutError(request=MagicMock())
        )
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Analyze orders"})

        assert response.status_code == 502
        data = response.json()
        assert data["error_type"] == "PROVIDER_ERROR"
        assert "timed out" in data["detail"].lower()


def test_chat_handles_overall_timeout_gracefully(data_store: OrderDataStore):
    """Verify that chat endpoint catches overall asyncio timeout and returns 502 PROVIDER_ERROR."""
    settings = Settings(
        openai_api_key="sk-test",
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    with patch.object(agent, "process_chat", side_effect=asyncio.TimeoutError()):
        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Calculate metrics"})

        assert response.status_code == 502
        data = response.json()
        assert data["error_type"] == "PROVIDER_ERROR"
        assert "timed out" in data["detail"].lower()


def test_chat_passes_timeout_parameter_to_create(data_store: OrderDataStore):
    """Verify that client.chat.completions.create is called with the configured timeout."""
    settings = Settings(
        openai_api_key="sk-test",
        request_timeout=25.0,
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    mock_msg = MagicMock(role="assistant", tool_calls=None, content="Response text")
    mock_res = MagicMock(choices=[MagicMock(message=mock_msg)])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_res)
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Hello"})

        assert response.status_code == 200
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["timeout"] == 25.0


def test_chat_detects_and_prevents_duplicate_tool_loops(data_store: OrderDataStore):
    """Verify that agent detects when a model attempts to call the exact same tool with identical
    arguments across turns, preventing infinite tool loops.
    """
    settings = Settings(
        openai_api_key="sk-test",
        max_tool_iterations=4,
        data_path=str(data_store.data_path)
    )
    agent = OrderAssistantAgent(settings=settings, data_store=data_store)
    main_module.data_store = data_store
    main_module.agent = agent

    # Turn 1: Call calculate_order_metrics with empty args
    tc1 = MagicMock(id="call_dup_1", type="function")
    tc1.function.name = "calculate_order_metrics"
    tc1.function.arguments = "{}"
    res1 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=[tc1], content=None))])

    # Turn 2: Attempt identical call again
    tc2 = MagicMock(id="call_dup_2", type="function")
    tc2.function.name = "calculate_order_metrics"
    tc2.function.arguments = "{}"
    res2 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=[tc2], content=None))])

    # Turn 3: Final synthesis
    res3 = MagicMock(choices=[MagicMock(message=MagicMock(role="assistant", tool_calls=None, content="Total orders: 60"))])

    with patch.object(agent, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[res1, res2, res3])
        mock_get_client.return_value = mock_client

        test_client = TestClient(main_module.app)
        response = test_client.post("/api/chat", json={"message": "Count total orders"})

        assert response.status_code == 200
        data = response.json()
        assert "Total orders: 60" in data["reply"]
        # The tool should only be executed once, not twice
        assert len(data["tools_used"]) == 1


def test_list_orders_endpoint(client: TestClient):
    """Test GET /api/orders retrieves all 60 orders and supports filtering."""
    # Unfiltered
    response = client.get("/api/orders")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 60
    assert data["count"] == 60
    assert len(data["orders"]) == 60

    # Filter by cancelled
    response_canc = client.get("/api/orders?status=cancelled")
    assert response_canc.status_code == 200
    data_canc = response_canc.json()
    assert data_canc["count"] == 7
    for o in data_canc["orders"]:
        assert o["status"] == "cancelled"

    # Filter by city
    response_city = client.get("/api/orders?city=Chennai")
    assert response_city.status_code == 200
    data_city = response_city.json()
    assert data_city["count"] > 0
    for o in data_city["orders"]:
        assert o["city"] == "Chennai"


def test_analytics_endpoint(client: TestClient):
    """Test GET /api/analytics returns authoritative dataset metrics."""
    response = client.get("/api/analytics")
    assert response.status_code == 200
    data = response.json()

    assert data["total_orders"] == 60
    assert data["delivered_orders"] == 48
    assert data["delivered_revenue_inr"] == 371040.0
    assert data["cancelled_orders"] == 7
    assert data["cancelled_revenue_inr"] == 72634.0
    assert data["net_revenue_inr"] == 397678.0
    assert data["gross_revenue_inr"] == 470312.0
    assert "highest_value_orders" in data
    assert len(data["highest_value_orders"]) == 5
    assert "status_breakdown" in data
    assert "category_breakdown" in data






