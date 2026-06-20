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
    <div className="flex flex-col h-full max-w-3xl mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Ask ParkSentinel</h1>
        <p className="text-gray-400 text-sm mt-1">
          Natural language queries over Bengaluru violation data
        </p>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => handleAsk(q)}
            disabled={loading}
            className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-full transition-colors disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-12">
            <p className="text-4xl mb-4">💬</p>
            <p>Ask a question about parking violations in Bengaluru</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i}>
            {msg.role === "user" && (
              <div className="flex justify-end">
                <div className="bg-red-600 text-white rounded-2xl rounded-tr-sm px-4 py-2 max-w-sm text-sm">
                  {msg.question}
                </div>
              </div>
            )}
            {msg.role === "assistant" && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-sm space-y-3">
                {msg.loading ? (
                  <div className="flex items-center gap-2 text-gray-400">
                    <div className="animate-spin w-4 h-4 border-2 border-red-500 border-t-transparent rounded-full" />
                    Analyzing...
                  </div>
                ) : (
                  <>
                    <p className="text-white">{msg.answer}</p>
                    {msg.sql && (
                      <details className="text-xs">
                        <summary className="text-gray-500 cursor-pointer">View SQL</summary>
                        <pre className="mt-2 bg-gray-950 p-3 rounded-lg text-green-400 overflow-x-auto">
                          {msg.sql}
                        </pre>
                      </details>
                    )}
                    {msg.data && msg.data.length > 0 && (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-gray-400">
                              {Object.keys(msg.data[0]).map((k) => (
                                <th key={k} className="text-left px-2 py-1">{k}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {msg.data.slice(0, 10).map((row, ri) => (
                              <tr key={ri} className="border-t border-gray-800">
                                {Object.values(row).map((v, ci) => (
                                  <td key={ci} className="px-2 py-1 text-gray-300">{String(v)}</td>
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

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleAsk(input);
        }}
        className="flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about parking violations..."
          disabled={loading}
          className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-red-500"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white px-6 py-3 rounded-xl text-sm font-medium"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
