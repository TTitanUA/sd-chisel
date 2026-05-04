import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  sessionsApi,
  useSessionInvalidation,
  type Action,
  type SamplingBundle,
  type Session,
} from "@/api/sessions";
import {
  useActionDefaults,
  useUpdateActionDefaults,
  type DefaultAction,
} from "@/api/settings";
import { ACTION_LABELS, FIELDS, type FieldDef } from "./fields";
import styles from "./ActionSettingsModal.module.css";

// Session-mode targets one of the four session-scoped action columns;
// default-mode covers all five (those four plus comfy_import).
type Mode =
  | { kind: "session"; session: Session; action: Action }
  | { kind: "default"; action: DefaultAction };

type DraftField = {
  override: boolean;
  // Raw input value as the user typed it. We coerce on save so partial
  // values like "0." don't blow up while typing.
  value: string;
};

type Draft = Record<string, DraftField>;

function readBundle(
  mode: Mode,
  appDefaults: Record<string, SamplingBundle> | undefined,
): SamplingBundle {
  if (mode.kind === "session") {
    const field = (`${mode.action}_settings`) as keyof Session;
    const raw = mode.session[field];
    if (raw && typeof raw === "object") return raw as SamplingBundle;
    return {};
  }
  // default-mode: pre-populate with the currently stored app-default
  // bundle so the user can tweak existing values instead of starting
  // every Edit from a blank slate.
  return (appDefaults?.[mode.action] ?? {}) as SamplingBundle;
}

function bundleToDraft(bundle: SamplingBundle): Draft {
  const draft: Draft = {};
  for (const f of FIELDS) {
    const v = bundle[f.key];
    draft[f.key] = {
      override: v !== undefined && v !== null,
      value: v !== undefined && v !== null ? String(v) : "",
    };
  }
  return draft;
}

function draftToBundle(draft: Draft): { bundle: SamplingBundle; error: string | null } {
  const bundle: SamplingBundle = {};
  for (const f of FIELDS) {
    const slot = draft[f.key];
    if (!slot || !slot.override) continue;
    const trimmed = slot.value.trim();
    if (trimmed === "") {
      return { bundle, error: `${f.label}: enter a value or switch to Inherit` };
    }
    const num = Number(trimmed);
    if (!Number.isFinite(num)) {
      return { bundle, error: `${f.label}: not a number` };
    }
    if (f.kind === "integer" && !Number.isInteger(num)) {
      return { bundle, error: `${f.label}: must be an integer` };
    }
    if (f.min !== undefined && num < f.min) {
      return { bundle, error: `${f.label}: must be ≥ ${f.min}` };
    }
    if (f.max !== undefined && num > f.max) {
      return { bundle, error: `${f.label}: must be ≤ ${f.max}` };
    }
    bundle[f.key] = num;
  }
  return { bundle, error: null };
}

function formatInherited(value: number | undefined, kind: FieldDef["kind"]): string {
  if (value === undefined) return "(model default)";
  return kind === "integer" ? String(Math.trunc(value)) : String(value);
}

