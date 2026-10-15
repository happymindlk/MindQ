import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Bot, User } from 'lucide-react';
import { api } from '../api/client';

export default function Chatbot() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    { id: 1, text: "Hello! I'm your MindQ assistant. How can I help you today?", sender: 'bot' }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const generateBasicResponse = (msg) => {
    const lower = msg.toLowerCase();
    if (lower.includes('start') || lower.includes('begin')) {
      return "Enter your access code and email on the login page to begin.";
    }
    if (lower.includes('access code') || lower.includes('code')) {
      return "Your access code was provided by your organization. It looks like HM-XXXX-X.";
    }
    if (lower.includes('time') || lower.includes('long') || lower.includes('duration')) {
      return "Each test typically takes 15-30 minutes. Your progress is saved automatically.";
    }
    if (lower.includes('help') || lower.includes('stuck') || lower.includes('error')) {
      return "If you're having trouble, please contact your organization administrator.";
    }
    return "I'm not sure about that. Try asking about getting started, access codes, or test duration.";
  };

  const handleSend = async (e) => {
    e?.preventDefault();
    if (!input.trim()) return;

    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { id: Date.now(), text: userMsg, sender: 'user' }]);
    setIsTyping(true);

    // Try API first, fallback to basic logic
    try {
      const res = await api.chat.sendMessage(userMsg);
      setMessages(prev => [...prev, { id: Date.now(), text: res.response || generateBasicResponse(userMsg), sender: 'bot' }]);
    } catch (err) {
      // Fallback
      setTimeout(() => {
        setMessages(prev => [...prev, { id: Date.now(), text: generateBasicResponse(userMsg), sender: 'bot' }]);
        setIsTyping(false);
      }, 600);
      return;
    }
    setIsTyping(false);
  };

  return (
    <>
      {/* Toggle Button */}
      <button
        onClick={() => setIsOpen(true)}
        className={`
          fixed bottom-6 right-6 p-4 rounded-full bg-indigo-600 text-white shadow-lg shadow-indigo-500/30
          hover:bg-indigo-500 hover:-translate-y-1 transition-all duration-300 z-50
          ${isOpen ? 'scale-0 opacity-0 pointer-events-none' : 'scale-100 opacity-100'}
        `}
      >
        <MessageSquare className="w-6 h-6" />
      </button>

      {/* Chat Window */}
      <div className={`
        fixed bottom-6 right-6 w-[350px] max-w-[calc(100vw-3rem)] bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl z-50
        flex flex-col transform transition-all duration-300 origin-bottom-right
        ${isOpen ? 'scale-100 opacity-100' : 'scale-90 opacity-0 pointer-events-none'}
      `} style={{ height: '500px', maxHeight: 'calc(100vh - 6rem)' }}>
        
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-800/50 rounded-t-2xl">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-indigo-500/20 flex items-center justify-center text-indigo-400">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-50">Support Assistant</h3>
              <p className="text-xs text-slate-400">Always online</p>
            </div>
          </div>
          <button 
            onClick={() => setIsOpen(false)}
            className="text-slate-400 hover:text-slate-50 p-1 rounded-md hover:bg-slate-700 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-3 ${msg.sender === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`
                w-8 h-8 rounded-full flex items-center justify-center shrink-0
                ${msg.sender === 'user' ? 'bg-slate-800 text-slate-300' : 'bg-indigo-500/20 text-indigo-400'}
              `}>
                {msg.sender === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>
              <div className={`
                max-w-[75%] px-4 py-2.5 rounded-2xl text-sm
                ${msg.sender === 'user' 
                  ? 'bg-indigo-600 text-white rounded-tr-sm' 
                  : 'bg-slate-800 text-slate-200 rounded-tl-sm'
                }
              `}>
                {msg.text}
              </div>
            </div>
          ))}
          {isTyping && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-full bg-indigo-500/20 flex items-center justify-center shrink-0 text-indigo-400">
                <Bot className="w-4 h-4" />
              </div>
              <div className="bg-slate-800 px-4 py-3 rounded-2xl rounded-tl-sm flex gap-1.5 items-center">
                <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"></div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form onSubmit={handleSend} className="p-3 border-t border-slate-800 bg-slate-900 rounded-b-2xl">
          <div className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your message..."
              className="w-full bg-slate-800 border border-slate-700 text-slate-50 text-sm rounded-full pl-4 pr-12 py-2.5 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
            <button
              type="submit"
              disabled={!input.trim() || isTyping}
              className="absolute right-1.5 p-1.5 bg-indigo-600 text-white rounded-full hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
