import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourceImagesPane } from "./SourceImagesPane";
import type { Session, SourceImage } from "@/api/sessions";

const baseSession: Session = {
  id: "s1",
  project_id: "p1",
  name: "demo",
  session_type: "i2i",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_images: [],
  vl_model_name: "qwen-vl",
  prompt_model_name: null,
  hidden: false,
  created_at: 0,
  updated_at: 0,
};

function makeImage(over: Partial<SourceImage>): SourceImage {
  return {
    id: "img1",
    session_id: "s1",
    path: "images/s1/sources/img1.png",
    url: "/media/images/s1/sources/img1.png",
    original_filename: "image-one.png",
    is_main: true,
    analysis: null,
    analysis_prompt: null,
    created_at: 0,
    updated_at: 0,
    ...over,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.includes("/settings/lmstudio")) {
      return jsonResponse({ configured: true, base_url: "http://h", api_key_set: false });
    }
    return jsonResponse({});
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceImagesPane", () => {
  it("renders the empty state when there are no source images", () => {
    render(withClient(<SourceImagesPane session={baseSession} />));
    expect(screen.getByText(/Drop source images/i)).toBeInTheDocument();
  });

  it("renders a card per image with main badge on the first", () => {
    const session = {
      ...baseSession,
      source_images: [
        makeImage({ id: "a", original_filename: "main.png", is_main: true }),
        makeImage({ id: "b", original_filename: "ref.png", is_main: false }),
      ],
    };
    render(withClient(<SourceImagesPane session={session} />));
    expect(screen.getByText("main.png")).toBeInTheDocument();
    expect(screen.getByText("ref.png")).toBeInTheDocument();
    // The main card has a "Main image" star button (disabled), the reference has a "Set as main" button.
    expect(screen.getByRole("button", { name: /main image/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /set as main/i })).toBeEnabled();
  });

  it("clicking the brief analysis opens the detail modal", async () => {
    const session = {
      ...baseSession,
      source_images: [
        makeImage({
          id: "a",
          analysis: "moody portrait with soft rim lighting and a deep blue palette",
        }),
      ],
    };
    render(withClient(<SourceImagesPane session={session} />));
    await userEvent.click(
      screen.getByRole("button", { name: /show full analysis/i }),
    );
    const dialog = await screen.findByRole("dialog");
    // The dialog body contains the full (un-truncated) analysis.
    expect(dialog).toHaveTextContent(/moody portrait with soft rim lighting/);
    expect(dialog).toHaveTextContent("image-one.png");
  });

  it("Re-analyze button opens the analyze modal pre-filled with prior refining prompt", async () => {
    const session = {
      ...baseSession,
      source_images: [
        makeImage({
          id: "a",
          analysis: "first take",
          analysis_prompt: "focus on the cat",
        }),
      ],
    };
    render(withClient(<SourceImagesPane session={session} />));
    await userEvent.click(screen.getByRole("button", { name: /^Re-analyze$/i }));
    const textarea = await screen.findByRole("textbox");
    expect(textarea).toHaveValue("focus on the cat");
  });
});
