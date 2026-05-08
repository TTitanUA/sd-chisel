/** Workflow + readiness placeholder. Real readiness gating ships from
 *  features/comfy/; ComfyMock just surfaces the bound workflow id so
 *  the variant has something to show in the Nodes tab. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import { useComfyMock } from "../state/useComfyMock";
import styles from "./InspectorPanels.module.css";

export function NodesPanel() {
  const { session } = useComfyMock();
  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>Nodes</span>
      </div>
      <div className={styles.body}>
        <div className={styles.empty}>
          Workflow{" "}
          <code>{session.comfy_workflow_id?.slice(0, 8) ?? "unbound"}</code> —
          readiness panel ships in the real comfy workspace.
        </div>
      </div>
    </div>
  );
}
