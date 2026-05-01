import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import {
  settingsApi,
  useLmModels,
  useLmStudioConfig,
  useRefreshLmStudio,
  useSettingsInvalidation,
  useShowHidden,
} from "@/api/settings";
import styles from "./LmStudioSettings.module.css";

const LM_STUDIO_DEFAULT_URL = "http://localhost:1234";

export function LmStudioSettings() {
  const cfg = useLmStudioConfig();
  const models = useLmModels();
  const refresh = useRefreshLmStudio();
  const invalidate = useSettingsInvalidation();
  const showHidden = useShowHidden();
  const visibleModels = (models.data ?? []).filter((m) => showHidden || !m.hidden);

  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    if (cfg.data) {
      setBaseUrl(cfg.data.base_url ?? "");
      setApiKey(cfg.data.api_key ?? "");
    }
  }, [cfg.data]);

  const save = useMutation({
    mutationFn: () =>
      settingsApi.putLmStudio({
        base_url: baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
      }),
    onSuccess: () => invalidate.config(),
  });

  const patch = useMutation({
    mutationFn: (args: { name: string; vision?: boolean; tool_use?: boolean; reasoning?: boolean; enabled?: boolean; favorite?: boolean; hidden?: boolean }) =>
      settingsApi.patchModel(args.name, {
        ...(args.vision !== undefined ? { vision: args.vision } : {}),
        ...(args.tool_use !== undefined ? { tool_use: args.tool_use } : {}),
        ...(args.reasoning !== undefined ? { reasoning: args.reasoning } : {}),
        ...(args.enabled !== undefined ? { enabled: args.enabled } : {}),
        ...(args.favorite !== undefined ? { favorite: args.favorite } : {}),
        ...(args.hidden !== undefined ? { hidden: args.hidden } : {}),
      }),
    onSuccess: () => invalidate.models(),
  });

  const configured = !!cfg.data?.configured;
  const refreshError = refresh.error ? String(refresh.error) : null;
  const refreshDisabled = !configured || refresh.isPending;

  return (
    <div className={styles.page}>
      <section className={styles.section}>
        <div className={styles.h}>LMStudio endpoint</div>
        <div className={styles.sub}>
          OpenAI-compatible base URL exposed by LMStudio. The API key is optional —
          LMStudio ignores it; leave empty unless your reverse proxy needs it.
        </div>
        <div className={styles.urlField}>
          <TextInput
            label="Base URL"
            placeholder="http://localhost:1234"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
          />
          <button
            type="button"
            className={styles.urlDefault}
            onClick={() => setBaseUrl(LM_STUDIO_DEFAULT_URL)}
          >
            Use default
          </button>
        </div>
        <TextInput
          label="API key (optional)"
          placeholder="leave empty for local LMStudio"
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
        />
        <div>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {save.isPending ? "Saving…" : "Save endpoint"}
          </Button>
        </div>
      </section>

      <section className={styles.section}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className={styles.h}>Available models</div>
          <div style={{ flex: 1 }} />
          <Button
            size="sm"
            icon={<Icon name="RotateCw" size={12} />}
            onClick={() => refresh.mutate()}
            disabled={refreshDisabled}
          >
            {refresh.isPending ? "Refreshing…" : "Refresh from LMStudio"}
          </Button>
        </div>

        {!configured && (
          <div className={styles.banner}>
            Configure base URL above, then press Refresh to fetch the model list.
          </div>
        )}
        {configured && refreshError && (
          <div className={styles.banner} data-tone="error" role="alert">
            Refresh failed: {refreshError}
          </div>
        )}
        {configured && !refreshError && (models.data ?? []).length === 0 && (
          <div className={styles.banner}>
            No models cached yet. Press Refresh to fetch them from LMStudio.
          </div>
        )}

        {visibleModels.length > 0 && (
          <div className={styles.modelTable} role="table">
            <div className={styles.headCell}>Model</div>
            <div className={styles.headCell}>Capabilities</div>
            <div className={styles.headCell}>Favorite</div>
            <div className={styles.headCell}>Enabled</div>
            <div className={styles.headCell}>Hidden</div>
            <div className={styles.headCell}>Last seen</div>
            {visibleModels.map((m) => (
              <Row key={m.name}>
                <div title={m.name} style={m.hidden ? { opacity: 0.55 } : undefined}>{m.name}</div>
                <div className={styles.capabilities}>
                  {(["vision", "tool_use", "reasoning"] as const).map((cap) => (
                    <label key={cap} className={styles.capLabel}>
                      <input
                        type="checkbox"
                        checked={m[cap]}
                        onChange={(e) =>
                          patch.mutate({ name: m.name, [cap]: e.currentTarget.checked })
                        }
                      />
                      {cap === "tool_use" ? "tools" : cap}
                    </label>
                  ))}
                </div>
                <div>
                  <button
                    type="button"
                    className={styles.starBtn}
                    aria-label={m.favorite ? "Unset favorite" : "Set as favorite"}
                    aria-pressed={m.favorite}
                    onClick={() =>
                      patch.mutate({ name: m.name, favorite: !m.favorite })
                    }
                    title={m.favorite ? "Favorite (used by default)" : "Set as favorite"}
                  >
                    <Star size={14} strokeWidth={1.75} fill={m.favorite ? "currentColor" : "none"} />
                  </button>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={m.enabled}
                    onChange={(e) =>
                      patch.mutate({ name: m.name, enabled: e.currentTarget.checked })
                    }
                  />
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={m.hidden}
                    onChange={(e) =>
                      patch.mutate({ name: m.name, hidden: e.currentTarget.checked })
                    }
                    aria-label="Hidden"
                  />
                </div>
                <div style={{ color: "var(--text-subtle)", fontSize: 12 }}>
                  {m.last_seen ? new Date(m.last_seen * 1000).toLocaleString() : "—"}
                </div>
              </Row>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
