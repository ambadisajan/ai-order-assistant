import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("order_assistant.data_store")


def normalize_status(status_val: Optional[str]) -> Optional[str]:
    """Normalize status string to lowercase canonical name, handling case, whitespace,
    and common variations (e.g. 'canceled' vs 'cancelled', 'cancelled orders', etc.).
    """
    if status_val is None:
        return None
    s = str(status_val).strip().lower()
    if not s or s in ("all", "any", "none", "*"):
        return None
    # Strip optional trailing 'orders' or 'order'
    if s.endswith(" orders"):
        s = s[:-7].strip()
    elif s.endswith(" order"):
        s = s[:-6].strip()

    if s in ("cancelled", "canceled", "cancellation", "cancellations"):
        return "cancelled"
    if s in ("delivered", "delivery"):
        return "delivered"
    if s in ("returned", "return", "returns"):
        return "returned"
    if s in ("processing", "process", "in progress"):
        return "processing"
    if s in ("shipped", "ship", "shipping", "in transit"):
        return "shipped"
    return s


def is_cancelled_status(status_val: Optional[str]) -> bool:
    """Check if the status represents a cancelled order."""
    return normalize_status(status_val) == "cancelled"


def is_delivered_status(status_val: Optional[str]) -> bool:
    """Check if the status represents a delivered order."""
    return normalize_status(status_val) == "delivered"


