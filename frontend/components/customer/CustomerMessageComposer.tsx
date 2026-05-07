"use client";

import type { ReactNode } from "react";

import type { PromptChip } from "@/components/customer/PromptChips";
import { SendIcon } from "@/components/customer/SendIcon";
import { VoiceControls } from "@/components/customer/VoiceControls";
import { isFundComparisonPrompt } from "@/lib/fund-comparison-guard";

type CustomerMessageComposerProps = {
  chips: PromptChip[];
  sending: boolean;
  onChipSend: (prompt: string) => void;
  onBookAdvisor: () => void;
  /** Optional actions (e.g. cancel latest booking) shown as compact quick replies like AIAppointmentScheduler. */
  quickActions?: { id: string; label: string; onClick: () => void; disabled?: boolean }[];
  input: string;
  voiceInterim: string;
  onInputChange: (value: string) => void;
  onSendText: () => void;
  canSend: boolean;
  voiceActive: boolean;
  voiceUnsupported: boolean;
  voiceError: string | null;
  onVoiceToggle: () => void;
  /** Reserved for a future non–Web Speech pipeline; keeps layout stable when enabled. */
  voiceExtensionSlot?: ReactNode;
};

/**
 * Single composer surface: prompt chips, typing, and voice toggle together (Architecture.md — not mutually exclusive).
 * Voice recognition implementation may evolve; Web Speech stays behind VoiceControls until a richer SDK lands.
 */
export function CustomerMessageComposer({
  chips,
  sending,
  onChipSend,
  onBookAdvisor,
  quickActions,
  input,
  voiceInterim,
  onInputChange,
  onSendText,
  canSend,
  voiceActive,
  voiceUnsupported,
  voiceError,
  onVoiceToggle,
  voiceExtensionSlot,
}: CustomerMessageComposerProps) {
  const displayValue = voiceInterim ? `${input}${input.trim() ? " " : ""}${voiceInterim}` : input;

  return (
    <div className="border-t border-groww-border pt-4">
      <div className="mb-3 space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-groww-faint">Continue this conversation</p>
        <p className="text-xs text-groww-muted">
          Use suggestions, type, or voice together — switch anytime in the same thread.
        </p>
      </div>

      {quickActions && quickActions.length > 0 ? (
        <div className="mb-3 space-y-2 rounded-xl border border-groww-border/80 bg-groww-surfaceSoft/50 px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-groww-faint">Next step</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Quick booking actions">
            {quickActions.map((action) => (
              <button
                key={action.id}
                type="button"
                className="rounded-full border border-groww-border bg-white px-3 py-1.5 text-xs font-semibold text-groww-text shadow-sm transition hover:border-groww-accent/50 hover:text-groww-accent disabled:opacity-50"
                onClick={action.onClick}
                disabled={Boolean(action.disabled || sending)}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex flex-wrap gap-2">
        {chips
          .filter((c) => !isFundComparisonPrompt(c.prompt))
          .slice(0, 6)
          .map((chip) => (
            <button key={chip.id} type="button" className="pill-chip" onClick={() => onChipSend(chip.prompt)} disabled={sending}>
              {chip.label}
            </button>
          ))}
      </div>

      <label htmlFor="customer-composer" className="sr-only">
        Ask Groww AI
      </label>
      <div
        role="group"
        aria-label="Message composer: text input and voice"
        className={
          voiceActive
            ? "rounded-2xl border border-groww-accent bg-white p-3 shadow-card"
            : "rounded-2xl border border-groww-border bg-white p-3 shadow-sm"
        }
      >
        <textarea
          id="customer-composer"
          value={displayValue}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Ask about NAV, fees, mutual fund basics, or booking an advisor..."
          className="min-h-[88px] w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-groww-text placeholder:text-groww-faint focus:outline-none"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (canSend) onSendText();
            }
          }}
        />
        <div className="flex flex-col gap-3 border-t border-groww-border pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="hidden text-[10px] font-semibold uppercase tracking-wide text-groww-faint sm:inline">Speak</span>
              <VoiceControls active={voiceActive} unsupported={voiceUnsupported} onToggle={onVoiceToggle} />
              {voiceExtensionSlot ? (
                <span className="flex items-center border-l border-groww-border pl-3">{voiceExtensionSlot}</span>
              ) : null}
            </div>
            <div className="hidden h-6 w-px bg-groww-border sm:block" aria-hidden />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-groww-faint">
              Voice fills the box · edit text anytime · Enter to send
            </span>
          </div>
          <div className="flex items-center justify-end gap-2 sm:shrink-0">
            <button type="button" className="pill-chip" onClick={onBookAdvisor} disabled={sending}>
              Book advisor
            </button>
            <button
              type="button"
              className="focus-ring flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-groww-accent text-white shadow-card transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onSendText}
              disabled={!canSend}
              aria-label="Send message"
            >
              {sending ? (
                <span className="text-xs font-semibold" aria-hidden>
                  …
                </span>
              ) : (
                <SendIcon className="h-5 w-5" />
              )}
            </button>
          </div>
        </div>
      </div>

      {voiceError ? <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700">{voiceError}</p> : null}
    </div>
  );
}
