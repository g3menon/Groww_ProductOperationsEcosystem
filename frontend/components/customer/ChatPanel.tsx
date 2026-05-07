"use client";

import { useEffect, useRef } from "react";

import { BookingCard, type BookingSummary } from "@/components/customer/BookingCard";
import { formatShortIso } from "@/lib/formatters";

type CitationSource = {
  source_url: string;
  doc_type: string;
  title: string;
  last_checked: string;
  relevant_quote?: string | null;
};

export type ChatMessage = {
  id: string;
  session_id?: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations?: CitationSource[];
  booking?: BookingSummary;
};

interface ChatPanelProps {
  messages: ChatMessage[];
  isSending?: boolean;
  /** Keeps parent booking summaries in sync when a booking card is cancelled inside chat history. */
  onBookingUpdated?: (next: BookingSummary) => void;
}

const BOOKING_ID_PATTERN = /\bBK-\d{8}-[A-Z0-9]{4,}\b/i;

function CitationCard({ citation }: { citation: CitationSource }) {
  const label = citation.doc_type === "fee_explainer" ? "Fee explainer" : "Fund page";

  return (
    <a
      href={citation.source_url}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-2 block rounded-xl border border-groww-border bg-white px-3 py-2 text-xs shadow-sm transition hover:border-groww-accent/40 hover:bg-groww-accentSoft/40"
      aria-label={`Source: ${citation.title}`}
    >
      <div className="flex items-center gap-1.5">
        <span className="rounded-full bg-groww-surfaceSoft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-groww-muted">
          {label}
        </span>
        <span className="truncate font-semibold text-groww-text">{citation.title}</span>
      </div>
      {citation.relevant_quote ? <p className="mt-1 line-clamp-2 text-groww-muted">{citation.relevant_quote}</p> : null}
      <p className="mt-0.5 text-groww-faint">Last checked: {citation.last_checked}</p>
    </a>
  );
}

function inferredBooking(content: string): BookingSummary | null {
  const match = content.match(BOOKING_ID_PATTERN);
  return match ? { booking_id: match[0], status: "pending_advisor_approval" } : null;
}

export function ChatPanel({ messages, isSending = false, onBookingUpdated }: ChatPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isSending]);

  return (
    <div className="max-h-[52vh] min-h-[280px] space-y-4 overflow-y-auto px-1 py-2 pr-2 md:max-h-[58vh]">
      {messages.map((message) => {
        const isUser = message.role === "user";
        const booking = message.booking ?? (!isUser ? inferredBooking(message.content) : null);
        return (
          <div key={message.id} className={isUser ? "flex justify-end" : "flex justify-start"}>
            <div className={isUser ? "max-w-[82%] md:max-w-[72%]" : "max-w-[88%] md:max-w-[76%]"}>
              <div
                className={
                  isUser
                    ? "rounded-2xl rounded-br-md bg-groww-accentSoft px-4 py-3 text-sm leading-6 text-groww-text"
                    : "rounded-2xl rounded-bl-md border border-groww-border bg-white px-4 py-3 text-sm leading-6 text-groww-text shadow-sm"
                }
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
              </div>
              <p className={isUser ? "mt-1 text-right text-[11px] text-groww-faint" : "mt-1 text-[11px] text-groww-faint"}>
                {formatShortIso(message.created_at)}
              </p>
              {!isUser && booking ? <BookingCard booking={booking} onBookingUpdated={onBookingUpdated} /> : null}
              {!isUser && message.citations && message.citations.length > 0 ? (
                <div className="mt-2 space-y-1" aria-label="Sources">
                  <p className="px-1 text-[10px] font-semibold uppercase tracking-wide text-groww-faint">Sources</p>
                  {message.citations.map((citation) => (
                    <CitationCard key={citation.source_url} citation={citation} />
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}

      {isSending ? (
        <div className="flex justify-start">
          <div className="rounded-2xl rounded-bl-md border border-groww-border bg-white px-4 py-3 shadow-sm">
            <div className="flex items-center gap-1.5" aria-label="Assistant is typing">
              <span className="h-2 w-2 animate-bounce rounded-full bg-groww-accent/50" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-groww-accent/50 [animation-delay:120ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-groww-accent/50 [animation-delay:240ms]" />
            </div>
          </div>
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  );
}
