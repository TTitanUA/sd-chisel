import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LoraSpec = { name: string; weight: number };

export type GeneratedPrompt = {
  positive: string;
  negative: string | null;
  loras: LoraSpec[];
};

export type Intent = { kind: string; query: string };

export type RetrievedLora = { name: string; distance: number };

export type RetrievedIntent = {
  intent_index: number;
  intent_query: string;
  results: RetrievedLora[];
};

export type Prompt = {
  id: number;
  session_id: string;
  prompt: GeneratedPrompt;
  intents: Intent[] | null;
  retrieved: RetrievedIntent[] | null;
  created_at: number;
};

export type GeneratePromptResponse = {
  prompt_id: number;
  prompt: GeneratedPrompt;
  intents: Intent[];
  retrieved: RetrievedIntent[];
  created_at: number;
};

const promptsKey = (sessionId: string) => ["prompts", sessionId] as const;

export function usePrompts(sessionId: string | undefined) {
  return useQuery({
    queryKey: promptsKey(sessionId ?? ""),
    enabled: Boolean(sessionId),
    queryFn: async () => {
      const body = await apiFetch<{ prompts: Prompt[] }>(
        `/api/sessions/${sessionId}/prompts`,
      );
      return body.prompts;
    },
  });
}

export function useGeneratePrompt(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<GeneratePromptResponse>(
        `/api/sessions/${sessionId}/generate-prompt`,
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: promptsKey(sessionId) });
    },
  });
}
