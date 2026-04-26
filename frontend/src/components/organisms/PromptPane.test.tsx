import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PromptPane } from "./PromptPane";
import type { Session } from "@/api/sessions";
import * as promptsApi from "@/api/prompts";
import * as libraryApi from "@/api/library";

const session: Session = {
  id: "ses1",
  project_id: "p1",
  name: "s",
  model_name: "m1",
  use_negative: true,
  pinned_loras: [{ lora_name: "pinned-x", weight_override: null }],
  source_image_path: null,
  source_image_url: null,
  vl_summary: "summary",
  vl_model_name: null,
  prompt_model_name: "pm-1",
  created_at: 0,
  updated_at: 0,
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.spyOn(libraryApi, "useLoras").mockReturnValue({
    data: [
      {
        name: "lora-known",
        display_name: "lora-known",
        description: "",
        tags: [],
        trigger_words: ["k_t"],
        family_id: "sdxl",
        recommended_weight: 0.5,
        author: null, version: null, source_url: null,
        created_at: 0, updated_at: 0, is_indexed: true,
      },
    ] as libraryApi.Lora[],
  } as unknown as ReturnType<typeof libraryApi.useLoras>);
});

describe("PromptPane", () => {
  it("renders empty state when no prompts and disables generate without vl_summary", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={{ ...session, vl_summary: null }} />);
    expect(screen.getByText(/No prompt yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate/i })).toBeDisabled();
  });

  it("renders positive, negative, and known + unknown LoRA badges", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [
        {
          id: 1,
          session_id: session.id,
          prompt: {
            positive: "moody girl",
            negative: "blurry",
            loras: [
              { name: "lora-known", weight: 0.5 },
              { name: "ghost-lora", weight: 0.7 },
            ],
          },
          intents: [{ kind: "style", query: "moody" }],
          retrieved: [{ intent_index: 0, intent_query: "moody", results: [{ name: "lora-known", distance: 0.1 }] }],
          created_at: 0,
        },
      ],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(), isPending: false, error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    expect(screen.getByDisplayValue("moody girl")).toBeInTheDocument();
    expect(screen.getByDisplayValue("blurry")).toBeInTheDocument();
    expect(screen.getByText("lora-known")).toBeInTheDocument();
    expect(screen.getByText("ghost-lora")).toBeInTheDocument();
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  it("calls generate when Regenerate is clicked", () => {
    const mutate = vi.fn();
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [{
        id: 9, session_id: session.id, intents: null, retrieved: null,
        prompt: { positive: "p", negative: "n", loras: [] }, created_at: 0,
      }],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate, isPending: false, error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("renders error from generate mutation", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(), isPending: false, error: new Error("boom"),
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
});
