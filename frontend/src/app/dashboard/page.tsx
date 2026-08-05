"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  PhoneCall,
  Activity,
  Clock,
  Calendar,
  RefreshCw,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  PhoneIncoming,
  PhoneOutgoing,
  ExternalLink,
  Loader2,
  AlertCircle,
} from "lucide-react";
import CallDetailModal from "@/components/CallDetailModal";

interface SummaryData {
  total_calls: number;
  active_calls_count: number;
  calls_today: number;
  total_talk_time_seconds: number;
}

interface CallItem {
  id: string;
  call_sid: string;
  from_number: string;
  to_number: string;
  status: string;
  direction: string;
  duration: number | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

interface PaginatedCallsResponse {
  data: CallItem[];
  pagination: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
}

export default function DashboardPage() {
  const router = useRouter();

  // State
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [callsData, setCallsData] = useState<PaginatedCallsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Pagination & Sorting
  const [offset, setOffset] = useState(0);
  const limit = 10;
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // Countdown timer for auto-refresh
  const REFRESH_INTERVAL = 12; // seconds
  const [secondsUntilRefresh, setSecondsUntilRefresh] = useState(REFRESH_INTERVAL);

  // Modal
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);

  // Fetch Dashboard Data
  const fetchData = useCallback(
    async (isManualRefresh = false) => {
      if (isManualRefresh) setRefreshing(true);

      try {
        const [summaryRes, callsRes] = await Promise.all([
          fetch("/api/dashboard/summary"),
          fetch(`/api/calls?limit=${limit}&offset=${offset}&sort_by=started_at&sort_order=${sortOrder}`),
        ]);

        if (summaryRes.status === 401 || callsRes.status === 401) {
          router.push("/login");
          return;
        }

        if (!summaryRes.ok || !callsRes.ok) {
          throw new Error("Failed to load dashboard metrics");
        }

        const summaryJson = await summaryRes.json();
        const callsJson = await callsRes.json();

        setSummary(summaryJson);
        setCallsData(callsJson);
        setError(null);
      } catch (err: unknown) {
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("Failed to communicate with API server");
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [limit, offset, sortOrder, router]
  );

  // Initial load and dependency-triggered fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh interval timer (12 seconds)
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsUntilRefresh((prev) => {
        if (prev <= 1) {
          fetchData();
          return REFRESH_INTERVAL;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [fetchData]);

  const handleManualRefresh = () => {
    setSecondsUntilRefresh(REFRESH_INTERVAL);
    fetchData(true);
  };

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  };

  const toggleSortOrder = () => {
    setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"));
  };

  const formatSeconds = (totalSec: number) => {
    if (!totalSec || totalSec <= 0) return "0s";
    const hrs = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;

    const parts = [];
    if (hrs > 0) parts.push(`${hrs}h`);
    if (mins > 0 || hrs > 0) parts.push(`${mins}m`);
    parts.push(`${secs}s`);
    return parts.join(" ");
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "N/A";
    return new Date(dateStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const getStatusBadge = (statusStr: string) => {
    switch (statusStr.toLowerCase()) {
      case "active":
      case "in-progress":
        return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 font-medium";
      case "completed":
        return "bg-blue-500/15 text-blue-400 border-blue-500/30 font-medium";
      case "failed":
        return "bg-red-500/15 text-red-400 border-red-500/30 font-medium";
      default:
        return "bg-slate-500/15 text-slate-400 border-slate-500/30 font-medium";
    }
  };

  const currentPage = Math.floor(offset / limit) + 1;
  const totalCalls = callsData?.pagination.total || 0;
  const totalPages = Math.ceil(totalCalls / limit) || 1;

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100 flex flex-col">
      {/* Top Header */}
      <header className="sticky top-0 z-30 glass-panel border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400">
              <PhoneCall className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-slate-100 flex items-center gap-2">
                AI Voice Calling Platform
                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-mono">
                  Admin v1.0
                </span>
              </h1>
              <p className="text-xs text-slate-400">Live Webhook Call Operations & Transcripts</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Auto Refresh Badge */}
            <div className="hidden sm:flex items-center gap-2 text-xs text-slate-400 bg-slate-900/60 border border-slate-800 px-3 py-1.5 rounded-xl">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Live Update in <strong className="text-slate-200">{secondsUntilRefresh}s</strong></span>
            </div>

            {/* Manual Refresh */}
            <button
              onClick={handleManualRefresh}
              disabled={refreshing}
              title="Refresh Data"
              className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin text-indigo-400" : ""}`} />
            </button>

            {/* Logout */}
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 text-xs font-medium transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {error && (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-3">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Metric Summary Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Total Calls */}
          <div className="glass-card glass-card-hover rounded-2xl p-5 border border-slate-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Total Calls
              </span>
              <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <PhoneCall className="w-4 h-4" />
              </div>
            </div>
            <div className="text-3xl font-extrabold text-slate-100 tracking-tight">
              {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500" /> : summary?.total_calls ?? 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">All time processed calls</p>
          </div>

          {/* Card 2: Active Calls */}
          <div className="glass-card glass-card-hover rounded-2xl p-5 border border-slate-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Active Calls
              </span>
              <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 relative">
                <Activity className="w-4 h-4" />
                {(summary?.active_calls_count ?? 0) > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                )}
              </div>
            </div>
            <div className="text-3xl font-extrabold text-emerald-400 tracking-tight flex items-center gap-2">
              {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500" /> : summary?.active_calls_count ?? 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">Currently in progress</p>
          </div>

          {/* Card 3: Calls Today */}
          <div className="glass-card glass-card-hover rounded-2xl p-5 border border-slate-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Calls Today
              </span>
              <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                <Calendar className="w-4 h-4" />
              </div>
            </div>
            <div className="text-3xl font-extrabold text-slate-100 tracking-tight">
              {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500" /> : summary?.calls_today ?? 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">UTC midnight to present</p>
          </div>

          {/* Card 4: Total Talk Time */}
          <div className="glass-card glass-card-hover rounded-2xl p-5 border border-slate-800">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Total Talk Time
              </span>
              <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
                <Clock className="w-4 h-4" />
              </div>
            </div>
            <div className="text-3xl font-extrabold text-purple-300 tracking-tight">
              {loading ? (
                <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
              ) : (
                formatSeconds(summary?.total_talk_time_seconds ?? 0)
              )}
            </div>
            <p className="text-xs text-slate-500 mt-1">Cumulative duration</p>
          </div>
        </div>

        {/* Calls Section Header & Table Container */}
        <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
          {/* Section Header */}
          <div className="px-6 py-5 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900/40">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Call History & Active Sessions</h2>
              <p className="text-xs text-slate-400 mt-0.5">Click any row to inspect conversation transcripts</p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={toggleSortOrder}
                className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-300 border border-slate-700 transition-colors"
              >
                <ArrowUpDown className="w-3.5 h-3.5" />
                <span>Start Time: <strong className="uppercase">{sortOrder}</strong></span>
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto custom-scrollbar">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/80 uppercase tracking-wider text-[11px] text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-6 py-3.5 font-semibold">Direction</th>
                  <th className="px-6 py-3.5 font-semibold">From / To</th>
                  <th className="px-6 py-3.5 font-semibold">Status</th>
                  <th className="px-6 py-3.5 font-semibold">Start Time</th>
                  <th className="px-6 py-3.5 font-semibold">Duration</th>
                  <th className="px-6 py-3.5 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading && !callsData ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-16 text-center text-slate-500">
                      <div className="flex flex-col items-center justify-center gap-2">
                        <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                        <span>Loading calls list...</span>
                      </div>
                    </td>
                  </tr>
                ) : !callsData?.data || callsData.data.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-16 text-center text-slate-500">
                      No calls recorded yet. Incoming webhooks will appear here.
                    </td>
                  </tr>
                ) : (
                  callsData.data.map((call) => {
                    const isInbound = call.direction === "inbound";
                    return (
                      <tr
                        key={call.id}
                        onClick={() => setSelectedCallId(call.id)}
                        className="hover:bg-slate-800/40 cursor-pointer transition-colors group"
                      >
                        <td className="px-6 py-4 font-medium text-slate-200">
                          <div className="flex items-center gap-2">
                            {isInbound ? (
                              <PhoneIncoming className="w-4 h-4 text-emerald-400" />
                            ) : (
                              <PhoneOutgoing className="w-4 h-4 text-blue-400" />
                            )}
                            <span className="capitalize">{call.direction}</span>
                          </div>
                        </td>

                        <td className="px-6 py-4">
                          <div className="font-mono text-slate-200">{call.from_number}</div>
                          <div className="text-[11px] text-slate-500 font-mono">→ {call.to_number}</div>
                        </td>

                        <td className="px-6 py-4">
                          <span
                            className={`inline-block px-2.5 py-1 rounded-full border text-[11px] capitalize ${getStatusBadge(
                              call.status
                            )}`}
                          >
                            {call.status}
                          </span>
                        </td>

                        <td className="px-6 py-4 text-slate-300 whitespace-nowrap">
                          {formatDate(call.started_at || call.created_at)}
                        </td>

                        <td className="px-6 py-4 text-slate-300 whitespace-nowrap font-mono">
                          {call.duration !== null ? `${call.duration}s` : <span className="text-emerald-400 italic font-sans text-xs">Live</span>}
                        </td>

                        <td className="px-6 py-4 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedCallId(call.id);
                            }}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 text-xs transition-colors"
                          >
                            <span>Transcript</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Table Pagination Footer */}
          <div className="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-400">
            <div>
              Showing <strong className="text-slate-200">{offset + 1}</strong> to{" "}
              <strong className="text-slate-200">
                {Math.min(offset + limit, totalCalls)}
              </strong>{" "}
              of <strong className="text-slate-200">{totalCalls}</strong> calls
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                disabled={offset === 0}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                <span>Prev</span>
              </button>

              <span className="px-2 font-mono text-slate-300">
                Page {currentPage} / {totalPages}
              </span>

              <button
                onClick={() => setOffset((prev) => prev + limit)}
                disabled={!callsData?.pagination.has_more}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <span>Next</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* Call Detail Modal */}
      <CallDetailModal
        callId={selectedCallId}
        onClose={() => setSelectedCallId(null)}
      />
    </div>
  );
}
