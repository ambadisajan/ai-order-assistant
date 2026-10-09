import pytest
from app.data_store import OrderDataStore
from app.tools import execute_tool


def test_orders_dataset_loaded_count(data_store: OrderDataStore):
    """Verify that all 60 orders from the supplied dataset load correctly."""
    assert len(data_store.orders) == 60


def test_get_order_details_success(data_store: OrderDataStore):
    """Test retrieving existing order details by ID matching the actual CSV schema."""
    result = execute_tool("get_order_details", {"order_id": "ORD-1001"}, data_store)
    assert result["found"] is True
    order = result["order"]
    assert order["order_id"] == "ORD-1001"
    assert order["order_date"] == "2026-06-01"
    assert order["customer_name"] == "Rahul Sharma"
    assert order["city"] == "Hyderabad"
    assert order["product"] == "Wireless Mouse"
    assert order["category"] == "Electronics"
    assert order["quantity"] == 2
    assert order["unit_price_inr"] == 799.0
    assert order["total_inr"] == 1598.0
    assert order["payment_method"] == "Debit Card"
    assert order["status"] == "delivered"


def test_get_order_details_case_insensitive(data_store: OrderDataStore):
    """Test order ID lookup handles lower and mixed case."""
    result = execute_tool("get_order_details", {"order_id": "ord-1001"}, data_store)
    assert result["found"] is True
    assert result["order"]["order_id"] == "ORD-1001"


def test_get_order_details_missing_order(data_store: OrderDataStore):
    """Test lookup of non-existent order ID returns found=False with clear diagnostic message."""
    result = execute_tool("get_order_details", {"order_id": "ORD-9999"}, data_store)
    assert result["found"] is False
    assert result["order_id"] == "ORD-9999"
    assert "not found" in result["message"].lower()


def test_get_order_details_empty_id(data_store: OrderDataStore):
    """Test lookup with empty order ID returns an error."""
    result = execute_tool("get_order_details", {"order_id": ""}, data_store)
    assert result["found"] is False
    assert "required" in result["error"].lower()


def test_search_orders_by_status(data_store: OrderDataStore):
    """Test filtering orders by status (delivered, cancelled, returned)."""
    # 7 cancelled orders in the dataset
    cancelled = execute_tool("search_orders", {"status": "cancelled"}, data_store)
    assert cancelled["count"] == 7
    for o in cancelled["orders"]:
        assert o["status"].lower() == "cancelled"

    # Case-insensitive status query
    cancelled_upper = execute_tool("search_orders", {"status": "Cancelled"}, data_store)
    assert cancelled_upper["count"] == 7

    # 48 delivered orders (specify limit=60)
    delivered = execute_tool("search_orders", {"status": "delivered", "limit": 60}, data_store)
    assert delivered["count"] == 48

    # 3 returned orders
    returned = execute_tool("search_orders", {"status": "returned"}, data_store)
    assert returned["count"] == 3


def test_search_orders_by_customer(data_store: OrderDataStore):
    """Test filtering orders by customer name substring."""
    result = execute_tool("search_orders", {"customer": "Rahul Sharma"}, data_store)
    assert result["count"] == 4
    for o in result["orders"]:
        assert "Rahul Sharma" in o["customer_name"]


def test_search_orders_by_category_and_city(data_store: OrderDataStore):
    """Test filtering orders by category and city."""
    result = execute_tool("search_orders", {"category": "Electronics", "city": "Chennai"}, data_store)
    assert result["count"] == 4
    for o in result["orders"]:
        assert o["category"].lower() == "electronics"
        assert o["city"].lower() == "chennai"


def test_search_orders_by_product(data_store: OrderDataStore):
    """Test filtering orders by product name substring."""
    result = execute_tool("search_orders", {"product": "Standing Desk"}, data_store)
    assert result["count"] == 4
    for o in result["orders"]:
        assert "standing desk" in o["product"].lower()


def test_search_orders_by_payment_method(data_store: OrderDataStore):
    """Test filtering orders by payment method."""
    result = execute_tool("search_orders", {"payment_method": "UPI"}, data_store)
    assert result["count"] == 15
    for o in result["orders"]:
        assert o["payment_method"].lower() == "upi"


