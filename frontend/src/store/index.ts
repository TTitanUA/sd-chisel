import { create } from "zustand";

// Placeholder global store. Feature-specific stores (session, drawer, etc.)
// are added in their respective slice plans.
type AppState = {
  theme: "quarry";
};

export const useAppStore = create<AppState>(() => ({
  theme: "quarry",
}));
