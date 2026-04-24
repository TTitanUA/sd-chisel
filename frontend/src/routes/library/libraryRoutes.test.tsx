import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FamiliesRoute from "./families";
import ModelsRoute from "./models";
import LorasRoute from "./loras";

function renderRoute(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

describe("library routes", () => {
  it("renders families from the API", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json([
      { id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 },
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
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 }]);
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

    renderRoute(<ModelsRoute />);
    await waitFor(() => {
      expect(screen.getAllByText("Juggernaut").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/General model/)).toBeInTheDocument();
  });

  it("renders loras from the API", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 }]);
      }
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_compat: ["sdxl"],
          recommended_weight: 0.8,
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
      ]);
    }));

    renderRoute(<LorasRoute />);
    await waitFor(() => {
      expect(screen.getAllByText("Cinematic Light").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Rim light/)).toBeInTheDocument();
  });
});
