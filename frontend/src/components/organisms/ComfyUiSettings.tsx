import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import {
  settingsApi,
  useCheckComfyUi,
  useComfyUiConfig,
  useSettingsInvalidation,
  type ComfyUiCheckField,
} from "@/api/settings";
import styles from "./ComfyUiSettings.module.css";

const COMFY_DEFAULT_URL = "http://127.0.0.1:8188";

export function ComfyUiSettings() {
  const cfg = useComfyUiConfig();
  const invalidate = useSettingsInvalidation();
  const check = useCheckComfyUi();

  const [baseUrl, setBaseUrl] = useState("");
  const [installPath, setInstallPath] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [inputDir, setInputDir] = useState("");
  const [outputDir, setOutputDir] = useState("");

  useEffect(() => {
    if (cfg.data) {
      setBaseUrl(cfg.data.base_url ?? "");
      setInstallPath(cfg.data.install_path ?? "");
      setApiKey(cfg.data.api_key ?? "");
      setInputDir(cfg.data.input_dir ?? "");
      setOutputDir(cfg.data.output_dir ?? "");
    }
  }, [cfg.data]);

  const save = useMutation({
    mutationFn: () =>
      settingsApi.putComfyUi({
        base_url: baseUrl.trim() || null,
        install_path: installPath.trim() || null,
        api_key: apiKey.trim() || null,
        input_dir: inputDir.trim() || null,
        output_dir: outputDir.trim() || null,
      }),
    onSuccess: () => {
      invalidate.comfyui();
      check.reset();
    },
  });

  // Show what the resolver will actually use, computed by the backend
  // from override + install path. Helps the user see at a glance where
  // Phase 3 will read/write files.
  const effectiveInput = cfg.data?.effective_input_dir ?? null;
  const effectiveOutput = cfg.data?.effective_output_dir ?? null;
  const inputPlaceholder = installPath.trim()
    ? `default: ${installPath.trim().replace(/[\\/]+$/, "")}/input`
    : "set install path first";
  const outputPlaceholder = installPath.trim()
    ? `default: ${installPath.trim().replace(/[\\/]+$/, "")}/output`
    : "set install path first";

  return (
    <div className={styles.page}>
      <section className={styles.section}>
        <div className={styles.h}>ComfyUI endpoint</div>
        <div className={styles.sub}>
          Base URL of your local ComfyUI instance and the filesystem path to its
          install directory. The path is needed for the per-node import wizard,
          which walks <code>custom_nodes/</code>. The API key is optional —
          local ComfyUI has no auth; set this only if you sit behind a proxy
          that requires a header.
        </div>

        <div className={styles.urlField}>
          <TextInput
            label="Base URL"
            placeholder="http://127.0.0.1:8188"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
          />
          <button
            type="button"
            className={styles.urlDefault}
            onClick={() => setBaseUrl(COMFY_DEFAULT_URL)}
          >
            Use default
          </button>
        </div>

        <TextInput
          label="Install path"
          placeholder="e.g. F:/VAIProjects/ComfyUI"
          value={installPath}
          onChange={(e) => setInstallPath(e.currentTarget.value)}
        />

        <TextInput
          label="API key (optional)"
          placeholder="leave empty for local ComfyUI"
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
        />

        <div className={styles.sub} style={{ marginTop: 16 }}>
          ComfyUI's input / output directories. Leave empty to use the
          install-path defaults <code>&lt;install&gt;/input</code> and{" "}
          <code>&lt;install&gt;/output</code>. Override only if you run ComfyUI
          with <code>--input-directory</code> / <code>--output-directory</code>.
          Phase 3's generation cycle uploads session images here, reads
          SaveImage results from output, and (when the per-session toggle is
          on) deletes the uploaded files after a run.
        </div>

        <TextInput
          label="Input directory (optional)"
          placeholder={inputPlaceholder}
          value={inputDir}
          onChange={(e) => setInputDir(e.currentTarget.value)}
        />
        {effectiveInput && (
          <div className={styles.sub}>
            Resolved: <code>{effectiveInput}</code>
          </div>
        )}

        <TextInput
          label="Output directory (optional)"
          placeholder={outputPlaceholder}
          value={outputDir}
          onChange={(e) => setOutputDir(e.currentTarget.value)}
        />
        {effectiveOutput && (
          <div className={styles.sub}>
            Resolved: <code>{effectiveOutput}</code>
          </div>
        )}

        <div className={styles.actionRow}>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {save.isPending ? "Saving…" : "Save endpoint"}
          </Button>
          <Button
            icon={<Icon name="RotateCw" size={12} />}
            onClick={() => check.mutate()}
            disabled={check.isPending || !cfg.data?.configured}
            title={
              cfg.data?.configured
                ? "Verify URL and install path"
                : "Save the endpoint first to enable the check"
            }
          >
            {check.isPending ? "Checking…" : "Test connection"}
          </Button>
        </div>

        {check.data && (
          <div className={styles.checkResults}>
            <CheckLine label="URL" field={check.data.url} />
            <CheckLine label="Install path" field={check.data.install_path} />
          </div>
        )}
        {check.error && (
          <div className={styles.checkLine} data-tone="err" role="alert">
            <Icon name="AlertCircle" size={14} className={styles.checkLineIcon} />
            <div>
              <div className={styles.checkLineLabel}>Check failed</div>
              <div className={styles.checkLineDetail}>{String(check.error)}</div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function CheckLine({ label, field }: { label: string; field: ComfyUiCheckField }) {
  return (
    <div className={styles.checkLine} data-tone={field.ok ? "ok" : "err"}>
      <Icon
        name={field.ok ? "Check" : "AlertCircle"}
        size={14}
        className={styles.checkLineIcon}
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className={styles.checkLineLabel}>{label}</span>
        {field.ok ? (
          <span className={styles.checkLineMeta}>{formatInfo(field.info)}</span>
        ) : (
          <span className={styles.checkLineDetail}>{field.detail ?? "Unknown error"}</span>
        )}
      </div>
    </div>
  );
}

function formatInfo(info: Record<string, unknown> | null): string {
  if (!info) return "OK";
  const entries = Object.entries(info).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return "OK";
  return entries.map(([k, v]) => `${k}: ${String(v)}`).join(" · ");
}
