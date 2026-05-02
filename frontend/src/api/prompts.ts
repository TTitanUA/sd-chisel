import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { chatKeys } from "./chat";
import { sessionKeys } from "./sessions";

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
  brief: string | null;
  created_at: number;
};

export type GeneratePromptResponse = {
  prompt_id: number;
  prompt: GeneratedPrompt;
  intents: Intent[];
  retrieved: RetrievedIntent[];
  brief: string | null;
  created_at: number;
};

export type SummarizeImageView = { label: string; analysis: string };

export type SummarizePinnedLoraView = { name: string; weight: number | null };

export type SummarizeContext = {
  mode: string;
  model_name: string | null;
  model_description: string | null;
  family_id: string | null;
  family_display_name: string | null;
  pinned_loras: SummarizePinnedLoraView[];
  use_negative: boolean;
  main_image: SummarizeImageView | null;
  reference_images: SummarizeImageView[];
};

export type SummarizeChatResponse = {
  brief: string;
  context: SummarizeContext;
};

export type GeneratePromptInput = {
  brief?: string;
  compactHistory?: boolean;
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

export function useSummarizeChat(sessionId: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<SummarizeChatResponse>(
        `/api/sessions/${sessionId}/summarize-chat`,
        { method: "POST" },
      ),
  });
}

export function useGeneratePrompt(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: GeneratePromptInput = {}) => {
      const body: Record<string, unknown> = {};
      if (input.brief !== undefined) body.brief = input.brief;
      if (input.compactHistory) body.compact_history = true;
      return apiFetch<GeneratePromptResponse>(
        `/api/sessions/${sessionId}/generate-prompt`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: promptsKey(sessionId) });
      if (variables?.compactHistory) {
        qc.invalidateQueries({ queryKey: chatKeys.messages(sessionId) });
        qc.invalidateQueries({ queryKey: sessionKeys.session(sessionId) });
      }
    },
  });
}
