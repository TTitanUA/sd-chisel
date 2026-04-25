import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import styles from "./AppShell.module.css";

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (String(url).includes("/api/settings/lmstudio")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ base_url: null, api_key: null, configured: false, updated_at: 0 }),
            { status: 200 },
          ),
        );
      }
      if (String(url).endsWith("/api/projects")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (String(url).includes("/api/library/")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    }),
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    mockFetch();
  });

  it("renders the brand, project sidebar, topbar mode pills, endpoint chip, and the child outlet on workspace", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>child</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("sd-chisel")).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Workspace$/i })).toHaveClass(styles.navPillActive);
    expect(screen.getByRole("link", { name: /^Library$/i })).not.toHaveClass(styles.navPillActive);
    expect(await screen.findByText("(no endpoint)")).toBeInTheDocument();
    expect(screen.getByText("child")).toBeInTheDocument();
  });

  it("marks Library as active on library routes", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/library/loras"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/library/loras" element={<div>lib-child</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("link", { name: /^Library$/i })).toHaveClass(styles.navPillActive);
    expect(screen.getByRole("link", { name: /^Workspace$/i })).not.toHaveClass(styles.navPillActive);
    expect(screen.getAllByRole("link", { name: /^Settings$/i }).length).toBeGreaterThan(0);
    expect(screen.getByText("lib-child")).toBeInTheDocument();
  });
});