class OrderDataStore:
    """Manages loading and querying order data from orders.csv.
    
    All calculations are performed strictly in Python to guarantee numerical
    accuracy and prevent language model hallucinations.
    """

    def __init__(self, data_path: str = "data/orders.csv"):
        self.data_path = self._resolve_path(data_path)
        self.orders: List[Dict[str, Any]] = []
        self._load_data()

    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        """Resolve path whether relative to current working directory or backend root."""
        path = Path(path_str)
        if path.is_absolute() and path.exists():
            return path
        
        # Check current working directory
        if path.exists():
            return path.resolve()
        
        # Check relative to backend directory
        backend_dir = Path(__file__).resolve().parent.parent
        backend_rel = backend_dir / path_str
        if backend_rel.exists():
            return backend_rel.resolve()
        
        return path.resolve()

    def _load_data(self) -> None:
        """Load and parse orders from CSV file matching the Torcue technical screening schema:
        order_id, order_date, customer_name, city, product, category, quantity, unit_price_inr, total_inr, payment_method, status
        """
        if not self.data_path.exists():
            logger.error(f"Orders dataset not found at: {self.data_path}")
            self.orders = []
            return

        orders = []
        try:
            with open(self.data_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Parse row strictly according to the actual CSV schema
                    order_record = {
                        "order_id": row["order_id"].strip(),
                        "order_date": row["order_date"].strip(),
                        "customer_name": row["customer_name"].strip(),
                        "city": row["city"].strip(),
                        "product": row["product"].strip(),
                        "category": row["category"].strip(),
                        "quantity": int(row["quantity"].strip()),
                        "unit_price_inr": round(float(row["unit_price_inr"].strip()), 2),
                        "total_inr": round(float(row["total_inr"].strip()), 2),
                        "payment_method": row["payment_method"].strip(),
                        "status": row["status"].strip().lower()
                    }
                    orders.append(order_record)
            self.orders = orders
            logger.info(f"Successfully loaded {len(self.orders)} orders from {self.data_path}")
        except Exception as e:
            logger.error(f"Error loading CSV data from {self.data_path}: {e}")
            raise RuntimeError(f"Failed to load dataset: {e}")

    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Look up an order by order ID (case-insensitive)."""
        target_id = order_id.strip().upper()
        for order in self.orders:
            if order["order_id"].upper() == target_id:
                return dict(order)
        return None

    def search_orders(
        self,
        status: Optional[str] = None,
        customer: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        product: Optional[str] = None,
        payment_method: Optional[str] = None,
        month: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Filter orders by status, customer name, category, city, product, payment method, month, and date range."""
        results = []

        target_status = normalize_status(status)
        customer_lower = customer.strip().lower() if customer else None
        category_lower = category.strip().lower() if category else None
        city_lower = city.strip().lower() if city else None
        product_lower = product.strip().lower() if product else None
        payment_lower = payment_method.strip().lower() if payment_method else None
        month_str = month.strip() if month else None
        start_dt = start_date.strip() if start_date else None
        end_dt = end_date.strip() if end_date else None

        for order in self.orders:
            order_status = normalize_status(order["status"])
            if target_status and order_status != target_status:
                continue
            if customer_lower and customer_lower not in order["customer_name"].lower():
                continue
            if category_lower and category_lower not in order["category"].lower():
                continue
            if city_lower and city_lower not in order["city"].lower():
                continue
            if product_lower and product_lower not in order["product"].lower():
                continue
            if payment_lower and payment_lower not in order["payment_method"].lower():
                continue
            if month_str:
                # Support YYYY-MM or MM
                if not (order["order_date"].startswith(month_str) or order["order_date"][:7] == month_str):
                    continue
            if start_dt and order["order_date"] < start_dt:
                continue
            if end_dt and order["order_date"] > end_dt:
                continue

            results.append(dict(order))
            if len(results) >= limit:
                break

        return results

    def calculate_order_metrics(
        self,
        status: Optional[str] = None,
        customer: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        payment_method: Optional[str] = None,
        month: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calculate order counts, cancelled orders, delivered revenue, net revenue in INR,
        gross revenue in INR, category revenue by month, and customer spending breakdown.
        
        Revenue Treatment Policy:
        - Delivered Revenue (INR): Total revenue for orders with status 'delivered'.
        - Net Revenue (INR): Excludes cancelled orders (sums Delivered, Shipped, Processing, Returned).
        - Gross Revenue (INR): Total of all matching orders including cancelled.
        - Cancelled Orders & Cancelled Revenue (INR): Quantified and reported explicitly.
        - Customer Spending: Net spend per customer (excludes cancelled orders).
        - Category Revenue by Month: Grouped by order month (YYYY-MM) and category for active orders.
        """
        matched_orders = self.search_orders(
            status=status,
            customer=customer,
            category=category,
            city=city,
            payment_method=payment_method,
            month=month,
            start_date=start_date,
            end_date=end_date,
            limit=len(self.orders) + 1
        )

        total_orders = len(matched_orders)
        cancelled_orders = 0
        cancelled_revenue_inr = 0.0
        delivered_orders = 0
        delivered_revenue_inr = 0.0
        net_revenue_inr = 0.0
        gross_revenue_inr = 0.0

        status_breakdown: Dict[str, int] = defaultdict(int)
        status_revenue_breakdown: Dict[str, float] = defaultdict(float)
        category_breakdown: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "net_revenue_inr": 0.0}
        )
        payment_method_breakdown: Dict[str, int] = defaultdict(int)
        city_breakdown: Dict[str, int] = defaultdict(int)
        category_revenue_by_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        monthly_revenue: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "net_revenue_inr": 0.0,
                "gross_revenue_inr": 0.0,
                "orders_count": 0,
                "cancelled_orders": 0,
                "delivered_orders": 0,
                "delivered_revenue_inr": 0.0,
            }
        )
        customer_spending: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "net_spend_inr": 0.0,
                "gross_spend_inr": 0.0,
                "orders_count": 0,
                "cancelled_orders": 0,
                "delivered_orders": 0,
            }
        )

        for o in matched_orders:
            amt = float(o["total_inr"])
            raw_st = o["status"]
            st = normalize_status(raw_st) or raw_st.strip().lower()
            cust = o["customer_name"]
            cat = o["category"]
            ct = o["city"]
            pm = o["payment_method"]
            order_month = o["order_date"][:7]  # e.g., '2026-06'

            gross_revenue_inr += amt
            status_breakdown[st] += 1
            status_revenue_breakdown[st] = round(status_revenue_breakdown[st] + amt, 2)
            payment_method_breakdown[pm] += 1
            city_breakdown[ct] += 1
            monthly_revenue[order_month]["orders_count"] += 1
            monthly_revenue[order_month]["gross_revenue_inr"] = round(
                monthly_revenue[order_month]["gross_revenue_inr"] + amt, 2
            )

            customer_spending[cust]["orders_count"] += 1
            customer_spending[cust]["gross_spend_inr"] = round(
                customer_spending[cust]["gross_spend_inr"] + amt, 2
            )

            if is_cancelled_status(st):
                cancelled_orders += 1
                cancelled_revenue_inr += amt
                monthly_revenue[order_month]["cancelled_orders"] += 1
                customer_spending[cust]["cancelled_orders"] += 1
            else:
                net_revenue_inr += amt
                if is_delivered_status(st):
                    delivered_orders += 1
                    delivered_revenue_inr += amt
                    monthly_revenue[order_month]["delivered_orders"] += 1
                    monthly_revenue[order_month]["delivered_revenue_inr"] = round(
                        monthly_revenue[order_month]["delivered_revenue_inr"] + amt, 2
                    )
                    customer_spending[cust]["delivered_orders"] += 1

                category_breakdown[cat]["count"] += 1
                category_breakdown[cat]["net_revenue_inr"] = round(
                    category_breakdown[cat]["net_revenue_inr"] + amt, 2
                )
                category_revenue_by_month[order_month][cat] = round(
                    category_revenue_by_month[order_month][cat] + amt, 2
                )
                monthly_revenue[order_month]["net_revenue_inr"] = round(
                    monthly_revenue[order_month]["net_revenue_inr"] + amt, 2
                )
                customer_spending[cust]["net_spend_inr"] = round(
                    customer_spending[cust]["net_spend_inr"] + amt, 2
                )

        active_orders = total_orders - cancelled_orders
        avg_order_value = round(net_revenue_inr / active_orders, 2) if active_orders > 0 else 0.0

        # Sort customer spending by net_spend_inr descending
        sorted_customers = [
            {
                "customer_name": cust,
                "net_spend_inr": data["net_spend_inr"],
                "gross_spend_inr": data["gross_spend_inr"],
                "orders_count": data["orders_count"],
                "cancelled_orders": data["cancelled_orders"],
                "delivered_orders": data["delivered_orders"]
            }
            for cust, data in customer_spending.items()
        ]
        sorted_customers.sort(key=lambda x: x["net_spend_inr"], reverse=True)

        # Format category_revenue_by_month as sorted dictionary
        formatted_cat_rev_by_month = {
            m: dict(category_revenue_by_month[m])
            for m in sorted(category_revenue_by_month.keys())
        }

        # Format monthly_revenue as sorted dictionary
        formatted_monthly_revenue = {
            m: dict(monthly_revenue[m])
            for m in sorted(monthly_revenue.keys())
        }

        highest_spender = sorted_customers[0] if sorted_customers else None

        # Overall dataset baselines for full dataset visibility
        dataset_cancelled_count = sum(1 for o in self.orders if is_cancelled_status(o["status"]))
        dataset_cancelled_rev = round(
            sum(float(o["total_inr"]) for o in self.orders if is_cancelled_status(o["status"])), 2
        )
        dataset_delivered_count = sum(1 for o in self.orders if is_delivered_status(o["status"]))
        dataset_delivered_rev = round(
            sum(float(o["total_inr"]) for o in self.orders if is_delivered_status(o["status"])), 2
        )
        dataset_net_rev = round(
            sum(float(o["total_inr"]) for o in self.orders if not is_cancelled_status(o["status"])), 2
        )
        dataset_gross_rev = round(sum(float(o["total_inr"]) for o in self.orders), 2)

        dataset_summary = {
            "total_orders": len(self.orders),
            "cancelled_orders": dataset_cancelled_count,
            "cancelled_revenue_inr": dataset_cancelled_rev,
            "delivered_orders": dataset_delivered_count,
            "delivered_revenue_inr": dataset_delivered_rev,
            "net_revenue_inr": dataset_net_rev,
            "gross_revenue_inr": dataset_gross_rev
        }

        return {
            "total_orders": total_orders,
            "active_completed_orders": active_orders,
            "cancelled_orders": cancelled_orders,
            "cancelled_revenue_inr": round(cancelled_revenue_inr, 2),
            "delivered_orders": delivered_orders,
            "delivered_revenue_inr": round(delivered_revenue_inr, 2),
            "net_revenue_inr": round(net_revenue_inr, 2),
            "gross_revenue_inr": round(gross_revenue_inr, 2),
            "average_order_value_inr": avg_order_value,
            "status_breakdown": dict(status_breakdown),
            "status_revenue_breakdown": dict(status_revenue_breakdown),
            "dataset_summary": dataset_summary,
            "category_breakdown": dict(category_breakdown),
            "payment_method_breakdown": dict(payment_method_breakdown),
            "city_breakdown": dict(city_breakdown),
            "category_revenue_by_month": formatted_cat_rev_by_month,
            "monthly_revenue": formatted_monthly_revenue,
            "highest_spending_customer": highest_spender,
            "top_customers_spending": sorted_customers[:10],
            "applied_filters": {
                "status": status,
                "customer": customer,
                "category": category,
                "city": city,
                "payment_method": payment_method,
                "month": month,
                "start_date": start_date,
                "end_date": end_date
            },
            "revenue_policy": (
                "Net revenue in INR excludes cancelled orders. Cancelled orders and cancelled revenue are tracked separately. "
                "Delivered revenue specifically reflects orders with status 'delivered'."
            )
        }
