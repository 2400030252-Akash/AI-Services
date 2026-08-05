"use client";

import { useEffect, useState } from "react";
import { X, Phone, Clock, User, Bot, AlertCircle, Loader2 } from "lucide-react";

interface ConversationTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface CallDetailData {
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
  conversations: ConversationTurn[];
}

interface CallDetailModalProps {
  callId: string | null;
  onClose: () => void;
}

export default function CallDetailModal({ callId, onClose }: CallDetailModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<CallDetailData | null>(null);

  useEffect(() => {
    if (!callId) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetch(`/api/calls/${callId}/conversation`)
      .then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.message || "Failed to load call transcript");
        }
        return res.json();
      })
      .then((resData) => {
        if (isMounted) {
          setData(resData);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (isMounted) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [callId]);

  if (!callId) return null;

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
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      case "completed":
        return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      case "failed":
        return "bg-red-500/10 text-red-400 border-red-500/30";
      default:
        return "bg-slate-500/10 text-slate-400 border-slate-500/30";
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-3xl glass-panel rounded-2xl border border-slate-800 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Phone className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                Call Transcript
                {data && (
                  <span
                    className={`text-xs px-2.5 py-0.5 rounded-full border capitalize font-medium ${getStatusBadge(
                      data.status
                    )}`}
                  >
                    {data.status}
                  </span>
                )}
              </h2>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                {callId}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center text-slate-400 gap-3">
              <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
              <p className="text-sm">Loading transcript...</p>
            </div>
          ) : error ? (
            <div className="py-12 px-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex flex-col items-center text-center gap-2">
              <AlertCircle className="w-8 h-8" />
              <p className="font-medium text-sm">{error}</p>
            </div>
          ) : data ? (
            <>
              {/* Call Overview Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 text-xs">
                <div>
                  <span className="text-slate-500 block mb-1">From</span>
                  <span className="font-mono text-slate-200">{data.from_number}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-1">To</span>
                  <span className="font-mono text-slate-200">{data.to_number}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-1">Duration</span>
                  <span className="font-medium text-slate-200 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    {data.duration !== null ? `${data.duration}s` : "In Progress"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-1">Started At</span>
                  <span className="text-slate-300">{formatDate(data.started_at)}</span>
                </div>
              </div>

              {/* Transcript Messages Feed */}
              <div className="space-y-4 pt-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
                  Conversation Log ({data.conversations?.length || 0} messages)
                </h3>

                {!data.conversations || data.conversations.length === 0 ? (
                  <div className="py-12 text-center text-slate-500 text-sm italic border border-dashed border-slate-800 rounded-xl">
                    No transcript entries recorded for this call.
                  </div>
                ) : (
                  data.conversations.map((turn) => {
                    const isUser = turn.role === "user";
                    return (
                      <div
                        key={turn.id}
                        className={`flex gap-3 ${
                          isUser ? "justify-start" : "justify-end"
                        }`}
                      >
                        {isUser && (
                          <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 shrink-0">
                            <User className="w-4 h-4" />
                          </div>
                        )}

                        <div
                          className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm shadow-md ${
                            isUser
                              ? "bg-slate-800/90 text-slate-100 border border-slate-700/60 rounded-tl-none"
                              : "bg-indigo-600/20 text-indigo-100 border border-indigo-500/30 rounded-tr-none"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-4 mb-1 text-[11px] opacity-75">
                            <span className="font-semibold uppercase tracking-wide">
                              {isUser ? "Caller" : "AI Voice Assistant"}
                            </span>
                            <span>{formatDate(turn.created_at)}</span>
                          </div>
                          <p className="leading-relaxed whitespace-pre-wrap">
                            {turn.content}
                          </p>
                        </div>

                        {!isUser && (
                          <div className="w-8 h-8 rounded-full bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center text-indigo-300 shrink-0">
                            <Bot className="w-4 h-4" />
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
