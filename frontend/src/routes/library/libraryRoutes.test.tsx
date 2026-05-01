import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import FamiliesRoute from "./families";
import ModelsRoute from "./models";
import LorasRoute from "./loras";

function renderRoute(ui: ReactNode, path = "/library/families") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/library/families/*" element={ui} />
          <Route path="/library/models/*" element={ui} />
          <Route path="/library/loras/*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

describe("library routes", () => {
  it("renders families from the API", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json([
      { id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 },
    ])));

    renderRoute(<FamiliesRoute />);
    await waitFor(() => {
      expect(screen.getAllByText("SDXL").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Guide/)).toBeInTheDocument();
  });

  it("renders models from the API", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 }]);
      }
      return json([
        {
          name: "juggernaut",
          display_name: "Juggernaut",
          family_id: "sdxl",
          description: "General model",
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
      ]);
    }));

    renderRoute(<ModelsRoute />, "/library/models");
    await waitFor(() => {
      expect(screen.getAllByText("juggernaut").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/General model/)).toBeInTheDocument();
  });

  it("renders loras from the API", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 }]);
      }
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_id: "sdxl",
          recommended_weight: 0.8,
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
          is_indexed: true,
        },
      ]);
    }));

    renderRoute(<LorasRoute />, "/library/loras");
    await waitFor(() => {
      expect(screen.getAllByText("cinematic_light").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Rim light/)).toBeInTheDocument();
  });

  it("replaces family filter when choosing another family (LoRA, like models)", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([
          { id: "sdxl", display_name: "SDXL", prompt_guide: "A", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 },
          { id: "sd1", display_name: "SD1", prompt_guide: "B", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 },
        ]);
      }
      return json([
        {
          name: "lora_sdxl",
          display_name: "LoRA SDXL",
          description: "for sdxl",
          tags: [],
          trigger_words: [],
          family_id: "sdxl",
          recommended_weight: 0.8,
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
        {
          name: "lora_sd1",
          display_name: "LoRA SD1",
          description: "for sd1",
          tags: [],
          trigger_words: [],
          family_id: "sd1",
          recommended_weight: 0.7,
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
      ]);
    }));

    renderRoute(<LorasRoute />, "/library/loras");
    const list = await screen.findByRole("complementary", { name: "LoRA list" });
    await waitFor(() => {
      expect(within(list).getAllByText("lora_sdxl").length).toBeGreaterThan(0);
    });
    expect(within(list).getByText("lora_sd1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Family" }));
    const dialog1 = await screen.findByRole("dialog", { name: "Filter by family" });
    fireEvent.click(within(dialog1).getByText("SDXL"));
    await waitFor(() => {
      expect(within(list).getByText("1 of 2")).toBeInTheDocument();
    });
    expect(within(list).getByText("lora_sdxl")).toBeInTheDocument();
    expect(within(list).queryByText("lora_sd1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Family" }));
    const dialog2 = await screen.findByRole("dialog", { name: "Filter by family" });
    fireEvent.click(within(dialog2).getByText("SD1"));
    await waitFor(() => {
      expect(within(list).getByText("1 of 2")).toBeInTheDocument();
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(within(list).getByText("lora_sd1")).toBeInTheDocument();
    expect(within(list).queryByText("lora_sdxl")).not.toBeInTheDocument();
  });

  it("renders an Indexed badge in the LoRA detail meta", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "", prompt_i2i: "", prompt_t2i: "", created_at: 0, updated_at: 0 }]);
      }
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: [],
          trigger_words: [],
          family_id: "sdxl",
          recommended_weight: 0.8,
          author: null,
          version: null,
          source_url: null,
          created_at: 0,
          updated_at: 0,
          is_indexed: true,
        },
      ]);
    }));

    renderRoute(<LorasRoute />, "/library/loras");
    expect(await screen.findByText(/indexed/i)).toBeInTheDocument();
  });

  it("renames a LoRA from the edit page and navigates to the new URL", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "G", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 }]);
      }
      if (url.includes("/rename") && init?.method === "POST") {
        return json({
          name: "cinematic_light_v2",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_id: "sdxl",
          recommended_weight: 0.75,
          author: null, version: null, source_url: null,
          created_at: 1, updated_at: 2, is_indexed: true,
        });
      }
      // GET /loras
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_id: "sdxl",
          recommended_weight: 0.75,
          author: null, version: null, source_url: null,
          created_at: 1, updated_at: 1, is_indexed: true,
        },
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRoute(<LorasRoute />, "/library/loras/cinematic_light/edit");

    const renameToggle = await screen.findByRole("button", { name: /rename…/i });
    fireEvent.click(renameToggle);

    const slugInput = await screen.findByLabelText(/new filename slug/i);
    fireEvent.change(slugInput, { target: { value: "cinematic_light_v2" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      const renameCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          typeof url === "string" &&
          url.includes("/api/library/loras/cinematic_light/rename") &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(renameCalls.length).toBe(1);
      const body = JSON.parse((renameCalls[0][1] as RequestInit).body as string);
      expect(body).toEqual({ new_name: "cinematic_light_v2" });
    });
  });
});
