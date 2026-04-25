import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SessionSettingsDrawer } from "./SessionSettingsDrawer";
import * as settingsApi from "@/api/settings";
import * as libraryApi from "@/api/library";
import type { Session } from "@/api/sessions";

const baseSession: Session = {
  id: "s1",
  project_id: "p1",
  name: null,
  model_name: null,
  use_negative: true,
  vl_model_name: null,
  prompt_model_name: null,
  vl_summary: null,
  source_image_path: null,
  source_image_url: null,
  pinned_loras: [],
  created_at: 0,
  updated_at: 0,
};

function renderDrawer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SessionSettingsDrawer session={baseSession} open={true} onOpenChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionSettingsDrawer model pickers", () => {
  beforeEach(() => {
    vi.spyOn(libraryApi, "useLoras").mockReturnValue({ data: [] } as any);
    vi.spyOn(libraryApi, "useModels").mockReturnValue({ data: [] } as any);
  });
  afterEach(() => vi.restoreAllMocks());

  it("VL select offers vl + both, hides prompt-only", () => {
    vi.spyOn(settingsApi, "useLmModelsByRole").mockImplementation((role) =>
      ({
        data: role === "vl"
          ? [{ name: "qwen-vl", role: "vl", enabled: true, last_seen: 0 },
             { name: "any-model", role: "both", enabled: true, last_seen: 0 }]
          : [{ name: "any-model", role: "both", enabled: true, last_seen: 0 }],
      } as any),
    );
    renderDrawer();
    const vlSelect = screen.getByLabelText(/vl model/i) as HTMLSelectElement;
    const optionTexts = Array.from(vlSelect.options).map((o) => o.value);
    expect(optionTexts).toContain("qwen-vl");
    expect(optionTexts).toContain("any-model");
    expect(optionTexts).not.toContain("mistral-prompt");
  });

  it("shows 'Configure LMStudio' link when no models cached", () => {
    vi.spyOn(settingsApi, "useLmModelsByRole").mockReturnValue({ data: [] } as any);
    renderDrawer();
    expect(screen.getByRole("link", { name: /configure lmstudio/i })).toBeInTheDocument();
  });
});
