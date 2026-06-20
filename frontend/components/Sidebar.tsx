"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Dashboard", icon: "🗺️" },
  { href: "/forecast", label: "Forecast", icon: "📈" },
  { href: "/enforcement", label: "Enforcement", icon: "👮" },
  { href: "/analytics", label: "Analytics", icon: "📊" },
  { href: "/query", label: "Ask AI", icon: "💬" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-full md:w-56 shrink-0 border-b md:border-b-0 md:border-r border-gray-800 bg-gray-900 flex flex-col">
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-lg font-bold text-white">ParkSentinel</h1>
        <p className="text-xs text-gray-400 mt-1">Bengaluru Traffic Police</p>
      </div>
      <nav className="flex md:flex-col flex-row overflow-x-auto md:flex-1 p-3 gap-1 md:space-y-1">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
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
      <div className="hidden md:block p-4 border-t border-gray-800 text-xs text-gray-500">
        Gridlock Hackathon 2.0
      </div>
    </aside>
  );
}
