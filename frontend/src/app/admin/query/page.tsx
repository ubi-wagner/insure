"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import UserMenu from "@/components/UserMenu";

interface Preset { name: string; description: string; sql: string }
interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated?: boolean;
  error?: string;
}

export default function SqlQueryPage() {
  const { isAdmin, loading: authLoading } = useAuth();
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);

  useEffect(() => {
    fetch("/api/proxy/admin/sql/presets")
      .then((r) => r.json())
      .then((d) => setPresets(d.presets ?? []))
      .catch(() => {});
  }, []);

  async function runQuery() {
    if (!sql.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch("/api/proxy/admin/sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql, limit: 500 }),
      });
      setResult(await res.json());
    } catch (err) {
      setResult({ columns: [], rows: [], row_count: 0, error: String(err) });
    }
    setRunning(false);
  }

  if (authLoading) return null;
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 text-lg mb-2">Admin access required</p>
          <Link href="/" className="text-blue-400 text-sm">Back to Dashboard</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/ops" className="text-blue-400 hover:text-blue-300 text-xs">&larr; Ops</Link>
          <h1 className="text-base font-bold tracking-tight">SQL Query Tool</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/" className="text-gray-500 hover:text-white text-xs">Dashboard</Link>
          <Link href="/help" className="text-blue-400 hover:text-blue-300 text-xs font-medium">? Help</Link>
          <UserMenu />
        </div>
      </header>

      <div className="flex max-w-7xl mx-auto">
        {/* Preset sidebar */}
        <div className="hidden md:block w-56 shrink-0 border-r border-gray-800 px-3 py-4 space-y-1 overflow-y-auto max-h-[calc(100vh-57px)]">
          <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-2">Canned Queries</p>
          {presets.map((p) => (
            <button
              key={p.name}
              onClick={() => setSql(p.sql)}
              className="block w-full text-left px-2 py-1.5 rounded text-xs hover:bg-gray-800/50 transition-colors"
            >
              <span className="text-gray-300 font-medium">{p.name}</span>
              <br />
              <span className="text-gray-600 text-[10px]">{p.description}</span>
            </button>
          ))}
        </div>

        {/* Main query area */}
        <div className="flex-1 px-4 md:px-6 py-4 space-y-4">
          {/* Mobile preset dropdown */}
          <div className="md:hidden">
            <select
              onChange={(e) => {
                const p = presets.find((x) => x.name === e.target.value);
                if (p) setSql(p.sql);
              }}
              className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-3 py-2"
              defaultValue=""
            >
              <option value="" disabled>Load a canned query...</option>
              {presets.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* SQL editor */}
          <div>
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runQuery();
              }}
              placeholder="SELECT * FROM entities LIMIT 10"
              rows={6}
              className="w-full bg-gray-900 border border-gray-700 text-white text-xs font-mono rounded-lg px-4 py-3 placeholder-gray-600 focus:outline-none focus:border-blue-600 resize-y"
            />
            <div className="flex items-center justify-between mt-2">
              <p className="text-[10px] text-gray-600">
                Read-only. SELECT/WITH/EXPLAIN only. Max 500 rows. Ctrl+Enter to run.
              </p>
              <button
                onClick={runQuery}
                disabled={running || !sql.trim()}
                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-5 py-2 rounded font-medium"
              >
                {running ? "Running..." : "Run Query"}
              </button>
            </div>
          </div>

          {/* Results */}
          {result?.error && (
            <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-3">
              <p className="text-red-300 text-xs font-medium mb-1">Query Error</p>
              <pre className="text-red-400 text-[11px] whitespace-pre-wrap font-mono">{result.error}</pre>
            </div>
          )}

          {result && !result.error && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-gray-500 text-xs">
                  {result.row_count} row{result.row_count !== 1 ? "s" : ""}
                  {result.truncated ? " (truncated at limit)" : ""}
                </p>
                <button
                  onClick={() => {
                    const csv = [result.columns.join(","), ...result.rows.map((r) => result.columns.map((c) => JSON.stringify(r[c] ?? "")).join(","))].join("\n");
                    const blob = new Blob([csv], { type: "text/csv" });
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = "query_results.csv";
                    a.click();
                  }}
                  className="text-gray-500 hover:text-white text-[10px]"
                >
                  Export CSV
                </button>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-auto max-h-[60vh]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900 z-10">
                    <tr className="border-b border-gray-800">
                      {result.columns.map((col) => (
                        <th key={col} className="text-left px-3 py-2 text-gray-500 whitespace-nowrap font-medium">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                        {result.columns.map((col) => (
                          <td key={col} className="px-3 py-1.5 text-gray-400 truncate max-w-[300px] font-mono">
                            {row[col] != null ? String(row[col]) : <span className="text-gray-700">null</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
