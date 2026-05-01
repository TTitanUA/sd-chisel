import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { TextInput } from "@/components/molecules/FormField";
import {
  sessionsApi,
  useSessionInvalidation,
  type SessionType,
} from "@/api/sessions";
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
      "Text-to-image: prompt is built from chat alone with no source image. Workflow not yet implemented.",
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

  const create = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error("missing projectId");
      return sessionsApi.createSession(projectId, {
        session_type: type,
        name: name.trim() || defaultName(),
        model_name: null,
        use_negative: true,
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
            disabled={create.isPending}
          >
            {create.isPending ? "Creating…" : "Create session"}
          </Button>
        </div>
      </div>
    </div>
  );
}
