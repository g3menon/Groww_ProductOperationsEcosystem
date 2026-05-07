/** Mirrors backend CANCELABLE_STATES (app/schemas/booking.py). */

export const BOOKING_CANCELLABLE_STATUSES = new Set([
  "draft",
  "collecting_details",
  "pending_advisor_approval",
  "approved",
  "confirmation_sent",
]);

export function isBookingCancellable(status?: string | null): boolean {
  if (!status) return false;
  return BOOKING_CANCELLABLE_STATUSES.has(status);
}

export function bookingStatusLabel(status?: string | null): string {
  switch (status) {
    case "pending_advisor_approval":
      return "Pending advisor approval";
    case "approved":
      return "Approved";
    case "confirmation_sent":
      return "Confirmation sent";
    case "cancelled":
      return "Cancelled";
    case "rejected":
      return "Rejected";
    case "completed":
      return "Completed";
    default:
      return status ? status.replace(/_/g, " ") : "Booking";
  }
}
