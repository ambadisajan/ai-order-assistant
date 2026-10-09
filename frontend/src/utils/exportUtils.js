/**
 * Safe CSV export and metrics reporting utilities.
 * Handles proper RFC 4180 escaping for commas, quotes, and newlines.
 */

function escapeCSVField(value) {
  if (value === null || value === undefined) {
    return '""';
  }
  const str = String(value);
  if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return `"${str}"`;
}

export function exportOrdersToCSV(orders, filename = 'orders_export.csv') {
  if (!orders || orders.length === 0) {
    alert('No orders to export.');
    return;
  }

  const headers = [
    'Order ID',
    'Order Date',
    'Customer Name',
    'City',
    'Product',
    'Category',
    'Quantity',
    'Unit Price (INR)',
    'Total (INR)',
    'Payment Method',
    'Status'
  ];

  const rows = orders.map(o => [
    escapeCSVField(o.order_id),
    escapeCSVField(o.order_date),
    escapeCSVField(o.customer_name),
    escapeCSVField(o.city),
    escapeCSVField(o.product),
    escapeCSVField(o.category),
    o.quantity,
    o.unit_price_inr,
    o.total_inr,
    escapeCSVField(o.payment_method),
    escapeCSVField(o.status)
  ]);

  const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\r\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function exportMetricsReport(metrics, filename = 'order_metrics_summary.txt') {
  if (!metrics) {
    alert('No analytics metrics available to export.');
    return;
  }

  const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19);
  const reportLines = [
    '================================================================================',
    '                  AI ORDER ASSISTANT - BUSINESS METRICS REPORT                  ',
    '================================================================================',
    `Generated At: ${timestamp}`,
    `Dataset Scope: Local Screening Dataset (60 Orders)`,
    '',
    '--------------------------------------------------------------------------------',
    '1. EXECUTIVE REVENUE & ORDER TOTALS',
    '--------------------------------------------------------------------------------',
    `Total Orders in Dataset:        ${metrics.total_orders}`,
    `Delivered Orders:               ${metrics.delivered_orders} (₹${(metrics.delivered_revenue_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })})`,
    `Active/Completed Orders:        ${metrics.active_completed_orders}`,
    `Net Revenue (excl. cancelled):  ₹${(metrics.net_revenue_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`,
    `Gross Revenue (incl. all):      ₹${(metrics.gross_revenue_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`,
    `Cancelled Orders (Lost Rev):    ${metrics.cancelled_orders} (₹${(metrics.cancelled_revenue_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })})`,
    `Average Order Value (AOV):      ₹${(metrics.average_order_value_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })} (Net Rev ÷ Active Orders)`,
    '',
    '--------------------------------------------------------------------------------',
    '2. ORDER STATUS DISTRIBUTION',
    '--------------------------------------------------------------------------------'
  ];

  if (metrics.status_breakdown) {
    Object.entries(metrics.status_breakdown).forEach(([st, cnt]) => {
      const rev = metrics.status_revenue_breakdown ? (metrics.status_revenue_breakdown[st] || 0) : 0;
      reportLines.push(
        `  - ${st.toUpperCase().padEnd(14)}: ${String(cnt).padStart(3)} orders | ₹${rev.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
      );
    });
  }

  reportLines.push(
    '',
    '--------------------------------------------------------------------------------',
    '3. CATEGORY NET REVENUE BREAKDOWN',
    '--------------------------------------------------------------------------------'
  );

  if (metrics.category_breakdown) {
    Object.entries(metrics.category_breakdown).forEach(([cat, val]) => {
      const rev = typeof val === 'object' ? val.net_revenue_inr : val;
      const cnt = typeof val === 'object' ? val.count : '';
      reportLines.push(
        `  - ${cat.padEnd(16)}: ${String(cnt).padStart(3)} orders | ₹${Number(rev || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
      );
    });
  }

  if (metrics.highest_spending_customer) {
    reportLines.push(
      '',
      '--------------------------------------------------------------------------------',
      '4. TOP CUSTOMER',
      '--------------------------------------------------------------------------------',
      `  Name:        ${metrics.highest_spending_customer.customer_name}`,
      `  Net Spend:   ₹${(metrics.highest_spending_customer.net_spend_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`,
      `  Total Orders: ${metrics.highest_spending_customer.orders_count} (${metrics.highest_spending_customer.delivered_orders} delivered)`
    );
  }

  reportLines.push(
    '',
    '================================================================================',
    'REVENUE POLICY NOTE:',
    metrics.revenue_policy || 'Net revenue excludes cancelled orders.',
    '================================================================================'
  );

  const textContent = reportLines.join('\r\n');
  const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
