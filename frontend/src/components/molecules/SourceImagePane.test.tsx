import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SourceImagePane } from "./SourceImagePane";
import { sessionsApi, type Session } from "@/api/sessions";
import { settingsApi } from "@/api/settings";

const baseSession: Session = {
  id: "sess1",
  project_id: "proj1",
  name: "S",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_image_path: "images/sess1/source.png",
  source_image_url: "/media/images/sess1/source.png",
  vl_summary: null,
  vl_model_name: "qwen2-vl-7b-instruct",
  prompt_model_name: null,
  created_at: 0,
  updated_at: 0,
};

function withClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(session: Session, configured = true) {
  vi.spyOn(settingsApi, "getLmStudio").mockResolvedValue({
    base_url: configured ? "http://h/v1" : null,
    api_key: null,
    configured,
    updated_at: 0,
  });
  const qc = withClient();
  return render(
    <QueryClientProvider client={qc}>
      <SourceImagePane session={session} />
    </QueryClientProvider>,
  );
}

describe("SourceImagePane analyze flow", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("shows the VL model in the meta line", () => {
    renderWith(baseSession);
    expect(screen.getByText(/qwen2-vl-7b-instruct/)).toBeInTheDocument();
  });

  it("disables Analyze when no vl_model_name on session", () => {
    renderWith({ ...baseSession, vl_model_name: null });
    const btn = screen.getByRole("button", { name: /analyze/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringMatching(/vl model/i));
  });

  it("disables Analyze when LMStudio not configured", async () => {
    renderWith(baseSession, false);
    const btn = await screen.findByRole("button", { name: /analyze/i });
    expect(btn).toBeDisabled();
  });

  it("calls analyzeSource on click", async () => {
    const spy = vi.spyOn(sessionsApi, "analyzeSource").mockResolvedValue({
      ...baseSession, vl_summary: "moody portrait",
    });
    renderWith(baseSession);
    await userEvent.click(await screen.findByRole("button", { name: /analyze/i }));
    expect(spy).toHaveBeenCalledWith("sess1");
  });

  it("renders existing vl_summary when present", () => {
    renderWith({ ...baseSession, vl_summary: "previously analyzed scene" });
    expect(screen.getByText(/previously analyzed scene/)).toBeInTheDocument();
  });

  it("shows error when analyzeSource rejects", async () => {
    vi.spyOn(sessionsApi, "analyzeSource").mockRejectedValue(
      new Error("API 502: upstream timeout"),
    );
    renderWith(baseSession);
    await userEvent.click(await screen.findByRole("button", { name: /analyze/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/502|upstream/i);
  });
});
