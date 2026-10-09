import React, { useState, useEffect, useMemo } from 'react';
import { exportOrdersToCSV } from '../utils/exportUtils';

export default function OrderExplorer({ apiBaseUrl, onAskAssistant }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [cityFilter, setCityFilter] = useState('');
  const [paymentFilter, setPaymentFilter] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Sorting
  const [sortBy, setSortBy] = useState('date-desc');

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 10;

  // Selected order for detail modal
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [actionError, setActionError] = useState(null);

  const handleAskAboutOrder = (order) => {
    setActionError(null);
    const orderId = order?.order_id ? String(order.order_id).trim() : '';
    if (!orderId) {
      setActionError('Could not find order ID. Unable to ask AI Assistant about this order.');
      return;
    }

    // Close the order details modal
    setSelectedOrder(null);

    // Formulate the contextual question
    const question = `Give me a summary of order ${orderId}, including its current status, customer, product, total amount, payment method, and delivery city.`;

    if (typeof onAskAssistant === 'function') {
      onAskAssistant(question);
    } else {
      setActionError('AI Assistant navigation is unavailable.');
    }
  };

  // Fetch all orders once from backend (60 orders total)
  const fetchOrders = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/orders?limit=100`);
      if (!res.ok) {
        throw new Error(`Failed to load orders (HTTP ${res.status})`);
      }
      const data = await res.json();
      setOrders(data.orders || []);
    } catch (err) {
      setError(err.message || 'Could not fetch orders from backend.');
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    let ignore = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBaseUrl}/api/orders?limit=100`);
        if (!res.ok) throw new Error(`Failed to load orders (HTTP ${res.status})`);
        const data = await res.json();
        if (!ignore) setOrders(data.orders || []);
      } catch (err) {
        if (!ignore) setError(err.message || 'Could not fetch orders from backend.');
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    load();
    return () => {
      ignore = true;
    };
  }, [apiBaseUrl]);

  // Derived filtered & sorted orders
  const filteredOrders = useMemo(() => {
    return orders.filter((o) => {
      // Search term matches order ID or customer name or product
      if (searchTerm.trim()) {
        const q = searchTerm.trim().toLowerCase();
        const matchesId = o.order_id.toLowerCase().includes(q);
        const matchesCustomer = o.customer_name.toLowerCase().includes(q);
        const matchesProduct = o.product.toLowerCase().includes(q);
        if (!matchesId && !matchesCustomer && !matchesProduct) {
          return false;
        }
      }

      // Status filter
      if (statusFilter && o.status.toLowerCase() !== statusFilter.toLowerCase()) {
        return false;
      }

      // Category filter
      if (categoryFilter && o.category.toLowerCase() !== categoryFilter.toLowerCase()) {
        return false;
      }

      // City filter
      if (cityFilter && o.city.toLowerCase() !== cityFilter.toLowerCase()) {
        return false;
      }

      // Payment method filter
      if (paymentFilter && o.payment_method.toLowerCase() !== paymentFilter.toLowerCase()) {
        return false;
      }

      // Date range filter
      if (startDate && o.order_date < startDate) {
        return false;
      }
      if (endDate && o.order_date > endDate) {
        return false;
      }

      return true;
    });
  }, [orders, searchTerm, statusFilter, categoryFilter, cityFilter, paymentFilter, startDate, endDate]);

  // Sorted list
  const sortedOrders = useMemo(() => {
    const list = [...filteredOrders];
    switch (sortBy) {
      case 'date-desc':
        return list.sort((a, b) => b.order_date.localeCompare(a.order_date));
      case 'date-asc':
        return list.sort((a, b) => a.order_date.localeCompare(b.order_date));
      case 'amount-desc':
        return list.sort((a, b) => b.total_inr - a.total_inr);
      case 'amount-asc':
        return list.sort((a, b) => a.total_inr - b.total_inr);
      case 'id-asc':
        return list.sort((a, b) => a.order_id.localeCompare(b.order_id));
      case 'id-desc':
        return list.sort((a, b) => b.order_id.localeCompare(a.order_id));
      default:
        return list;
    }
  }, [filteredOrders, sortBy]);

  // Paginated slice with auto-clamping to totalPages
  const totalPages = Math.ceil(sortedOrders.length / pageSize) || 1;
  const safeCurrentPage = Math.min(Math.max(currentPage, 1), totalPages);
  const paginatedOrders = useMemo(() => {
    const start = (safeCurrentPage - 1) * pageSize;
    return sortedOrders.slice(start, start + pageSize);
  }, [sortedOrders, safeCurrentPage, pageSize]);

  const clearAllFilters = () => {
    setSearchTerm('');
    setStatusFilter('');
    setCategoryFilter('');
    setCityFilter('');
    setPaymentFilter('');
    setStartDate('');
    setEndDate('');
    setSortBy('date-desc');
    setCurrentPage(1);
  };

  const hasActiveFilters =
    Boolean(searchTerm) ||
    Boolean(statusFilter) ||
    Boolean(categoryFilter) ||
    Boolean(cityFilter) ||
    Boolean(paymentFilter) ||
    Boolean(startDate) ||
    Boolean(endDate);

  const formatINR = (val) => {
    return `₹${Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="explorer-container">
      {/* Top Header & Export Controls */}
      <div className="explorer-header-row">
        <div>
          <h2 className="explorer-title">Searchable Order Explorer</h2>
          <p className="explorer-subtitle">
            Browse, search, sort, and filter all 60 customer orders with live criteria.
          </p>
        </div>
        <div className="explorer-header-actions">
          {hasActiveFilters && (
            <button
              type="button"
              className="btn-secondary"
              onClick={clearAllFilters}
            >
              ✕ Clear Filters
            </button>
          )}
          <button
            type="button"
            className="btn-primary"
            onClick={() => exportOrdersToCSV(sortedOrders, `orders_filtered_${new Date().toISOString().slice(0, 10)}.csv`)}
            title="Export currently filtered orders as CSV"
          >
            📥 Export CSV ({sortedOrders.length})
          </button>
        </div>
      </div>

      {/* Filter Toolbar Card */}
      <div className="filter-card">
        <div className="filter-grid">
          {/* Search Box */}
          <div className="filter-item search-filter-item">
            <label htmlFor="search-input" className="filter-label">Search Query</label>
            <div className="search-input-wrapper">
              <span className="search-icon">🔍</span>
              <input
                id="search-input"
                type="text"
                placeholder="Search order ID (ORD-1001), customer, or product..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="filter-input-search"
              />
              {searchTerm && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => setSearchTerm('')}
                  title="Clear search"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* Status Filter */}
          <div className="filter-item">
            <label htmlFor="status-select" className="filter-label">Status</label>
            <select
              id="status-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="filter-select"
            >
              <option value="">All Statuses (60)</option>
              <option value="delivered">Delivered (48)</option>
              <option value="cancelled">Cancelled (7)</option>
              <option value="returned">Returned (2)</option>
              <option value="processing">Processing (2)</option>
              <option value="shipped">Shipped (1)</option>
            </select>
          </div>

          {/* Category Filter */}
          <div className="filter-item">
            <label htmlFor="category-select" className="filter-label">Category</label>
            <select
              id="category-select"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="filter-select"
            >
              <option value="">All Categories</option>
              <option value="electronics">Electronics</option>
              <option value="furniture">Furniture</option>
              <option value="stationery">Stationery</option>
              <option value="accessories">Accessories</option>
            </select>
          </div>

          {/* City Filter */}
          <div className="filter-item">
            <label htmlFor="city-select" className="filter-label">City</label>
            <select
              id="city-select"
              value={cityFilter}
              onChange={(e) => setCityFilter(e.target.value)}
              className="filter-select"
            >
              <option value="">All Cities</option>
              <option value="chennai">Chennai</option>
              <option value="bengaluru">Bengaluru</option>
              <option value="hyderabad">Hyderabad</option>
              <option value="kochi">Kochi</option>
              <option value="pune">Pune</option>
              <option value="thiruvananthapuram">Thiruvananthapuram</option>
            </select>
          </div>

          {/* Payment Method Filter */}
          <div className="filter-item">
            <label htmlFor="payment-select" className="filter-label">Payment Method</label>
            <select
              id="payment-select"
              value={paymentFilter}
              onChange={(e) => setPaymentFilter(e.target.value)}
              className="filter-select"
            >
              <option value="">All Methods</option>
              <option value="upi">UPI</option>
              <option value="credit card">Credit Card</option>
              <option value="debit card">Debit Card</option>
              <option value="net banking">Net Banking</option>
              <option value="cash on delivery">Cash on Delivery</option>
            </select>
          </div>

          {/* Sorting Control */}
          <div className="filter-item">
            <label htmlFor="sort-select" className="filter-label">Sort By</label>
            <select
              id="sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="filter-select"
            >
              <option value="date-desc">Date (Newest First)</option>
              <option value="date-asc">Date (Oldest First)</option>
              <option value="amount-desc">Amount (Highest First)</option>
              <option value="amount-asc">Amount (Lowest First)</option>
              <option value="id-asc">Order ID (Ascending)</option>
              <option value="id-desc">Order ID (Descending)</option>
            </select>
          </div>
        </div>

        {/* Date Range Sub-row */}
        <div className="date-filter-row">
          <span className="date-label">Date Range:</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="filter-date-input"
            title="Start Date"
          />
          <span className="date-separator">to</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="filter-date-input"
            title="End Date"
          />
          {(startDate || endDate) && (
            <button
              type="button"
              className="btn-tiny"
              onClick={() => { setStartDate(''); setEndDate(''); }}
            >
              Clear Dates
            </button>
          )}
        </div>
      </div>

      {/* Action Error Alert */}
      {actionError && !selectedOrder && (
        <div className="error-banner" role="alert" style={{ borderRadius: '0.5rem', marginBottom: '1rem' }}>
          <span className="error-icon">⚠️</span>
          <span className="error-text" style={{ margin: '0 0.5rem' }}>{actionError}</span>
          <button
            type="button"
            className="error-dismiss"
            onClick={() => setActionError(null)}
            title="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}

      {/* Results Header & Summary */}
      <div className="results-summary-row">
        <span className="results-count">
          Showing <strong>{sortedOrders.length}</strong> of <strong>{orders.length}</strong> orders
          {hasActiveFilters && ' (filtered)'}
        </span>
        <span className="results-pagination-info">
          Page {safeCurrentPage} of {totalPages}
        </span>
      </div>

      {/* Table Container */}
      {loading ? (
        <div className="loading-state-card">
          <div className="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p>Loading orders from dataset...</p>
        </div>
      ) : error ? (
        <div className="error-card">
          <p>⚠️ {error}</p>
          <button className="btn-primary" onClick={fetchOrders}>Retry</button>
        </div>
      ) : sortedOrders.length === 0 ? (
        <div className="empty-state-card">
          <div className="empty-icon">🔍</div>
          <h3>No matching orders found</h3>
          <p>Try adjusting your search query, status filters, or date range.</p>
          <button className="btn-secondary" onClick={clearAllFilters}>
            Reset All Filters
          </button>
        </div>
      ) : (
        <div className="orders-table-wrapper">
          <table className="orders-table">
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Order Date</th>
                <th>Customer Name</th>
                <th>City</th>
                <th>Product</th>
                <th>Category</th>
                <th>Qty</th>
                <th>Total (INR)</th>
                <th>Payment</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {paginatedOrders.map((o) => (
                <tr
                  key={o.order_id}
                  className="order-row-interactive"
                  onClick={() => {
                    setSelectedOrder(o);
                    setActionError(null);
                  }}
                >
                  <td>
                    <span className="order-id-badge">{o.order_id}</span>
                  </td>
                  <td>{o.order_date}</td>
                  <td>
                    <strong>{o.customer_name}</strong>
                  </td>
                  <td>{o.city}</td>
                  <td className="product-cell" title={o.product}>
                    {o.product}
                  </td>
                  <td>
                    <span className="category-tag">{o.category}</span>
                  </td>
                  <td className="numeric-cell">{o.quantity}</td>
                  <td className="numeric-cell">
                    <strong>{formatINR(o.total_inr)}</strong>
                  </td>
                  <td className="payment-cell">{o.payment_method}</td>
                  <td>
                    <span className={`status-pill status-${o.status}`}>
                      {o.status}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-row-inspect"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedOrder(o);
                        setActionError(null);
                      }}
                      title="Inspect complete order details"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="pagination-bar">
          <button
            type="button"
            className="pagination-btn"
            disabled={safeCurrentPage === 1}
            onClick={() => setCurrentPage(Math.max(safeCurrentPage - 1, 1))}
          >
            ← Previous
          </button>

          <div className="pagination-numbers">
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((pg) => (
              <button
                key={pg}
                type="button"
                className={`pagination-num-btn ${pg === safeCurrentPage ? 'active' : ''}`}
                onClick={() => setCurrentPage(pg)}
              >
                {pg}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="pagination-btn"
            disabled={safeCurrentPage === totalPages}
            onClick={() => setCurrentPage(Math.min(safeCurrentPage + 1, totalPages))}
          >
            Next →
          </button>
        </div>
      )}

      {/* Detailed Order Modal */}
      {selectedOrder && (
        <div
          className="modal-backdrop"
          onClick={() => {
            setSelectedOrder(null);
            setActionError(null);
          }}
          role="dialog"
          aria-modal="true"
        >
          <div className="modal-card order-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="order-modal-header">
              <div>
                <span className="order-id-badge large-badge">{selectedOrder.order_id}</span>
                <span className={`status-pill status-${selectedOrder.status} ml-2`}>
                  {selectedOrder.status.toUpperCase()}
                </span>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => {
                  setSelectedOrder(null);
                  setActionError(null);
                }}
              >
                ✕
              </button>
            </div>

            <div className="order-details-grid">
              <div className="detail-item">
                <span className="detail-label">Customer Name</span>
                <span className="detail-value font-bold">{selectedOrder.customer_name}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Order Date</span>
                <span className="detail-value">{selectedOrder.order_date}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Delivery City</span>
                <span className="detail-value">{selectedOrder.city}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Payment Method</span>
                <span className="detail-value">{selectedOrder.payment_method}</span>
              </div>
              <div className="detail-item full-width">
                <span className="detail-label">Product Name</span>
                <span className="detail-value font-bold">{selectedOrder.product}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Category</span>
                <span className="detail-value">
                  <span className="category-tag">{selectedOrder.category}</span>
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Quantity</span>
                <span className="detail-value">{selectedOrder.quantity} item(s)</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Unit Price</span>
                <span className="detail-value">{formatINR(selectedOrder.unit_price_inr)}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Total Amount</span>
                <span className="detail-value font-bold text-blue">
                  {formatINR(selectedOrder.total_inr)}
                </span>
              </div>
            </div>

            {/* Action Error in Modal */}
            {actionError && (
              <div className="error-banner" role="alert" style={{ borderRadius: '0.375rem', marginTop: '0.75rem' }}>
                <span className="error-icon">⚠️</span>
                <span className="error-text" style={{ margin: '0 0.5rem' }}>{actionError}</span>
                <button
                  type="button"
                  className="error-dismiss"
                  onClick={() => setActionError(null)}
                  title="Dismiss error"
                >
                  ✕
                </button>
              </div>
            )}

            <div className="order-modal-actions">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setSelectedOrder(null);
                  setActionError(null);
                }}
              >
                Close
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => handleAskAboutOrder(selectedOrder)}
              >
                💬 Ask AI Assistant about this Order
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