export function ActionSettingsModal({
  mode,
  open,
  onOpenChange,
}: {
  mode: Mode;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const defaults = useActionDefaults();
  const sessionInvalidate = useSessionInvalidation();
  const updateDefaults = useUpdateActionDefaults();

  const [draft, setDraft] = useState<Draft>({});
  const [openHelp, setOpenHelp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const initialBundle = useMemo(
    () => readBundle(mode, defaults.data),
    [mode, defaults.data],
  );

  useEffect(() => {
    if (!open) return;
    setDraft(bundleToDraft(initialBundle));
    setError(null);
    setOpenHelp(null);
  }, [open, initialBundle]);

  const save = useMutation({
    mutationFn: async () => {
      const { bundle, error: vErr } = draftToBundle(draft);
      if (vErr) throw new Error(vErr);
      if (mode.kind === "session") {
        return sessionsApi.updateSession(mode.session.id, {
          name: mode.session.name,
          model_name: mode.session.model_name,
          use_negative: mode.session.use_negative,
          pinned_loras: mode.session.pinned_loras,
          vl_model_name: mode.session.vl_model_name,
          prompt_model_name: mode.session.prompt_model_name,
          [`${mode.action}_settings`]: bundle,
        });
      }
      return updateDefaults.mutateAsync({ [mode.action]: bundle });
    },
    onSuccess: () => {
      if (mode.kind === "session") sessionInvalidate.session(mode.session.id);
      onOpenChange(false);
    },
    onError: (err) => setError(String(err)),
  });

  const clearAll = useMutation({
    mutationFn: async () => {
      if (mode.kind === "session") {
        return sessionsApi.updateSession(mode.session.id, {
          name: mode.session.name,
          model_name: mode.session.model_name,
          use_negative: mode.session.use_negative,
          pinned_loras: mode.session.pinned_loras,
          vl_model_name: mode.session.vl_model_name,
          prompt_model_name: mode.session.prompt_model_name,
          [`${mode.action}_settings`]: null,
        });
      }
      return updateDefaults.mutateAsync({ [mode.action]: {} });
    },
    onSuccess: () => {
      if (mode.kind === "session") sessionInvalidate.session(mode.session.id);
      onOpenChange(false);
    },
    onError: (err) => setError(String(err)),
  });

  const inheritFrom = mode.kind === "session"
    ? defaults.data?.[mode.action] ?? {}
    : {};

  const isDefaultMode = mode.kind === "default";
  const titleAction = ACTION_LABELS[mode.action];
  const subTitle = isDefaultMode
    ? "App-wide default — applied when a session leaves a value as Inherit."
    : "Session override — leaves keys as Inherit to fall back to the app default.";

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !save.isPending && !clearAll.isPending && onOpenChange(v)}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.panel} aria-describedby={undefined}>
          <div className={styles.head}>
            <div>
              <Dialog.Title className={styles.title}>
                {titleAction} settings
              </Dialog.Title>
              <div className={styles.subTitle}>
                {isDefaultMode ? "Defaults" : "Session override"}
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.closeBtn}
                aria-label="Close"
                disabled={save.isPending || clearAll.isPending}
              >
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            <p className={styles.intro}>{subTitle}</p>
            {FIELDS.map((f) => {
              const slot = draft[f.key] ?? { override: false, value: "" };
              const inherited = !isDefaultMode
                ? (inheritFrom as SamplingBundle)[f.key]
                : undefined;
              return (
                <div key={f.key} className={styles.field}>
                  <div className={styles.fieldHead}>
                    <span className={styles.label}>{f.label}</span>
                    <button
                      type="button"
                      className={styles.helpBtn}
                      aria-label={`What does ${f.label} do?`}
                      onClick={() => setOpenHelp((v) => v === f.key ? null : f.key)}
                    >
                      ?
                    </button>
                  </div>
                  <div className={styles.fieldRow}>
                    <div className={styles.modeToggle} role="group">
                      <button
                        type="button"
                        aria-pressed={!slot.override}
                        onClick={() =>
                          setDraft((d) => ({
                            ...d,
                            [f.key]: { override: false, value: "" },
                          }))
                        }
                        disabled={save.isPending || clearAll.isPending}
                      >
                        Inherit
                      </button>
                      <button
                        type="button"
                        aria-pressed={slot.override}
                        onClick={() =>
                          setDraft((d) => ({
                            ...d,
                            [f.key]: {
                              override: true,
                              value: slot.value || (
                                inherited !== undefined ? String(inherited) : ""
                              ),
                            },
                          }))
                        }
                        disabled={save.isPending || clearAll.isPending}
                      >
                        Override
                      </button>
                    </div>
                    <input
                      className={styles.input}
                      type="number"
                      inputMode={f.kind === "integer" ? "numeric" : "decimal"}
                      step={f.step ?? (f.kind === "integer" ? 1 : "any")}
                      min={f.min}
                      max={f.max}
                      value={slot.value}
                      placeholder={
                        slot.override
                          ? ""
                          : isDefaultMode
                            ? "(unset)"
                            : formatInherited(inherited, f.kind)
                      }
                      disabled={!slot.override || save.isPending || clearAll.isPending}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          [f.key]: { override: true, value: e.currentTarget.value },
                        }))
                      }
                    />
                    {!slot.override && !isDefaultMode && (
                      <span className={styles.inheritedValue} aria-live="polite">
                        →&nbsp;{formatInherited(inherited, f.kind)}
                      </span>
                    )}
                  </div>
                  {openHelp === f.key && (
                    <div className={styles.help}>
                      {f.help}{" "}
                      <a href={f.docHref} target="_blank" rel="noreferrer">
                        Learn more ↗
                      </a>
                    </div>
                  )}
                </div>
              );
            })}
            {error && <div className={styles.error} role="alert">{error}</div>}
          </div>
          <div className={styles.foot}>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => clearAll.mutate()}
              disabled={save.isPending || clearAll.isPending}
              title={
                isDefaultMode
                  ? "Clear all keys from this app default"
                  : "Clear this session override (inherit the entire app default)"
              }
            >
              {clearAll.isPending ? "Clearing…" : "Clear all"}
            </Button>
            <div className={styles.footActions}>
              <Button
                type="button"
                onClick={() => onOpenChange(false)}
                disabled={save.isPending || clearAll.isPending}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => save.mutate()}
                disabled={save.isPending || clearAll.isPending}
              >
                {save.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
