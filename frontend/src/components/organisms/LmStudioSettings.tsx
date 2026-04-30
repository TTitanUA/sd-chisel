import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import {
  settingsApi,
  useLmModels,
  useLmStudioConfig,
  useRefreshLmStudio,
  useSettingsInvalidation,
  type LmRole,
} from "@/api/settings";
import styles from "./LmStudioSettings.module.css";

const ROLES: LmRole[] = ["vl", "prompt", "both"];
const LM_STUDIO_DEFAULT_URL = "http://localhost:1234/v1";

export function LmStudioSettings() {
  const cfg = useLmStudioConfig();
  const models = useLmModels();
  const refresh = useRefreshLmStudio();
  const invalidate = useSettingsInvalidation();

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
    mutationFn: (args: { name: string; role?: LmRole; enabled?: boolean }) =>
      settingsApi.patchModel(args.name, {
        ...(args.role !== undefined ? { role: args.role } : {}),
        ...(args.enabled !== undefined ? { enabled: args.enabled } : {}),
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
            placeholder="http://localhost:1234/v1"
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

        {(models.data ?? []).length > 0 && (
          <div className={styles.modelTable} role="table">
            <div className={styles.headCell}>Model</div>
            <div className={styles.headCell}>Role</div>
            <div className={styles.headCell}>Enabled</div>
            <div className={styles.headCell}>Last seen</div>
            {(models.data ?? []).map((m) => (
              <Row key={m.name}>
                <div title={m.name}>{m.name}</div>
                <div>
                  <select
                    className={styles.modelRoleSelect}
                    value={m.role}
                    onChange={(e) =>
                      patch.mutate({ name: m.name, role: e.currentTarget.value as LmRole })
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
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
