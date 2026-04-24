import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type Family = {
  id: string;
  display_name: string;
  prompt_guide: string;
  created_at: number;
  updated_at: number;
};

export type FamilyCreate = Pick<Family, "id" | "display_name" | "prompt_guide">;
export type FamilyUpdate = Pick<Family, "display_name" | "prompt_guide">;

export type Model = {
  name: string;
  display_name: string;
  family_id: string;
  description: string | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};

export type ModelCreate = Omit<Model, "created_at" | "updated_at">;
export type ModelUpdate = Omit<ModelCreate, "name">;

export type Lora = {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  trigger_words: string[];
  family_id: string;
  recommended_weight: number | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};

export type LoraCreate = Omit<Lora, "created_at" | "updated_at">;
export type LoraUpdate = Omit<LoraCreate, "name">;

export const libraryKeys = {
  families: (q = "") => ["library", "families", q] as const,
  models: (familyId = "", q = "") => ["library", "models", familyId, q] as const,
  loras: (familyId = "", tag = "", q = "") => ["library", "loras", familyId, tag, q] as const,
};

function qs(params: Record<string, string | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const libraryApi = {
  listFamilies: (q?: string) => apiFetch<Family[]>(`/api/library/families${qs({ q })}`),
  createFamily: (body: FamilyCreate) =>
    apiFetch<Family>("/api/library/families", { method: "POST", body: JSON.stringify(body) }),
  updateFamily: (id: string, body: FamilyUpdate) =>
    apiFetch<Family>(`/api/library/families/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteFamily: (id: string) =>
    apiFetch<void>(`/api/library/families/${encodeURIComponent(id)}`, { method: "DELETE" }),

  listModels: (params: { family_id?: string; q?: string } = {}) =>
    apiFetch<Model[]>(`/api/library/models${qs(params)}`),
  createModel: (body: ModelCreate) =>
    apiFetch<Model>("/api/library/models", { method: "POST", body: JSON.stringify(body) }),
  updateModel: (name: string, body: ModelUpdate) =>
    apiFetch<Model>(`/api/library/models/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteModel: (name: string) =>
    apiFetch<void>(`/api/library/models/${encodeURIComponent(name)}`, { method: "DELETE" }),

  listLoras: (params: { family_id?: string; tag?: string; q?: string } = {}) =>
    apiFetch<Lora[]>(`/api/library/loras${qs(params)}`),
  createLora: (body: LoraCreate) =>
    apiFetch<Lora>("/api/library/loras", { method: "POST", body: JSON.stringify(body) }),
  updateLora: (name: string, body: LoraUpdate) =>
    apiFetch<Lora>(`/api/library/loras/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteLora: (name: string) =>
    apiFetch<void>(`/api/library/loras/${encodeURIComponent(name)}`, { method: "DELETE" }),
};

export function useFamilies(q = "") {
  return useQuery({ queryKey: libraryKeys.families(q), queryFn: () => libraryApi.listFamilies(q) });
}

export function useModels(params: { family_id?: string; q?: string } = {}) {
  return useQuery({
    queryKey: libraryKeys.models(params.family_id ?? "", params.q ?? ""),
    queryFn: () => libraryApi.listModels(params),
  });
}

export function useLoras(params: { family_id?: string; tag?: string; q?: string } = {}) {
  return useQuery({
    queryKey: libraryKeys.loras(params.family_id ?? "", params.tag ?? "", params.q ?? ""),
    queryFn: () => libraryApi.listLoras(params),
  });
}

export function useLibraryInvalidation() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["library"] });
  };
}
