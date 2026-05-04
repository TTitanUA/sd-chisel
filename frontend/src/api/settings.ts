import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LmStudioConfig = {
  base_url: string | null;
  api_key: string | null;
  configured: boolean;
  updated_at: number;
};

export type ComfyUiConfig = {
  base_url: string | null;
  install_path: string | null;
  api_key: string | null;
  configured: boolean;
  updated_at: number;
};

export type ComfyUiCheckField = {
  ok: boolean;
  detail: string | null;
  info: Record<string, unknown> | null;
};

export type ComfyUiCheck = {
  url: ComfyUiCheckField;
  install_path: ComfyUiCheckField;
};

export type LmModel = {
  name: string;
  vision: boolean;
  tool_use: boolean;
  reasoning: boolean;
  enabled: boolean;
  favorite: boolean;
  hidden: boolean;
  last_seen: number;
};

export type Privacy = {
  show_hidden: boolean;
  updated_at: number;
};

export type SamplingBundle = Record<string, number>;

export type ActionDefaults = {
  analyze: SamplingBundle;
  chat: SamplingBundle;
  summarize: SamplingBundle;
  generate: SamplingBundle;
  comfy_import: SamplingBundle;
};

export type Action = keyof ActionDefaults;

export const settingsKeys = {
  lmstudio: () => ["settings", "lmstudio"] as const,
  lmModels: () => ["settings", "lmstudio", "models"] as const,
  comfyui: () => ["settings", "comfyui"] as const,
  privacy: () => ["settings", "privacy"] as const,
  actionDefaults: () => ["settings", "action-defaults"] as const,
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
  unloadAll: () =>
    apiFetch<{ unloaded: number }>("/api/settings/lmstudio/unload-all", {
      method: "POST",
    }),
  listModels: () =>
    apiFetch<{ models: LmModel[] }>("/api/settings/lmstudio/models"),
  patchModel: (
    name: string,
    patch: { vision?: boolean; tool_use?: boolean; reasoning?: boolean; enabled?: boolean; favorite?: boolean; hidden?: boolean },
  ) =>
    apiFetch<LmModel>(`/api/settings/lmstudio/models/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  getComfyUi: () => apiFetch<ComfyUiConfig>("/api/settings/comfyui"),
  putComfyUi: (body: { base_url: string | null; install_path: string | null; api_key: string | null }) =>
    apiFetch<ComfyUiConfig>("/api/settings/comfyui", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  checkComfyUi: () =>
    apiFetch<ComfyUiCheck>("/api/settings/comfyui/check", { method: "POST" }),

  getPrivacy: () => apiFetch<Privacy>("/api/settings/privacy"),
  putPrivacy: (body: { show_hidden: boolean }) =>
    apiFetch<Privacy>("/api/settings/privacy", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getActionDefaults: () => apiFetch<ActionDefaults>("/api/settings/action-defaults"),
  putActionDefaults: (
    body: Partial<Record<Action, SamplingBundle>>,
  ) =>
    apiFetch<ActionDefaults>("/api/settings/action-defaults", {
      method: "PUT",
      body: JSON.stringify(body),
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
    comfyui: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.comfyui() });
    },
    all: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
    },
  };
}

export function useComfyUiConfig() {
  return useQuery({
    queryKey: settingsKeys.comfyui(),
    queryFn: settingsApi.getComfyUi,
  });
}

export function useCheckComfyUi() {
  return useMutation({
    mutationFn: () => settingsApi.checkComfyUi(),
  });
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

export function useUnloadAllLmModels() {
  return useMutation({
    mutationFn: () => settingsApi.unloadAll(),
  });
}

export function usePrivacy() {
  return useQuery({
    queryKey: settingsKeys.privacy(),
    queryFn: settingsApi.getPrivacy,
  });
}

export function useShowHidden(): boolean {
  const q = usePrivacy();
  return q.data?.show_hidden ?? false;
}

export function useSetPrivacy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { show_hidden: boolean }) => settingsApi.putPrivacy(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.privacy() });
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

export function useActionDefaults() {
  return useQuery({
    queryKey: settingsKeys.actionDefaults(),
    queryFn: settingsApi.getActionDefaults,
  });
}

export function useUpdateActionDefaults() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Record<Action, SamplingBundle>>) =>
      settingsApi.putActionDefaults(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.actionDefaults() });
    },
  });
}
