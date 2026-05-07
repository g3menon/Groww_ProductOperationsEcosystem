"use client";

import { isFundComparisonPrompt } from "@/lib/fund-comparison-guard";

export type PromptChip = { id: string; label: string; prompt: string };

interface PromptChipsProps {
  chips: PromptChip[];
  disabled: boolean;
  onSend: (prompt: string) => void;
}

export const FALLBACK_PROMPTS: PromptChip[] = [
  {
    id: "fallback-nav",
    label: "Check NAV",
    prompt: "What is the NAV of HDFC Flexi Cap Direct Plan Growth?",
  },
  {
    id: "fallback-sip-basics",
    label: "SIP basics",
    prompt: "What is a SIP and how does it work with mutual funds?",
  },
  {
    id: "fallback-expense",
    label: "Expense ratio",
    prompt: "Explain expense ratio in simple words",
  },
  {
    id: "fallback-book",
    label: "Book advisor",
    prompt: "Book an appointment with an advisor",
  },
  {
    id: "fallback-cancel",
    label: "Cancel booking",
    prompt: "Cancel my booking",
  },
];

export function PromptChips({ chips, disabled, onSend }: PromptChipsProps) {
  const visibleChips = (chips.length > 0 ? chips : FALLBACK_PROMPTS).filter((c) => !isFundComparisonPrompt(c.prompt));

  return (
    <div className="flex flex-wrap justify-center gap-2">
      {visibleChips.map((chip) => (
        <button
          key={chip.id}
          type="button"
          className="pill-chip"
          onClick={() => onSend(chip.prompt)}
          disabled={disabled}
          aria-label={`Send prompt: ${chip.label}`}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