def test_search_orders_by_month(data_store: OrderDataStore):
    """Test filtering orders by month in YYYY-MM format."""
    june = execute_tool("search_orders", {"month": "2026-06"}, data_store)
    assert june["count"] == 18

    july = execute_tool("search_orders", {"month": "2026-07"}, data_store)
    assert july["count"] == 14


def test_search_orders_empty_results_graceful(data_store: OrderDataStore):
    """Test that searches with no matching records return empty list gracefully."""
    result = execute_tool("search_orders", {"customer": "NonExistentPerson"}, data_store)
    assert result["count"] == 0
    assert result["orders"] == []


def test_calculate_order_metrics_overall(data_store: OrderDataStore):
    """Test total counts, cancellation counts, and revenue calculations in INR."""
    metrics = execute_tool("calculate_order_metrics", {}, data_store)

    assert metrics["total_orders"] == 60
    assert metrics["cancelled_orders"] == 7
    assert metrics["active_completed_orders"] == 53

    # Revenue checks in INR
    net_rev = metrics["net_revenue_inr"]
    gross_rev = metrics["gross_revenue_inr"]
    canc_rev = metrics["cancelled_revenue_inr"]

    assert gross_rev == 470312.0
    assert canc_rev == 72634.0
    assert net_rev == 397678.0
    assert round(net_rev + canc_rev, 2) == round(gross_rev, 2)


def test_calculate_order_metrics_category_revenue_by_month(data_store: OrderDataStore):
    """Test category revenue by month calculation on actual orders."""
    metrics = execute_tool("calculate_order_metrics", {}, data_store)
    cat_by_month = metrics["category_revenue_by_month"]

    assert "2026-06" in cat_by_month
    assert "2026-07" in cat_by_month
    assert "2026-08" in cat_by_month
    assert "2026-09" in cat_by_month

    # Verify June 2026 category breakdown for non-cancelled orders
    june_cats = cat_by_month["2026-06"]
    assert june_cats["Electronics"] == 3995.0
    assert june_cats["Accessories"] == 29281.0
    assert june_cats["Stationery"] == 2740.0
    assert june_cats["Furniture"] == 5196.0


def test_calculate_order_metrics_highest_spending_customer(data_store: OrderDataStore):
    """Test highest-spending customer identification and cancellation exclusion."""
    metrics = execute_tool("calculate_order_metrics", {}, data_store)

    highest = metrics["highest_spending_customer"]
    assert highest is not None
    assert highest["customer_name"] == "Rohan Das"
    assert highest["net_spend_inr"] == 112282.0

    # Vikram Reddy placed orders with cancellations; verify net spend excludes cancelled
    top_customers = metrics["top_customers_spending"]
    vikram = next((c for c in top_customers if c["customer_name"] == "Vikram Reddy"), None)
    assert vikram is not None
    assert vikram["cancelled_orders"] > 0
    assert vikram["net_spend_inr"] < vikram["gross_spend_inr"]
    assert vikram["net_spend_inr"] == 53888.0


def test_unknown_tool_handling(data_store: OrderDataStore):
    """Test executing an unknown tool returns an error message."""
    result = execute_tool("non_existent_tool", {}, data_store)
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_calculate_order_metrics_delivered_and_cancelled_orders(data_store: OrderDataStore):
    """Test delivered-order revenue and cancelled-order counts against the actual CSV dataset."""
    # Compute ground truth dynamically directly from the loaded orders list
    delivered_orders = [o for o in data_store.orders if o["status"].strip().lower() == "delivered"]
    cancelled_orders = [o for o in data_store.orders if o["status"].strip().lower() == "cancelled"]

    expected_delivered_count = len(delivered_orders)
    expected_cancelled_count = len(cancelled_orders)
    expected_delivered_rev = round(sum(float(o["total_inr"]) for o in delivered_orders), 2)
    expected_cancelled_rev = round(sum(float(o["total_inr"]) for o in cancelled_orders), 2)

    # ORD-1015 must be among the cancelled orders
    ord_1015 = next((o for o in cancelled_orders if o["order_id"] == "ORD-1015"), None)
    assert ord_1015 is not None, "ORD-1015 must be present in cancelled orders"
    assert ord_1015["customer_name"] == "Vikram Reddy"
    assert ord_1015["total_inr"] == 21999.0

    metrics = execute_tool("calculate_order_metrics", {}, data_store)

    assert metrics["delivered_orders"] == expected_delivered_count
    assert metrics["delivered_revenue_inr"] == expected_delivered_rev
    assert metrics["cancelled_orders"] == expected_cancelled_count
    assert metrics["cancelled_revenue_inr"] == expected_cancelled_rev

    # Status breakdowns
    assert metrics["status_breakdown"]["delivered"] == expected_delivered_count
    assert metrics["status_breakdown"]["cancelled"] == expected_cancelled_count
    assert metrics["status_revenue_breakdown"]["delivered"] == expected_delivered_rev
    assert metrics["status_revenue_breakdown"]["cancelled"] == expected_cancelled_rev


