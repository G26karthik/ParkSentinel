"use client";

import { useState } from "react";
import { postQuery } from "@/lib/api";

const EXAMPLES = [
  "Which junction has the most HGV violations?",
  "What is the peak violation hour on weekends?",
  "Which police station zone worsened most in March?",
  "How many scooters were caught parking on footpaths?",
  "Show top 5 zones by double parking incidents",
];

interface Message {
  role: "user" | "assistant";
  question?: string;
  sql?: string;
  answer?: string;
  data?: Record<string, unknown>[];
  loading?: boolean;
}

export default function QueryPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleAsk(question: string) {
    if (!question.trim() || loading) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", question },
      { role: "assistant", loading: true },
    ]);
    setInput("");
    setLoading(true);

    try {
      const result = await postQuery(question);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          sql: result.sql,
          answer: result.answer,
          data: result.data,
        };
        return updated;
      });
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          answer: "Failed to connect to the query API. Ensure the backend is running.",
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-full w-full p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
          <span>💬</span> Ask AI Command Center
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          BTP Tactical Intelligence Engine — Query live database with natural language
        </p>
      </div>

      {/* Suggested Command Chips */}
      <div className="space-y-2">
        <div className="text-[10px] uppercase font-mono tracking-wider text-gray-500 font-bold">Suggested Command Queries:</div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              onClick={() => handleAsk(q)}
              disabled={loading}
              className="text-[11px] font-mono bg-gray-900 border border-gray-800 hover:border-red-900/50 hover:bg-red-950/10 text-gray-400 hover:text-white px-3 py-1.5 rounded transition-all disabled:opacity-50"
            >
              &gt; {q}
            </button>
          ))}
        </div>
      </div>

      {/* Command Console Screen Container */}
      <div className="flex-1 bg-gray-950/60 border border-gray-800/80 rounded-xl p-4 flex flex-col min-h-0 backdrop-blur-sm">
        {/* Terminal Header */}
        <div className="flex items-center justify-between border-b border-gray-800/60 pb-2 mb-4 text-[10px] uppercase font-mono tracking-wider text-gray-500">
          <span>Terminal Node: BTP-AI-COGNITIVE</span>
          <span className="flex items-center gap-1.5 font-bold">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            Secure Console Linked
          </span>
        </div>

        {/* Messages Feed */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1">
          {messages.length === 0 && (
            <div className="text-center text-gray-600 my-16 font-mono space-y-3">
              <p className="text-4xl text-gray-700 animate-pulse">📟</p>
              <p className="text-sm font-semibold tracking-wide uppercase">System Standby</p>
              <p className="text-xs max-w-md mx-auto leading-relaxed text-gray-500 font-sans">
                Awaiting BTP traffic queries. Click a suggested question above or type a custom command below to analyze violation database records.
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className="space-y-1">
              {msg.role === "user" && (
                <div className="flex justify-end w-full">
                  <div className="bg-red-950/30 border border-red-800/40 rounded-lg p-3 max-w-xl text-sm font-mono space-y-1.5">
                    <div className="text-[10px] text-red-400 uppercase tracking-wider font-bold">You</div>
                    <p className="text-gray-200">{msg.question}</p>
                  </div>
                </div>
              )}
              {msg.role === "assistant" && (
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3 font-mono">
                  {msg.loading ? (
                    <div className="flex items-center gap-2 text-gray-400 text-xs">
                      <div className="animate-spin w-4 h-4 border-2 border-red-500 border-t-transparent rounded-full" />
                      Thinking...
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center justify-between border-b border-gray-800/40 pb-1.5">
                        <div className="text-[10px] text-green-400 font-bold uppercase tracking-wider flex items-center gap-1">
                          <span>AI Answer</span>
                        </div>
                        {msg.data && (
                          <span className="text-[9px] text-gray-500 uppercase">{msg.data.length} records retrieved</span>
                        )}
                      </div>
                      <p className="text-gray-100 text-sm font-sans leading-relaxed">{msg.answer}</p>
                      
                      {msg.sql && (
                        <details className="text-xs bg-gray-950/60 border border-gray-800/60 rounded p-2">
                          <summary className="text-gray-500 cursor-pointer font-mono text-[10px] uppercase font-semibold select-none hover:text-gray-400">
                            Show SQL Statement
                          </summary>
                          <pre className="mt-2 bg-gray-950 p-3 rounded text-red-450 text-red-400 overflow-x-auto border border-red-950/30 font-mono text-xs whitespace-pre-wrap">
                            {msg.sql}
                          </pre>
                        </details>
                      )}

                      {msg.data && msg.data.length > 0 && (
                        <div className="overflow-x-auto border border-gray-800 rounded-md">
                          <table className="w-full text-[11px] font-mono text-left border-collapse">
                            <thead className="bg-gray-950 text-gray-400 uppercase tracking-wider text-[9px] border-b border-gray-800">
                              <tr>
                                {Object.keys(msg.data[0]).map((k) => (
                                  <th key={k} className="px-3 py-2 border-r border-gray-850 last:border-0">{k}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {msg.data.slice(0, 10).map((row, ri) => (
                                <tr key={ri} className="border-t border-gray-850 hover:bg-gray-950/20 last:border-0">
                                  {Object.values(row).map((v, ci) => (
                                    <td key={ci} className="px-3 py-2 text-gray-300 border-r border-gray-850 last:border-0">
                                      {v === null ? "NULL" : String(v)}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Input Bar Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk(input);
          }}
          className="flex gap-2 border-t border-gray-800/60 pt-4"
        >
          <div className="relative flex-1 flex">
            <span className="absolute left-4 top-3 text-red-500 font-mono text-sm pointer-events-none">&gt;</span>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Enter query for BTP traffic database..."
              disabled={loading}
              className="flex-1 bg-gray-900 border border-gray-800 rounded-lg pl-8 pr-4 py-3 text-white text-sm focus:outline-none focus:border-red-800 focus:ring-1 focus:ring-red-800 font-mono"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:bg-gray-800 text-white px-6 py-3 rounded-lg text-sm font-bold tracking-wide uppercase transition-colors shrink-0 border border-red-600/30"
          >
            Run Query
          </button>
        </form>
      </div>
    </div>
  );
}
