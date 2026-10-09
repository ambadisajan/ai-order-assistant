import React from 'react';

export default function Navbar({ activeTab, setActiveTab, backendStatus, onClearChat, messageCount }) {
  return (
    <header className="app-header">
      <div className="brand-section">
        <div className="brand-icon">📦</div>
        <div>
          <div className="brand-badge">Enterprise Edition</div>
          <h1 className="brand-title">AI Order Assistant</h1>
          <p className="brand-subtitle">FastAPI Tool Calling & Analytics Platform</p>
        </div>
      </div>

      <nav className="nav-tabs" aria-label="Main Navigation">
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
          aria-current={activeTab === 'chat' ? 'page' : undefined}
        >
          <span className="tab-icon">💬</span>
          <span className="tab-label">AI Assistant</span>
          {messageCount > 1 && <span className="tab-badge">{messageCount}</span>}
        </button>

        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
          aria-current={activeTab === 'dashboard' ? 'page' : undefined}
        >
          <span className="tab-icon">📊</span>
          <span className="tab-label">Analytics Dashboard</span>
        </button>

        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'orders' ? 'active' : ''}`}
          onClick={() => setActiveTab('orders')}
          aria-current={activeTab === 'orders' ? 'page' : undefined}
        >
          <span className="tab-icon">📦</span>
          <span className="tab-label">Order Explorer</span>
          {backendStatus.count > 0 && <span className="tab-badge">{backendStatus.count}</span>}
        </button>
      </nav>

      <div className="header-actions">
        <div
          className={`status-badge ${backendStatus.online ? 'status-online' : 'status-offline'}`}
          title={backendStatus.online ? `Model: ${backendStatus.model}` : 'FastAPI backend unavailable'}
        >
          <span className="status-dot"></span>
          <span>
            {backendStatus.online
              ? `Live (${backendStatus.count} orders)`
              : 'Backend Offline'}
          </span>
        </div>

        {activeTab === 'chat' && (
          <button
            onClick={onClearChat}
            className="btn-secondary"
            title="Clear conversation history"
            type="button"
          >
            Clear Chat
          </button>
        )}
      </div>
    </header>
  );
}
