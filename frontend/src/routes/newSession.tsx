import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { TextArea, TextInput } from "@/components/molecules/FormField";
import {
  sessionsApi,
  useSessionInvalidation,
  type SessionType,
} from "@/api/sessions";
import {
  comfyApi,
  parseWorkflowConflict,
  useWorkflows,
  useWorkflowsInvalidation,
  type WorkflowSummary,
} from "@/api/comfy";
import styles from "./newSession.module.css";

const TYPE_OPTIONS: { value: SessionType; label: string; description: string }[] = [
  {
    value: "i2i",
    label: "i2i",
    description:
      "Image-to-image: upload a source image, the VL model analyses it, and the prompt is built around an editing brief.",
  },
  {
    value: "t2i",
    label: "t2i",
    description:
      "Text-to-image: prompt is built from chat (and any reference images you upload). All uploaded images are references — t2i has no main image. Uses the family's prompt_t2i guide.",
  },
  {
    value: "comfy",
    label: "comfy",
    description:
      "Bind a saved ComfyUI workflow. The session opens on a readiness panel that walks every node through configuration before any further work.",
  },
];

function defaultName(): string {
  return `untitled · ${new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

export default function NewSessionRoute() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const invalidate = useSessionInvalidation();
  const [type, setType] = useState<SessionType>("i2i");
  const [name, setName] = useState("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error("missing projectId");
      return sessionsApi.createSession(projectId, {
        session_type: type,
        name: name.trim() || defaultName(),
        model_name: null,
        use_negative: true,
        comfy_workflow_id: type === "comfy" ? workflowId : null,
      });
    },
    onSuccess: (s) => {
      invalidate.projects();
      navigate(`/projects/${s.project_id}/sessions/${s.id}`);
    },
  });

  if (!projectId) {
    return <div className={styles.wrap}>Pick a project from the sidebar first.</div>;
  }

  const canCreate = type !== "comfy" || !!workflowId;

  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <div>
          <h2 className={styles.title}>New session</h2>
          <p className={styles.subtitle}>
            Pick a session type. This cannot be changed later.
          </p>
        </div>

        <div className={styles.types} role="radiogroup" aria-label="Session type">
          {TYPE_OPTIONS.map((opt) => {
            const active = opt.value === type;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={active}
                className={[
                  styles.typeCard,
                  active ? styles.typeCardActive : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => setType(opt.value)}
              >
                <span className={styles.typeKey}>{opt.label}</span>
                <span className={styles.typeDesc}>{opt.description}</span>
              </button>
            );
          })}
        </div>

        {type === "comfy" && (
          <ComfyWorkflowPicker
            workflowId={workflowId}
            onSelect={setWorkflowId}
          />
        )}

        <TextInput
          label="Name (optional)"
          placeholder={defaultName()}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          maxLength={160}
        />

        {create.isError && (
          <div className={styles.error}>
            {(create.error as Error)?.message ?? "Could not create session."}
          </div>
        )}

        <div className={styles.foot}>
          <Button
            type="button"
            onClick={() => navigate(`/projects/${projectId}`)}
            disabled={create.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={() => create.mutate()}
            disabled={create.isPending || !canCreate}
            title={!canCreate ? "Pick or upload a workflow first" : undefined}
          >
            {create.isPending ? "Creating…" : "Create session"}
          </Button>
        </div>
      </div>
    </div>
  );
}


function ComfyWorkflowPicker({
  workflowId,
  onSelect,
}: {
  workflowId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const list = useWorkflows();
  const invalidate = useWorkflowsInvalidation();
  const workflows = list.data ?? [];

  // Auto-select the most recent workflow when the comfy tab opens for
  // the first time and the user hasn't picked anything yet.
  useEffect(() => {
    if (workflowId === null && workflows.length > 0) {
      onSelect(workflows[0].id);
    }
  }, [workflows, workflowId, onSelect]);

  const [uploadName, setUploadName] = useState("");
  const [uploadJson, setUploadJson] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(uploadJson);
      } catch (exc) {
        throw new Error(`Invalid JSON: ${(exc as Error).message}`);
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("Workflow JSON must be a top-level object (API format).");
      }
      try {
        return await comfyApi.createWorkflow({
          name: uploadName.trim() || "imported workflow",
          graph: parsed,
        });
      } catch (err) {
        const conflict = parseWorkflowConflict(err);
        if (conflict) {
          throw new Error(
            `Already saved as "${conflict.existing.name}" (id ${conflict.existing.id}). Pick it from the list or rename.`,
          );
        }
        throw err;
      }
    },
    onSuccess: (saved) => {
      setUploadJson("");
      setUploadName("");
      setUploadError(null);
      invalidate();
      onSelect(saved.id);
    },
    onError: (err) => setUploadError((err as Error).message),
  });

  return (
    <div className={styles.workflowSection}>
      <div className={styles.workflowSectionTitle}>Saved workflows</div>
      {list.isLoading && <div className={styles.workflowEmpty}>Loading…</div>}
      {!list.isLoading && workflows.length === 0 && (
        <div className={styles.workflowEmpty}>
          No workflows yet — paste a workflow JSON below to add one.
        </div>
      )}
      {workflows.length > 0 && (
        <div className={styles.workflowList}>
          {workflows.map((w) => (
            <WorkflowRow
              key={w.id}
              workflow={w}
              active={w.id === workflowId}
              onSelect={() => onSelect(w.id)}
            />
          ))}
        </div>
      )}

      <div className={styles.uploadDivider}>or upload</div>

      <TextInput
        label="Workflow name"
        placeholder="e.g. SDXL t2i — quick"
        value={uploadName}
        onChange={(e) => setUploadName(e.currentTarget.value)}
        maxLength={200}
      />
      <TextArea
        label="Workflow JSON (API format)"
        hint="Use the canvas's Save (API Format) export — the format with node-id keys, not the regular Save."
        placeholder='{"3": {"class_type": "KSampler", "inputs": { ... }}, ...}'
        value={uploadJson}
        onChange={(e) => setUploadJson(e.currentTarget.value)}
        spellCheck={false}
        rows={6}
      />
      {uploadError && <div className={styles.error}>{uploadError}</div>}
      <div>
        <Button
          type="button"
          onClick={() => upload.mutate()}
          disabled={upload.isPending || !uploadJson.trim()}
        >
          {upload.isPending ? "Uploading…" : "Save workflow"}
        </Button>
      </div>
    </div>
  );
}


function WorkflowRow({
  workflow,
  active,
  onSelect,
}: {
  workflow: WorkflowSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const created = useMemo(
    () => new Date(workflow.created_at * 1000).toLocaleString(),
    [workflow.created_at],
  );
  return (
    <button
      type="button"
      className={[
        styles.workflowRow,
        active ? styles.workflowRowActive : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={onSelect}
      role="radio"
      aria-checked={active}
    >
      <span className={styles.workflowRowName}>{workflow.name}</span>
      <span className={styles.workflowRowMeta}>{created}</span>
    </button>
  );
}
