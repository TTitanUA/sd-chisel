import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SessionSettingsDrawer } from "./SessionSettingsDrawer";
import * as settingsApi from "@/api/settings";
import * as libraryApi from "@/api/library";
import { sessionsApi, type Session } from "@/api/sessions";

const baseSession: Session = {
  id: "s1",
  project_id: "p1",
  name: null,
  session_type: "i2i",
  model_name: null,
  use_negative: true,
  vl_model_name: null,
  prompt_model_name: null,
  source_images: [],
  pinned_loras: [],
  comfy_input_cleanup: "keep",
  hidden: false,
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

type LorasResult = ReturnType<typeof libraryApi.useLoras>;
type ModelsResult = ReturnType<typeof libraryApi.useModels>;
type LmModelsResult = ReturnType<typeof settingsApi.useLmModelsForVision>;

describe("SessionSettingsDrawer model pickers", () => {
  beforeEach(() => {
    vi.spyOn(libraryApi, "useLoras").mockReturnValue({ data: [] } as unknown as LorasResult);
    vi.spyOn(libraryApi, "useModels").mockReturnValue({ data: [] } as unknown as ModelsResult);
  });
  afterEach(() => vi.restoreAllMocks());

  it("VL select offers vision-capable models, chat select offers all enabled", () => {
    vi.spyOn(settingsApi, "useLmModelsForVision").mockReturnValue(
      {
        data: [
          { name: "qwen-vl", vision: true, tool_use: false, reasoning: false, enabled: true, last_seen: 0 },
          { name: "any-model", vision: true, tool_use: false, reasoning: false, enabled: true, last_seen: 0 },
        ],
      } as unknown as LmModelsResult,
    );
    vi.spyOn(settingsApi, "useLmModelsForChat").mockReturnValue(
      {
        data: [
          { name: "any-model", vision: true, tool_use: false, reasoning: false, enabled: true, last_seen: 0 },
        ],
      } as unknown as LmModelsResult,
    );
    renderDrawer();
    const vlSelect = screen.getByLabelText(/vl model/i) as HTMLSelectElement;
    const optionTexts = Array.from(vlSelect.options).map((o) => o.value);
    expect(optionTexts).toContain("qwen-vl");
    expect(optionTexts).toContain("any-model");
    expect(optionTexts).not.toContain("mistral-prompt");
  });

  it("shows 'Configure LMStudio' link when no models cached", () => {
    vi.spyOn(settingsApi, "useLmModelsForVision").mockReturnValue({ data: [] } as unknown as LmModelsResult);
    vi.spyOn(settingsApi, "useLmModelsForChat").mockReturnValue({ data: [] } as unknown as LmModelsResult);
    renderDrawer();
    expect(screen.getByRole("link", { name: /configure lmstudio/i })).toBeInTheDocument();
  });
});

describe("SessionSettingsDrawer delete", () => {
  beforeEach(() => {
    vi.spyOn(libraryApi, "useLoras").mockReturnValue({ data: [] } as unknown as LorasResult);
    vi.spyOn(libraryApi, "useModels").mockReturnValue({ data: [] } as unknown as ModelsResult);
    vi.spyOn(settingsApi, "useLmModelsForVision").mockReturnValue({ data: [] } as unknown as LmModelsResult);
    vi.spyOn(settingsApi, "useLmModelsForChat").mockReturnValue({ data: [] } as unknown as LmModelsResult);
  });
  afterEach(() => vi.restoreAllMocks());

  it("calls deleteSession when user confirms", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const deleteSpy = vi.spyOn(sessionsApi, "deleteSession").mockResolvedValue(undefined);
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /delete session/i }));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(deleteSpy).toHaveBeenCalledWith("s1");
  });

  it("does not call deleteSession when user cancels", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const deleteSpy = vi.spyOn(sessionsApi, "deleteSession").mockResolvedValue(undefined);
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /delete session/i }));
    expect(deleteSpy).not.toHaveBeenCalled();
  });
});
