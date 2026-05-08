import * as Dialog from "@radix-ui/react-dialog";
import { Link, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { useLoras, useModels, type Lora } from "@/api/library";
import {
  sessionsApi,
  useSessionInvalidation,
  type PinnedLora,
  type Session,
} from "@/api/sessions";
import { useLmModelsForVision, useLmModelsForChat } from "@/api/settings";
import styles from "./SessionSettingsDrawer.module.css";

export function SessionSettingsDrawer({
  session,
  open,
  onOpenChange,
}: {
  session: Session;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const models = useModels();
  const loras = useLoras();
  const vlChoices = useLmModelsForVision();
  const promptChoices = useLmModelsForChat();
  const invalidate = useSessionInvalidation();
  const navigate = useNavigate();

  const [name, setName] = useState(session.name ?? "");
  const [modelName, setModelName] = useState(session.model_name ?? "");
  const [useNegative, setUseNegative] = useState(session.use_negative);
  const [pinned, setPinned] = useState<PinnedLora[]>(session.pinned_loras);
  const [vlModel, setVlModel] = useState(session.vl_model_name ?? "");
  const [promptModel, setPromptModel] = useState(session.prompt_model_name ?? "");
  const [loraSearch, setLoraSearch] = useState("");

  // Auto-pick favorite for prompt model when session has no value yet.
  useEffect(() => {
    if (promptModel) return;
    const list = promptChoices.data ?? [];
    if (list.length === 0) return;
    const favorite = list.find((m) => m.favorite);
    if (favorite) setPromptModel(favorite.name);
  }, [promptModel, promptChoices.data]);

  const save = useMutation({
    mutationFn: () =>
      sessionsApi.updateSession(session.id, {
        name: name.trim() || null,
        model_name: modelName || null,
        use_negative: useNegative,
        pinned_loras: pinned,
        vl_model_name: vlModel || null,
        prompt_model_name: promptModel || null,
      }),
    onSuccess: () => {
      invalidate.session(session.id);
      onOpenChange(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => sessionsApi.deleteSession(session.id),
    onSuccess: () => {
      invalidate.projects();
      onOpenChange(false);
      navigate(`/projects/${session.project_id}`, { replace: true });
    },
  });

  function onDeleteClick() {
    const ok = window.confirm(
      `Delete session "${session.name ?? "untitled"}"? This cannot be undone.`,
    );
    if (ok) deleteMutation.mutate();
  }

  function togglePin(lora: Lora) {
    setPinned((current) =>
      current.some((p) => p.lora_name === lora.name)
        ? current.filter((p) => p.lora_name !== lora.name)
        : [...current, { lora_name: lora.name, weight_override: null }],
    );
  }

  const filteredLoras = (loras.data ?? []).filter((l) =>
    `${l.name} ${l.display_name}`.toLowerCase().includes(loraSearch.toLowerCase()),
  );

  // Comfy sessions configure their diffusion model, negative-prompt
  // toggle, and LoRAs through agents + the workflow's slot map, not
  // through the session row.
  const isComfyLike =
    session.session_type === "comfy" || session.session_type === "comfy_mock";

  const noLmModels =
    !vlChoices.isLoading
    && !promptChoices.isLoading
    && (vlChoices.data?.length ?? 0) === 0
    && (promptChoices.data?.length ?? 0) === 0;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.panel} aria-describedby={undefined}>
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>Session settings</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.closeBtn} aria-label="Close">
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            <TextInput
              label="Session name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
            />
            {!isComfyLike && (
              <>
                <div className={styles.labelBlock}>
                  <span>Base model (diffusion)</span>
                  <select
                    className={styles.select}
                    value={modelName}
                    onChange={(e) => setModelName(e.currentTarget.value)}
                  >
                    <option value="">(none)</option>
                    {(models.data ?? []).map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.display_name} · {m.family_id}
                      </option>
                    ))}
                  </select>
                </div>
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={useNegative}
                    onChange={(e) => setUseNegative(e.currentTarget.checked)}
                  />
                  Use negative prompt
                </label>
              </>
            )}

            <div className={styles.labelBlock}>
              <span>VL model (image analysis)</span>
              <select
                aria-label="VL model"
                className={styles.select}
                value={vlModel}
                onChange={(e) => setVlModel(e.currentTarget.value)}
                disabled={(vlChoices.data?.length ?? 0) === 0}
              >
                <option value="">(not set)</option>
                {(vlChoices.data ?? []).map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>

            <div className={styles.labelBlock}>
              <span>Prompt model (text LLM)</span>
              <select
                aria-label="Prompt model"
                className={styles.select}
                value={promptModel}
                onChange={(e) => setPromptModel(e.currentTarget.value)}
                disabled={(promptChoices.data?.length ?? 0) === 0}
              >
                <option value="">(not set)</option>
                {(promptChoices.data ?? []).map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>

            {noLmModels && (
              <div style={{
                fontSize: 12, color: "var(--text-subtle)",
                border: "1px dashed var(--border)", borderRadius: 6, padding: 10,
              }}>
                No enabled LMStudio models yet.{" "}
                <Link to="/settings/lmstudio" onClick={() => onOpenChange(false)}>
                  Configure LMStudio →
                </Link>
              </div>
            )}

            {!isComfyLike && (
              <div>
                <div style={{ marginBottom: 6 }}>Pinned LoRAs ({pinned.length})</div>
                <TextInput
                  label="Search LoRAs"
                  placeholder="Type to filter…"
                  value={loraSearch}
                  onChange={(e) => setLoraSearch(e.currentTarget.value)}
                />
                <div className={styles.loraList}>
                  {filteredLoras.map((l) => {
                    const isPinned = pinned.some((p) => p.lora_name === l.name);
                    return (
                      <button
                        key={l.name}
                        type="button"
                        className={`${styles.loraRow} ${isPinned ? styles.pinned : ""}`}
                        onClick={() => togglePin(l)}
                      >
                        {isPinned && <Icon name="Pin" size={12} />}
                        <span className={styles.loraName}>{l.display_name}</span>
                        <span className={styles.loraMeta}>{l.family_id}</span>
                      </button>
                    );
                  })}
                  {filteredLoras.length === 0 && (
                    <div style={{ padding: 12, color: "var(--text-subtle)" }}>No LoRAs match.</div>
                  )}
                </div>
              </div>
            )}

            <div className={styles.dangerZone}>
              <Button
                type="button"
                variant="ghost"
                className={styles.dangerBtn}
                icon={<Icon name="Trash2" size={12} />}
                onClick={onDeleteClick}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete session"}
              </Button>
            </div>
          </div>
          <div className={styles.foot}>
            <Button type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
