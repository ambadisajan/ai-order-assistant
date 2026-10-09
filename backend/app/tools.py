from typing import Any, Dict, List
from app.data_store import OrderDataStore

# Tool schemas defined using OpenAI-compatible function-calling format with Groq compatibility
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": (
                "Retrieve full details for a specific order by its order ID (e.g., 'ORD-1001'). "
                "Returns order_date, customer_name, city, product, category, quantity, unit_price_inr, "
                "total_inr, payment_method, and status. "
                "Use this whenever the user asks about a specific order, tracking, item, or status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique identifier of the order, such as ORD-1001."
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_orders",
            "description": (
                "Search and filter orders by status, customer name, category, city, "
                "product name, payment method, month, or date range. Returns a list of matching order records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": ["string", "null"],
                        "description": "Order status to filter by (e.g., 'delivered', 'cancelled', 'returned', 'processing', 'shipped')."
                    },
                    "customer": {
                        "type": ["string", "null"],
                        "description": "Customer name substring to search for (e.g., 'Rahul Sharma', 'Sneha Pillai')."
                    },
                    "category": {
                        "type": ["string", "null"],
                        "description": "Product category (e.g., 'Electronics', 'Accessories', 'Stationery', 'Furniture')."
                    },
                    "city": {
                        "type": ["string", "null"],
                        "description": "Delivery city name (e.g., 'Chennai', 'Thiruvananthapuram', 'Kochi', 'Hyderabad', 'Bengaluru', 'Pune')."
                    },
                    "product": {
                        "type": ["string", "null"],
                        "description": "Product name or keyword (e.g., 'Wireless Mouse', 'Standing Desk', 'Noise Cancelling Headphones')."
                    },
                    "payment_method": {
                        "type": ["string", "null"],
                        "description": "Payment method (e.g., 'UPI', 'Debit Card', 'Credit Card', 'Cash on Delivery', 'Net Banking')."
                    },
                    "month": {
                        "type": ["string", "null"],
                        "description": "Filter by month in YYYY-MM format (e.g., '2026-06', '2026-07', '2026-08', '2026-09')."
                    },
                    "start_date": {
                        "type": ["string", "null"],
                        "description": "Filter orders on or after this date in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": ["string", "null"],
                        "description": "Filter orders on or before this date in YYYY-MM-DD format."
                    },
                    "limit": {
                        "type": ["integer", "null"],
                        "description": "Maximum number of orders to return (default 20, max 60).",
                        "default": 20
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_order_metrics",
            "description": (
                "Calculate authoritative numerical metrics on orders from the dataset: "
                "total order count, delivered order count and delivered revenue in INR, cancellation count and cancelled revenue in INR, "
                "net revenue in INR, gross revenue in INR, category revenue by month, and customer spending. "
                "When answering questions regarding delivered revenue and/or cancelled orders across the dataset, omit the status filter "
                "to receive comprehensive metrics for all statuses in a single call. Net revenue excludes cancelled orders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": ["string", "null"],
                        "description": (
                            "Optional status to filter metrics by (e.g., 'delivered', 'cancelled'). "
                            "Leave empty/null to calculate metrics across all statuses including delivered revenue, "
                            "cancelled order counts, and status breakdowns."
                        )
                    },
                    "customer": {
                        "type": ["string", "null"],
                        "description": "Optional customer name substring to filter metrics by."
                    },
                    "category": {
                        "type": ["string", "null"],
                        "description": "Optional category to filter metrics by."
                    },
                    "city": {
                        "type": ["string", "null"],
                        "description": "Optional city to filter metrics by."
                    },
                    "payment_method": {
                        "type": ["string", "null"],
                        "description": "Optional payment method to filter metrics by."
                    },
                    "month": {
                        "type": ["string", "null"],
                        "description": "Optional month in YYYY-MM format (e.g., '2026-06', '2026-07')."
                    },
                    "start_date": {
                        "type": ["string", "null"],
                        "description": "Optional start date filter in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": ["string", "null"],
                        "description": "Optional end date filter in YYYY-MM-DD format."
                    }
                }
            }
        }
    }
]


def execute_tool(tool_name: str, arguments: Dict[str, Any], data_store: OrderDataStore) -> Dict[str, Any]:
    """Execute the designated tool function with provided arguments against the data store.
    
    Safely cleans arguments by stripping null values so that optional parameters omitted
    or set to null by LLMs do not cause type errors.
    """
    clean_args = (
        {k: v for k, v in arguments.items() if v is not None}
        if isinstance(arguments, dict)
        else {}
    )

    if tool_name == "get_order_details":
        order_id = str(clean_args.get("order_id", "")).strip()
        if not order_id:
            return {"found": False, "error": "Order ID parameter is required."}
        order = data_store.get_order_by_id(order_id)
        if order:
            return {"found": True, "order": order}
        else:
            return {
                "found": False,
                "order_id": order_id,
                "message": f"Order with ID '{order_id}' was not found in the database. Please verify the order ID."
            }

    elif tool_name == "search_orders":
        raw_limit = clean_args.get("limit", 20)
        try:
            limit = min(int(raw_limit), 60)
        except (ValueError, TypeError):
            limit = 20

        results = data_store.search_orders(
            status=clean_args.get("status"),
            customer=clean_args.get("customer"),
            category=clean_args.get("category"),
            city=clean_args.get("city"),
            product=clean_args.get("product"),
            payment_method=clean_args.get("payment_method"),
            month=clean_args.get("month"),
            start_date=clean_args.get("start_date"),
            end_date=clean_args.get("end_date"),
            limit=limit
        )
        return {
            "count": len(results),
            "orders": results,
            "filters": clean_args
        }

    elif tool_name == "calculate_order_metrics":
        metrics = data_store.calculate_order_metrics(
            status=clean_args.get("status"),
            customer=clean_args.get("customer"),
            category=clean_args.get("category"),
            city=clean_args.get("city"),
            payment_method=clean_args.get("payment_method"),
            month=clean_args.get("month"),
            start_date=clean_args.get("start_date"),
            end_date=clean_args.get("end_date")
        )
        return metrics

    else:
        return {"error": f"Unknown tool: '{tool_name}'"}
