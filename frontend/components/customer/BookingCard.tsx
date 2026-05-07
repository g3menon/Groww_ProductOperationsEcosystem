"use client";

import { useState } from "react";

import { fetchJson } from "@/lib/api-client";
import { bookingStatusLabel, isBookingCancellable } from "@/lib/booking-status";

export type BookingSummary = {
  booking_id: string;
  preferred_date?: string;
  preferred_time?: string;
  display_timezone?: string;
  status?: string;
  issue_summary?: string;
  booking_reason?: string;
};

type BookingDetail = BookingSummary & Record<string, unknown>;

export function BookingCard({
  booking,
  onBookingUpdated,
}: {
  booking: BookingSummary;
  /** Called after a successful cancel so parent state (e.g. lastBooking) stays in sync. */
  onBookingUpdated?: (next: BookingSummary) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const slot = [booking.preferred_date, booking.preferred_time].filter(Boolean).join(" at ");
  const status = booking.status ?? "pending_advisor_approval";
  const cancellable = isBookingCancellable(status);
  const cancelled = status === "cancelled";

  const copyBookingId = async () => {
    await navigator.clipboard.writeText(booking.booking_id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const cancelBooking = async () => {
    if (!cancellable || cancelBusy) return;
    const ok = window.confirm(`Cancel booking ${booking.booking_id}?`);
    if (!ok) return;
    setCancelBusy(true);
    setCancelError(null);
    try {
      const response = await fetchJson<BookingDetail>("/api/v1/booking/cancel", {
        method: "POST",
        body: JSON.stringify({
          booking_id: booking.booking_id,
          reason: "Customer cancelled from booking card.",
        }),
      });
      const next = response.data;
      if (next?.booking_id) {
        const merged: BookingSummary = {
          ...booking,
          ...next,
          booking_reason: booking.booking_reason ?? (next as BookingSummary).booking_reason,
        };
        onBookingUpdated?.(merged);
      }
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : "Could not cancel this booking.");
    } finally {
      setCancelBusy(false);
    }
  };

  const badgeClass = cancelled
    ? "bg-stone-100 text-stone-700"
    : status === "approved" || status === "confirmation_sent"
      ? "bg-sky-100 text-sky-800"
      : "bg-emerald-100 text-emerald-700";

  return (
    <div
      className={
        cancelled
          ? "mt-3 rounded-2xl border border-stone-200 bg-gradient-to-br from-stone-50 to-white p-4 shadow-sm"
          : "mt-3 rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-4 shadow-sm"
      }
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${badgeClass}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
            {bookingStatusLabel(status)}
          </div>
          <h4 className="mt-3 text-sm font-semibold text-groww-text">
            {cancelled ? "Booking cancelled" : "Advisor request"}
          </h4>
          {slot ? (
            <p className="mt-1 text-sm text-groww-muted">
              Requested slot: {slot} {booking.display_timezone ?? "IST"}
            </p>
          ) : null}
          {booking.booking_reason ? (
            <p className="mt-2 text-sm font-semibold text-groww-text">Reason: {booking.booking_reason}</p>
          ) : null}
          {booking.issue_summary ? <p className="mt-2 text-sm leading-6 text-groww-muted">{booking.issue_summary}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="focus-ring rounded-full border border-groww-border bg-white px-3 py-2 text-xs font-semibold text-groww-accent shadow-sm hover:bg-groww-accentSoft"
            onClick={() => void copyBookingId()}
          >
            {copied ? "Copied" : "Copy ID"}
          </button>
          {cancellable ? (
            <button
              type="button"
              className="focus-ring rounded-full border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 shadow-sm hover:bg-red-50 disabled:opacity-50"
              onClick={() => void cancelBooking()}
              disabled={cancelBusy}
            >
              {cancelBusy ? "Cancelling…" : "Cancel booking"}
            </button>
          ) : null}
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-groww-border bg-white px-3 py-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-groww-faint">Booking ID</p>
        <p className="mt-1 font-mono text-sm font-semibold text-groww-text">{booking.booking_id}</p>
      </div>
      {cancelError ? <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{cancelError}</p> : null}
    </div>
  );
}