def test_status_normalization_and_whitespace_handling(data_store: OrderDataStore):
    """Test that search_orders and calculate_order_metrics handle variations in casing,
    whitespace, and spelling (such as 'canceled' vs 'cancelled').
    """
    # 1. Search orders with single 'l' 'canceled'
    res_single_l = execute_tool("search_orders", {"status": "canceled"}, data_store)
    assert res_single_l["count"] == 7
    order_ids = [o["order_id"] for o in res_single_l["orders"]]
    assert "ORD-1015" in order_ids

    # 2. Search orders with mixed case and whitespace
    res_whitespace = execute_tool("search_orders", {"status": "  Cancelled  "}, data_store)
    assert res_whitespace["count"] == 7

    res_upper = execute_tool("search_orders", {"status": "CANCELLED"}, data_store)
    assert res_upper["count"] == 7

    # 3. Delivered with whitespace and title case (specify limit=60 since default is 20)
    res_deliv_ws = execute_tool("search_orders", {"status": " Delivered ", "limit": 60}, data_store)
    assert res_deliv_ws["count"] == 48

    # 4. Metrics with 'canceled'
    metrics_canc = execute_tool("calculate_order_metrics", {"status": "canceled"}, data_store)
    assert metrics_canc["cancelled_orders"] == 7
    assert metrics_canc["total_orders"] == 7
    assert metrics_canc["cancelled_revenue_inr"] == 72634.0


def test_calculate_order_metrics_delivered_filter_and_dataset_summary(data_store: OrderDataStore):
    """Test that when filtering by status='delivered', delivered revenue is calculated
    and dataset_summary provides the overall dataset counts including cancelled orders.
    """
    metrics = execute_tool("calculate_order_metrics", {"status": "delivered"}, data_store)

    assert metrics["total_orders"] == 48
    assert metrics["delivered_orders"] == 48
    assert metrics["delivered_revenue_inr"] == 371040.0
    assert metrics["net_revenue_inr"] == 371040.0

    # dataset_summary guarantees visibility into overall dataset totals
    ds_summary = metrics["dataset_summary"]
    assert ds_summary["total_orders"] == 60
    assert ds_summary["cancelled_orders"] == 7
    assert ds_summary["cancelled_revenue_inr"] == 72634.0
    assert ds_summary["delivered_orders"] == 48
    assert ds_summary["delivered_revenue_inr"] == 371040.0
    assert ds_summary["net_revenue_inr"] == 397678.0
    assert ds_summary["gross_revenue_inr"] == 470312.0


def test_delivered_revenue_vs_net_revenue_relationship(data_store: OrderDataStore):
    """Verify mathematical consistency between delivered revenue, net revenue,
    cancelled revenue, and gross revenue.
    """
    metrics = execute_tool("calculate_order_metrics", {}, data_store)

    delivered_rev = metrics["delivered_revenue_inr"]
    net_rev = metrics["net_revenue_inr"]
    gross_rev = metrics["gross_revenue_inr"]
    canc_rev = metrics["cancelled_revenue_inr"]

    # Net revenue must include delivered plus returned, processing, shipped
    assert delivered_rev <= net_rev
    # Gross revenue must equal net revenue + cancelled revenue
    assert round(net_rev + canc_rev, 2) == round(gross_rev, 2)
    # Delivered revenue + other non-cancelled statuses equals net revenue
    other_active_rev = sum(
        rev for status, rev in metrics["status_revenue_breakdown"].items()
        if status not in ("delivered", "cancelled")
    )
    assert round(delivered_rev + other_active_rev, 2) == round(net_rev, 2)

