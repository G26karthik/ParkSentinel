"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV = [
  { href: "/", label: "Dashboard", icon: "🗺️" },
  { href: "/forecast", label: "Forecast", icon: "📈" },
  { href: "/enforcement", label: "Enforcement", icon: "👮" },
  { href: "/analytics", label: "Analytics", icon: "📊" },
  { href: "/query", label: "Ask AI", icon: "💬" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {/* Mobile Top Bar */}
      <div className="md:hidden flex items-center justify-between p-4 border-b border-gray-800 bg-gray-900 shrink-0">
        <div>
          <h1 className="text-lg font-bold text-white">ParkSentinel</h1>
          <p className="text-xs text-gray-400 mt-1">Bengaluru Traffic Police</p>
        </div>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="text-gray-400 hover:text-white p-2"
          aria-label="Toggle Navigation"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {isOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Backdrop for mobile */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-40 md:hidden" 
          onClick={() => setIsOpen(false)}
        />
      )}

      {/* Sidebar Content */}
      <aside className={`
        fixed inset-y-0 left-0 z-50 w-64 bg-gray-900 border-r border-gray-800 flex flex-col transform transition-transform duration-300 ease-in-out
        md:relative md:w-56 md:translate-x-0 md:z-auto
        ${isOpen ? "translate-x-0" : "-translate-x-full"}
      `}>
        <div className="hidden md:block p-4 border-b border-gray-800 shrink-0">
          <h1 className="text-lg font-bold text-white">ParkSentinel</h1>
          <p className="text-xs text-gray-400 mt-1">Bengaluru Traffic Police</p>
        </div>
        
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setIsOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors whitespace-nowrap ${
                  active
                    ? "bg-red-600/20 text-red-400 font-medium"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`}
              >
                <span>{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-4 border-t border-gray-800 text-[10px] text-gray-500 shrink-0 space-y-1.5 bg-gray-950/20">
          <div className="text-gray-400 font-semibold uppercase tracking-wider text-[9px]">Branding & Systems</div>
          <div className="text-gray-500 leading-normal">
            Designed for Bengaluru Traffic Police (BTP) & ASTRAM integration (simulation environment).
          </div>
          <div className="text-gray-600 border-t border-gray-800/40 pt-1.5">
            Gridlock Hackathon 2.0
          </div>
        </div>
      </aside>
    </>
  );
}
