import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LmStudioConfig = {
  base_url: string | null;
  api_key: string | null;
  configured: boolean;
  updated_at: number;
};

export type LmModel = {
  name: string;
  vision: boolean;
  tool_use: boolean;
  reasoning: boolean;
  enabled: boolean;
  favorite: boolean;
  last_seen: number;
};

export const settingsKeys = {
  lmstudio: () => ["settings", "lmstudio"] as const,
  lmModels: () => ["settings", "lmstudio", "models"] as const,
};

export const settingsApi = {
  getLmStudio: () => apiFetch<LmStudioConfig>("/api/settings/lmstudio"),
  putLmStudio: (body: { base_url: string | null; api_key: string | null }) =>
    apiFetch<LmStudioConfig>("/api/settings/lmstudio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  refresh: () =>
    apiFetch<{ models: LmModel[] }>("/api/settings/lmstudio/refresh", {
      method: "POST",
    }),
  listModels: () =>
    apiFetch<{ models: LmModel[] }>("/api/settings/lmstudio/models"),
  patchModel: (
    name: string,
    patch: { vision?: boolean; tool_use?: boolean; reasoning?: boolean; enabled?: boolean; favorite?: boolean },
  ) =>
    apiFetch<LmModel>(`/api/settings/lmstudio/models/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};

export function useLmStudioConfig() {
  return useQuery({
    queryKey: settingsKeys.lmstudio(),
    queryFn: settingsApi.getLmStudio,
  });
}

export function useLmModels() {
  return useQuery({
    queryKey: settingsKeys.lmModels(),
    queryFn: () => settingsApi.listModels().then((r) => r.models),
  });
}

export function useSettingsInvalidation() {
  const client = useQueryClient();
  return {
    config: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.lmstudio() });
    },
    models: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.lmModels() });
    },
    all: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
    },
  };
}

export function useRefreshLmStudio() {
  const invalidate = useSettingsInvalidation();
  return useMutation({
    mutationFn: () => settingsApi.refresh(),
    onSuccess: () => {
      invalidate.models();
      invalidate.config();
    },
  });
}

export function useLmModelsForVision() {
  const all = useLmModels();
  return {
    ...all,
    data: (all.data ?? []).filter((m) => m.enabled && m.vision),
  };
}

export function useLmModelsForChat() {
  const all = useLmModels();
  return {
    ...all,
    data: (all.data ?? []).filter((m) => m.enabled),
  };
}
