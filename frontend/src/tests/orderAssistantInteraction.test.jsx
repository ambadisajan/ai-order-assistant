import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import OrderExplorer from '../components/OrderExplorer';
import ChatAssistant from '../components/ChatAssistant';
import App from '../App';

if (typeof window !== 'undefined' && window.HTMLElement) {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
}

describe('Order Explorer - Ask AI Assistant Button & Interaction', () => {
  const mockOrders = [
    {
      order_id: 'ORD-1058',
      order_date: '2024-03-15',
      customer_name: 'Ananya Verma',
      city: 'Bengaluru',
      product: 'Noise Cancelling Headphones',
      category: 'Electronics',
      quantity: 1,
      unit_price_inr: 8999,
      total_inr: 8999,
      payment_method: 'UPI',
      status: 'delivered'
    },
    {
      order_id: 'ORD-1015',
      order_date: '2024-02-10',
      customer_name: 'Rajesh Nair',
      city: 'Kochi',
      product: 'Mechanical Keyboard',
      category: 'Electronics',
      quantity: 2,
      unit_price_inr: 2500,
      total_inr: 5000,
      payment_method: 'Credit Card',
      status: 'cancelled'
    }
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/orders')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ orders: mockOrders, total: mockOrders.length })
        });
      }
      if (url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', orders_count: 2, model: 'llama-3.3-70b-versatile' })
        });
      }
      if (url.includes('/api/chat')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            reply: 'Here is the summary of order ORD-1058: Status is delivered, Customer is Ananya Verma in Bengaluru.',
            tools_used: ['get_order_details']
          })
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({})
      });
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('captures order ID, closes modal, and passes contextual summary question to onAskAssistant', async () => {
    const handleAskAssistant = vi.fn();
    render(<OrderExplorer apiBaseUrl="http://localhost:8000" onAskAssistant={handleAskAssistant} />);

    // Wait for orders to load in table
    await waitFor(() => {
      expect(screen.getByText('ORD-1058')).toBeTruthy();
    });

    // Click on row for ORD-1058 to open modal
    const orderCell = screen.getByText('ORD-1058');
    fireEvent.click(orderCell);

    // Modal should be open
    expect(screen.getByRole('dialog')).toBeTruthy();
    const askButton = screen.getByRole('button', { name: /Ask AI Assistant about this Order/i });
    expect(askButton).toBeTruthy();

    // Click "Ask AI Assistant about this Order"
    fireEvent.click(askButton);

    // Modal should be closed
    expect(screen.queryByRole('dialog')).toBeNull();

    // onAskAssistant should be called with full contextual question
    expect(handleAskAssistant).toHaveBeenCalledTimes(1);
    expect(handleAskAssistant).toHaveBeenCalledWith(
      'Give me a summary of order ORD-1058, including its current status, customer, product, total amount, payment method, and delivery city.'
    );
  });

  it('displays a useful error message when order ID cannot be found, rather than silently failing', async () => {
    const handleAskAssistant = vi.fn();
    const badOrders = [
      {
        order_id: '',
        customer_name: 'Unknown User',
        status: 'pending'
      }
    ];

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/orders')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ orders: badOrders, total: 1 })
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<OrderExplorer apiBaseUrl="http://localhost:8000" onAskAssistant={handleAskAssistant} />);

    await waitFor(() => {
      expect(screen.getByText('Unknown User')).toBeTruthy();
    });

    // Click the row to open modal
    fireEvent.click(screen.getByText('Unknown User'));

    // Modal opens
    expect(screen.getByRole('dialog')).toBeTruthy();
    const askButton = screen.getByRole('button', { name: /Ask AI Assistant about this Order/i });

    // Click ask button with empty order_id
    fireEvent.click(askButton);

    // Error banner should appear
    expect(screen.getByText(/Could not find order ID/i)).toBeTruthy();

    // Modal should remain open to show error, and callback should NOT be invoked
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(handleAskAssistant).not.toHaveBeenCalled();
  });
});

