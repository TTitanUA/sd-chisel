/** Compact agent list-item: name, last-run, output count. Used by
 *  variants A and D where agents render as a vertical list. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import type { Agent } from "@/api/comfy";
import styles from "./AgentCard.module.css";

export function AgentCard({
  agent,
  selected,
  isRunning,
  onSelect,
}: {
  agent: Agent;
  selected: boolean;
  isRunning: boolean;
  onSelect: () => void;
}) {
  const filledSlots = agent.output_slots.filter(
    (s) => s.last_value !== null && s.last_value !== undefined,
  ).length;
  return (
    <button
      type="button"
      className={`${styles.card} ${selected ? styles.selected : ""}`}
      onClick={onSelect}
    >
      <div className={styles.row}>
        <span className={styles.name}>{agent.name}</span>
        {isRunning && <span className={styles.spinner}>●●●</span>}
      </div>
      <div className={styles.meta}>
        {filledSlots} / {agent.output_slots.length} slots filled
        {agent.last_run_at && (
          <>
            {" · "}
            {timeAgo(agent.last_run_at)}
          </>
        )}
      </div>
    </button>
  );
}

function timeAgo(epochSeconds: number): string {
  const diff = Math.floor(Date.now() / 1000 - epochSeconds);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
