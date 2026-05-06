import { useReadiness } from "@/api/comfy";
import type { Session } from "@/api/sessions";
import { Icon } from "@/components/atoms/Icon";
import { ComfyReadinessGate } from "@/features/comfy/readiness/ComfyReadinessGate";
import styles from "./InspectorRail.module.css";

/** Compact readiness summary inside the inspector rail. If readiness
 *  regresses (e.g. a workflow replace pulled in nodes that aren't in
 *  the catalog), the inline gate surfaces here so the user can fix
 *  the new misses without losing the workspace. */
export function NodesTab({ session }: { session: Session }) {
  const readiness = useReadiness(session.id);

  if (readiness.isLoading) {
    return <div className={styles.empty}>Loading readiness…</div>;
  }
  if (readiness.isError || !readiness.data) {
    return <div className={styles.empty}>Readiness unavailable.</div>;
  }

  const { ready, cards, error } = readiness.data;
  const blocking = cards.filter((c) => c.status !== "ready").length;

  if (ready) {
    return (
      <>
        <div className={styles.banner} data-tone="ok">
          <Icon name="Check" size={12} /> All {cards.length} node class
          {cards.length === 1 ? "" : "es"} are ready.
        </div>
        <div className={styles.empty}>
          The workflow's node classes are catalogued and installed. If you
          replace the workflow and a class isn't in the catalog, this tab
          surfaces the import wizard inline — no full-screen rewind.
        </div>
      </>
    );
  }

  return (
    <>
      <div className={styles.banner} data-tone="warn">
        <Icon name="AlertCircle" size={12} />{" "}
        {error ?? `${blocking} of ${cards.length} node class${cards.length === 1 ? "" : "es"} need attention.`}
      </div>
      <ComfyReadinessGate sessionId={session.id} />
    </>
  );
}
