import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ConfirmModal from './ConfirmModal';

const SUGGESTIONS = [
  "What is the status of order ORD-1001?",
  "Show me all cancelled orders",
  "Calculate total revenue and cancelled orders",
  "What is the category revenue by month?",
  "Who is our highest-spending customer?",
  "Search for orders in Chennai"
];

export default function ChatAssistant({
  messages,
  setMessages,
  apiBaseUrl,
  inputMessage,
  setInputMessage,
  showClearModal,
  setShowClearModal
}) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedTools, setExpandedTools] = useState({});
  // Optional developer-only debugging mode (disabled by default in normal user-facing UI)
  const isDevDebugMode = typeof window !== 'undefined' && Boolean(window.__DEBUG_AI_TOOLS__);
  const messagesEndRef = useRef(null);
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(true);

  const checkScroll = React.useCallback(() => {
    if (scrollRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
      setCanScrollLeft(scrollLeft > 4);
      setCanScrollRight(scrollLeft + clientWidth < scrollWidth - 6);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      checkScroll();
    }, 50);

    const handleResize = () => checkScroll();
    window.addEventListener('resize', handleResize);

    const el = scrollRef.current;
    if (!el) {
      return () => {
        clearTimeout(timer);
        window.removeEventListener('resize', handleResize);
      };
    }

    const onWheel = (e) => {
      if (e.deltaY !== 0 && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
        checkScroll();
      }
    };

    el.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', handleResize);
      el.removeEventListener('wheel', onWheel);
    };
  }, [checkScroll]);

  const scrollSuggestions = (direction) => {
    if (scrollRef.current) {
      const offset = direction === 'left' ? -220 : 220;
      scrollRef.current.scrollBy({ left: offset, behavior: 'smooth' });
      setTimeout(checkScroll, 300);
    }
  };

  // Scroll to bottom on message change or loading state change
  useEffect(() => {
    if (typeof messagesEndRef.current?.scrollIntoView === 'function') {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, loading]);

  const toggleToolExpand = (index, toolIdx) => {
    const key = `${index}-${toolIdx}`;
    setExpandedTools(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSend = async (messageToSend) => {
    const text = (messageToSend || input).trim();
    if (!text || loading) return;

    if (text.length > 2000) {
      setError('Message exceeds the maximum limit of 2,000 characters.');
      return;
    }

    setError(null);
    setInput('');

    // Append user message to history
    const userMessage = { role: 'user', content: text };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setLoading(true);

    // AbortController to enforce 45s timeout
    const controller = new AbortController();
    const timeoutDuration = 45000;
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, timeoutDuration);

    try {
      // Build conversation history for API payload (skip initial greeting for cleaner context)
      const historyPayload = updatedMessages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .slice(-10) // Keep recent 10 messages
        .map(m => ({ role: m.role, content: m.content }));

      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          message: text,
          conversation_history: historyPayload.slice(0, -1) // Exclude current turn
        })
      });

      let data = {};
      try {
        data = await response.json();
      } catch {
        data = { detail: `Server returned HTTP ${response.status}: ${response.statusText || 'Unable to parse response'}` };
      }

      if (!response.ok) {
        let errorMsg = data.detail || 'An unexpected error occurred.';
        if (data.error_type === 'MISSING_API_KEY') {
          errorMsg = 'API Key Required: Please add your OPENAI_API_KEY or GROQ_API_KEY into backend/.env and restart the backend server.';
        } else if (data.error_type === 'PROVIDER_ERROR') {
          errorMsg = `AI Provider Error: ${data.detail}`;
        }
        setError(errorMsg);
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: `⚠️ **Request Failed**: ${errorMsg}`,
            tools_used: [],
            isError: true
          }
        ]);
      } else {
        if (data.tools_used && data.tools_used.length > 0) {
          console.debug('[Developer Debug] Tools executed by AI assistant:', data.tools_used);
        }
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: data.reply || data.response || 'No response returned from the model.',
            tools_used: data.tools_used || []
          }
        ]);
      }
    } catch (err) {
      let connErr;
      if (err.name === 'AbortError') {
        connErr = 'Request timed out after 45 seconds while waiting for the AI model to execute tools. Please try again.';
      } else {
        connErr = 'Could not reach backend API at ' + apiBaseUrl + '. Is the FastAPI server running on port 8000?';
      }
      setError(connErr);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `⚠️ **Connection / Timeout Error**: ${connErr}`,
          tools_used: [],
          isError: true
        }
      ]);
    } finally {
      clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSendRef = useRef(handleSend);
  useEffect(() => {
    handleSendRef.current = handleSend;
  });

  const lastProcessedMessageRef = useRef(null);

  // If a parent passes an inputMessage, trigger send immediately without cancellable timers
  useEffect(() => {
    if (inputMessage && inputMessage.trim()) {
      const msg = inputMessage.trim();
      if (lastProcessedMessageRef.current !== msg) {
        lastProcessedMessageRef.current = msg;
        if (setInputMessage) {
          setInputMessage('');
        }
        handleSendRef.current?.(msg);
      }
    } else {
      lastProcessedMessageRef.current = null;
    }
  }, [inputMessage, setInputMessage]);

  const executeClearChat = () => {
    setMessages([
      {
        role: 'assistant',
        content: 'Conversation cleared. How can I assist you with your orders?',
        tools_used: []
      }
    ]);
    setError(null);
    setShowClearModal(false);
  };

  const cleanMarkdownContent = (content) => {
    if (!content) return '';
    return content.replace(/<br\s*\/?>/gi, '\n');
  };

  return (
    <div className="chat-container">
      {/* Feed Area */}
      <main className="chat-feed" role="log" aria-live="polite">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`message-row ${msg.role === 'user' ? 'message-user' : 'message-assistant'}`}
          >
            <div className="message-bubble">
              <div className="message-header">
                <span className="message-author">
                  {msg.role === 'user' ? '👤 You' : '🤖 Order Assistant'}
                </span>
              </div>

              {/* Developer-Only Tool Inspection Badges (hidden by default in standard user-facing UI) */}
              {isDevDebugMode && msg.tools_used && msg.tools_used.length > 0 && (
                <div className="tools-container">
                  <div className="tools-header-label">
                    <span>⚡ Function Calls Executed ({msg.tools_used.length})</span>
                  </div>
                  {msg.tools_used.map((t, toolIdx) => {
                    const isExpanded = expandedTools[`${index}-${toolIdx}`];
                    return (
                      <div key={toolIdx} className="tool-chip">
                        <div
                          className="tool-summary-row"
                          onClick={() => toggleToolExpand(index, toolIdx)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              toggleToolExpand(index, toolIdx);
                            }
                          }}
                        >
                          <span className="tool-name">🔧 {typeof t === 'string' ? t : (t.tool_name || '')}</span>
                          <span className="tool-toggle-icon">
                            {isExpanded ? '▲ hide' : '▼ inspect'}
                          </span>
                        </div>
                        {isExpanded && (
                          <div className="tool-details-panel">
                            <div className="tool-section">
                              <span className="tool-section-label">Arguments:</span>
                              <pre>{JSON.stringify(t.arguments, null, 2)}</pre>
                            </div>
                            <div className="tool-section">
                              <span className="tool-section-label">Result:</span>
                              <pre>{JSON.stringify(t.result, null, 2)}</pre>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Message Content with Markdown Support */}
              <div className="message-body">
                {msg.role === 'user' ? (
                  <div className="user-message-text">{msg.content}</div>
                ) : (
                  <div className="markdown-body">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        table: ({ ...props }) => (
                          <div className="markdown-table-wrapper">
                            <table className="markdown-table" {...props} />
                          </div>
                        ),
                        code: ({ className, children, ...props }) => {
                          const isInline = !className && !String(children).includes('\n');
                          return isInline ? (
                            <code className="code-pill" {...props}>
                              {children}
                            </code>
                          ) : (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          );
                        },
                        pre: ({ ...props }) => (
                          <pre className="code-block" {...props} />
                        )
                      }}
                    >
                      {cleanMarkdownContent(msg.content)}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Loading Indicator */}
        {loading && (
          <div className="message-row message-assistant">
            <div className="message-bubble loading-bubble">
              <div className="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <span className="loading-text">Analyzing dataset & executing tools...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Suggested Questions Section */}
      <div className="suggestions-bar">
        <span className="suggestions-title">Suggested:</span>
        <div className="suggestions-container">
          <button
            type="button"
            className={`suggestions-nav-btn btn-left ${canScrollLeft ? 'visible' : ''}`}
            onClick={() => scrollSuggestions('left')}
            disabled={!canScrollLeft}
            aria-label="Scroll suggestions left"
            title="Scroll left"
          >
            ‹
          </button>
          <div
            ref={scrollRef}
            className="suggestions-scroll"
            onScroll={checkScroll}
            tabIndex={0}
            role="region"
            aria-label="Suggested prompt chips"
          >
            {SUGGESTIONS.map((q, idx) => (
              <button
                key={idx}
                type="button"
                className="suggestion-pill"
                onClick={() => handleSend(q)}
                disabled={loading}
              >
                {q}
              </button>
            ))}
            <div className="suggestions-end-spacer" aria-hidden="true" />
          </div>
          <button
            type="button"
            className={`suggestions-nav-btn btn-right ${canScrollRight ? 'visible' : ''}`}
            onClick={() => scrollSuggestions('right')}
            disabled={!canScrollRight}
            aria-label="Scroll suggestions right"
            title="Scroll right"
          >
            ›
          </button>
        </div>
      </div>

      {/* Error Alert Banner */}
      {error && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{error}</span>
          <button
            type="button"
            className="error-dismiss"
            onClick={() => setError(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* Chat Input Section */}
      <footer className="chat-input-area">
        <div className="input-box-wrapper">
          <textarea
            className="chat-textarea"
            placeholder="Ask about orders, revenue, customer metrics, cancellations... (Press Enter to send)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            rows={2}
          />
          <button
            type="button"
            className="btn-send"
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
            title="Send message"
          >
            {loading ? 'Thinking...' : 'Send ➔'}
          </button>
        </div>
        <p className="input-caption">
          Powered by native LLM tool calling against <code className="code-pill">backend/data/orders.csv</code> (60 records).
        </p>
      </footer>

      {/* Confirmation Modal for Clearing Chat */}
      <ConfirmModal
        isOpen={showClearModal}
        title="Clear Conversation History?"
        message="This will reset the current chat session and clear all messages from your view. The 60-order dataset will remain unchanged."
        confirmText="Clear History"
        onConfirm={executeClearChat}
        onCancel={() => setShowClearModal(false)}
      />
    </div>
  );
}