describe('ChatAssistant - programmatic inputMessage execution', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('executes inputMessage immediately without cancellation and clears inputMessage', async () => {
    let currentInputMessage = 'Give me a summary of order ORD-1058, including its current status, customer, product, total amount, payment method, and delivery city.';
    const setInputMessageMock = vi.fn((newVal) => {
      currentInputMessage = newVal;
    });
    const setMessagesMock = vi.fn();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        reply: 'Order ORD-1058 summary: Customer Ananya Verma, Delivered.',
        tools_used: ['get_order_details']
      })
    });
    global.fetch = fetchMock;

    const initialMessages = [
      {
        role: 'assistant',
        content: 'Hello! I am your AI Order Assistant.',
        tools_used: []
      }
    ];

    const { rerender } = render(
      <ChatAssistant
        messages={initialMessages}
        setMessages={setMessagesMock}
        apiBaseUrl="http://localhost:8000"
        inputMessage={currentInputMessage}
        setInputMessage={setInputMessageMock}
        showClearModal={false}
        setShowClearModal={vi.fn()}
      />
    );

    // setInputMessage('') should have been called to reset parent state
    expect(setInputMessageMock).toHaveBeenCalledWith('');

    // Re-render with cleared inputMessage as parent would
    rerender(
      <ChatAssistant
        messages={initialMessages}
        setMessages={setMessagesMock}
        apiBaseUrl="http://localhost:8000"
        inputMessage=""
        setInputMessage={setInputMessageMock}
        showClearModal={false}
        setShowClearModal={vi.fn()}
      />
    );

    // /api/chat should have been called with the contextual question
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/chat',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('ORD-1058')
        })
      );
    });

    // setMessages should have been called with user message
    expect(setMessagesMock).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          role: 'user',
          content: expect.stringContaining('ORD-1058')
        })
      ])
    );
  });
});

describe('End-to-End Navigation & Order Query Flow in App', () => {
  const sampleOrders = [
    {
      order_id: 'ORD-1058',
      order_date: '2024-03-15',
      customer_name: 'Ananya Verma',
      city: 'Bengaluru',
      product: 'Noise Cancelling Headphones',
      category: 'Electronics',
      quantity: 1,
      unit_price_inr: 8999,
      total_inr: 8999,
      payment_method: 'UPI',
      status: 'delivered'
    }
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ orders_count: 60, model: 'llama-3.3-70b-versatile' })
        });
      }
      if (url.includes('/api/orders')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ orders: sampleOrders, total: sampleOrders.length })
        });
      }
      if (url.includes('/api/chat')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            reply: 'Here is the summary of order ORD-1058: Status is DELIVERED, Customer is Ananya Verma, Total is ₹8,999.00.',
            tools_used: ['get_order_details']
          })
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  it('completes the full loop: Order Explorer -> Modal -> Ask AI -> Switch Tab -> Chat Request & Response', async () => {
    render(<App />);

    // Initially on Chat tab. Switch to Order Explorer tab.
    const ordersTabBtn = screen.getByRole('button', { name: /Order Explorer/i });
    fireEvent.click(ordersTabBtn);

    // Wait for orders table to load
    await waitFor(() => {
      expect(screen.getByText('ORD-1058')).toBeTruthy();
    });

    // Click order row
    fireEvent.click(screen.getByText('ORD-1058'));

    // Modal opens
    const modalAskBtn = screen.getByRole('button', { name: /Ask AI Assistant about this Order/i });
    expect(modalAskBtn).toBeTruthy();

    // Click "Ask AI Assistant about this Order"
    fireEvent.click(modalAskBtn);

    // Modal should be closed
    expect(screen.queryByRole('dialog')).toBeNull();

    // Should have automatically navigated back to AI Assistant tab
    // The chat feed should show the user question
    await waitFor(() => {
      expect(screen.getByText(/Give me a summary of order ORD-1058/i)).toBeTruthy();
    });

    // And the assistant response should appear in chat
    await waitFor(() => {
      expect(screen.getByText(/Here is the summary of order ORD-1058: Status is DELIVERED/i)).toBeTruthy();
    });

    // Function Calls Executed and tool names must NOT be visible in normal chat UI
    expect(screen.queryByText(/Function Calls Executed/i)).toBeNull();
    expect(screen.queryByText(/get_order_details/i)).toBeNull();
  });

  it('renders Function Calls Executed only when developer debug mode is explicitly enabled', async () => {
    window.__DEBUG_AI_TOOLS__ = true;
    render(<App />);

    const ordersTabBtn = screen.getByRole('button', { name: /Order Explorer/i });
    fireEvent.click(ordersTabBtn);

    await waitFor(() => {
      expect(screen.getByText('ORD-1058')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('ORD-1058'));
    fireEvent.click(screen.getByRole('button', { name: /Ask AI Assistant about this Order/i }));

    await waitFor(() => {
      expect(screen.getByText(/Here is the summary of order ORD-1058: Status is DELIVERED/i)).toBeTruthy();
    });

    // In debug mode, the tool badge is accessible to developers
    expect(screen.getByText(/Function Calls Executed/i)).toBeTruthy();
    expect(screen.getByText(/get_order_details/i)).toBeTruthy();

    delete window.__DEBUG_AI_TOOLS__;
  });
});
