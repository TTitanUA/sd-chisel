import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PromptPane } from "./PromptPane";
import type { Session } from "@/api/sessions";
import * as promptsApi from "@/api/prompts";
import * as libraryApi from "@/api/library";
import * as tasksApi from "@/api/tasks";

vi.mock("./GenerateModal", () => ({
  GenerateModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="generate-modal">modal</div> : null,
}));

const session: Session = {
  id: "ses1",
  project_id: "p1",
  name: "s",
  session_type: "i2i",
  model_name: "m1",
  use_negative: true,
  pinned_loras: [{ lora_name: "pinned-x", weight_override: null }],
  source_images: [
    {
      id: "img1",
      session_id: "ses1",
      path: "images/ses1/sources/img1.png",
      url: "/media/images/ses1/sources/img1.png",
      original_filename: "main.png",
      image_number: 1,
      is_main: true,
      analysis: "summary",
      analysis_prompt: null,
      created_at: 0,
      updated_at: 0,
    },
  ],
  vl_model_name: null,
  prompt_model_name: "pm-1",
  hidden: false,
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
        hidden: false,
        created_at: 0, updated_at: 0, is_indexed: true,
      },
    ] as libraryApi.Lora[],
  } as unknown as ReturnType<typeof libraryApi.useLoras>);
});

describe("PromptPane", () => {
  it("renders empty state when no prompts and disables generate without main analysis", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);

    wrap(<PromptPane session={{ ...session, source_images: [] }} />);
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
          brief: null,
          created_at: 0,
        },
      ],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);

    wrap(<PromptPane session={session} />);
    expect(screen.getByDisplayValue("moody girl")).toBeInTheDocument();
    expect(screen.getByDisplayValue("blurry")).toBeInTheDocument();
    expect(screen.getByText("lora-known")).toBeInTheDocument();
    expect(screen.getByText("ghost-lora")).toBeInTheDocument();
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  it("opens GenerateModal when Regenerate is clicked", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [{
        id: 9, session_id: session.id, intents: null, retrieved: null,
        prompt: { positive: "p", negative: "n", loras: [] },
        brief: null, created_at: 0,
      }],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);

    wrap(<PromptPane session={session} />);
    expect(screen.queryByTestId("generate-modal")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(screen.getByTestId("generate-modal")).toBeInTheDocument();
  });

  it("for t2i sessions: Generate is enabled with no source images", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(tasksApi, "useIsReindexing").mockReturnValue(false);

    const t2i: Session = { ...session, session_type: "t2i", source_images: [] };
    wrap(<PromptPane session={t2i} />);
    const btn = screen.getByRole("button", { name: /Generate/i });
    expect(btn).toBeEnabled();
  });

  it("disables Generate while a reindex task is active", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(tasksApi, "useIsReindexing").mockReturnValue(true);

    wrap(<PromptPane session={session} />);
    const btn = screen.getByRole("button", { name: /Generate/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute(
      "title",
      expect.stringMatching(/index is updating/i),
    );
  });
});
