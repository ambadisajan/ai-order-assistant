import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import ChatAssistant from './components/ChatAssistant';
import Dashboard from './components/Dashboard';
import OrderExplorer from './components/OrderExplorer';
import './App.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000');

export default function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [backendStatus, setBackendStatus] = useState({ online: false, count: 0, model: '' });
  const [inputMessage, setInputMessage] = useState('');
  const [showClearModal, setShowClearModal] = useState(false);

  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I am your AI Order Assistant. I can look up specific orders, filter orders by customer, status, or city, and calculate accurate financial metrics directly from the dataset. How can I help you today?',
      tools_used: []
    }
  ]);

  // Check backend health on mount
  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/health`);
        if (res.ok) {
          const data = await res.json();
          setBackendStatus({ online: true, count: data.orders_count, model: data.model });
        } else {
          setBackendStatus({ online: false, count: 0, model: '' });
        }
      } catch {
        setBackendStatus({ online: false, count: 0, model: '' });
      }
    }
    checkHealth();
  }, []);

  const handleAskAssistant = (question) => {
    setActiveTab('chat');
    setInputMessage(question);
  };

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        backendStatus={backendStatus}
        onClearChat={() => setShowClearModal(true)}
        messageCount={messages.length}
      />

      <div className="app-content-body">
        {activeTab === 'chat' && (
          <ChatAssistant
            messages={messages}
            setMessages={setMessages}
            apiBaseUrl={API_BASE_URL}
            inputMessage={inputMessage}
            setInputMessage={setInputMessage}
            showClearModal={showClearModal}
            setShowClearModal={setShowClearModal}
          />
        )}

        {activeTab === 'dashboard' && (
          <Dashboard
            apiBaseUrl={API_BASE_URL}
            onAskAssistant={handleAskAssistant}
          />
        )}

        {activeTab === 'orders' && (
          <OrderExplorer
            apiBaseUrl={API_BASE_URL}
            onAskAssistant={handleAskAssistant}
          />
        )}
      </div>
    </div>
  );
}
