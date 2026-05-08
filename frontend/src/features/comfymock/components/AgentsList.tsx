/** Vertical list of agents + "create" actions. The "+ add" button
 *  expands an inline name input rather than using the native
 *  `window.prompt` (which is blocked in some sandboxed iframes and
 *  feels alien on a non-modal flow). The header also shows a
 *  coverage hint: how many `binding=llm` workflow slots still need
 *  an agent. See docs/comfy-agents-ui-mock-plan.md.
 */
import { useMemo, useState } from "react";
import { useCreateAgent, useSeedDefaultAgent } from "@/api/comfy";
import { useComfyMock } from "../state/useComfyMock";
import { AgentCard } from "./AgentCard";
import styles from "./AgentsList.module.css";

export function AgentsList() {
  const {
    session,
    agents,
    selectedAgentId,
    selectAgent,
    runningAgentIds,
    agentsLoading,
    slotMap,
  } = useComfyMock();
  const create = useCreateAgent(session.id);
  const seed = useSeedDefaultAgent(session.id);

  const empty = !agentsLoading && agents.length === 0;

  // Coverage: how many binding=llm slots still need a filler.
  const coverage = useMemo(() => {
    if (!slotMap) return null;
    const llm = slotMap.slot_map.slots.filter((s) => s.binding === "llm");
    if (llm.length === 0) return null;
    const bound = new Set<string>();
    for (const a of agents) {
      for (const s of a.output_slots) {
        if (s.bound_to?.workflow_slot_label) bound.add(s.bound_to.workflow_slot_label);
      }
    }
    const unbound = llm.filter((s) => !bound.has(s.label));
    return { total: llm.length, unbound };
  }, [slotMap, agents]);

  const [adding, setAdding] = useState(false);
  const [draftName, setDraftName] = useState("");

  function commitAdd() {
    const name = draftName.trim();
    if (!name) return;
    create.mutate({ name });
    setAdding(false);
    setDraftName("");
  }

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>Agents ({agents.length})</span>
        <button
          type="button"
          className={styles.add}
          onClick={() => {
            setAdding(true);
            setDraftName("New agent");
          }}
        >
          + add
        </button>
      </div>

      {adding && (
        <form
          className={styles.addForm}
          onSubmit={(e) => {
            e.preventDefault();
            commitAdd();
          }}
        >
          <input
            autoFocus
            className={styles.addInput}
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setAdding(false);
                setDraftName("");
              }
            }}
            placeholder="Agent name"
          />
          <button
            type="submit"
            className={styles.addOk}
            disabled={!draftName.trim() || create.isPending}
          >
            Create
          </button>
          <button
            type="button"
            className={styles.addCancel}
            onClick={() => {
              setAdding(false);
              setDraftName("");
            }}
          >
            cancel
          </button>
        </form>
      )}

      {coverage && (
        <div
          className={styles.coverage}
          data-tone={coverage.unbound.length === 0 ? "ok" : "warn"}
        >
          {coverage.unbound.length === 0 ? (
            <>
              All <strong>{coverage.total}</strong> LLM slots are bound by agents.
            </>
          ) : (
            <>
              <strong>{coverage.unbound.length}</strong> of{" "}
              <strong>{coverage.total}</strong> LLM slots still need an agent:{" "}
              {coverage.unbound.map((s, i) => (
                <span key={s.label}>
                  <code>{s.label}</code>
                  {i < coverage.unbound.length - 1 && ", "}
                </span>
              ))}
            </>
          )}
        </div>
      )}

      {empty && (
        <div className={styles.empty}>
          <div className={styles.emptyMsg}>
            No agents yet. Either create one manually or seed a default
            composer that covers every <code>binding=llm</code> workflow slot.
          </div>
          <button
            type="button"
            className={styles.seed}
            onClick={() => seed.mutate()}
            disabled={seed.isPending}
          >
            {seed.isPending ? "Seeding…" : "Create default composer"}
          </button>
          {seed.isError && (
            <div className={styles.error}>
              {(seed.error as Error)?.message ?? "Seed failed"}
            </div>
          )}
        </div>
      )}

      <div className={styles.list}>
        {agents.map((a) => (
          <AgentCard
            key={a.id}
            agent={a}
            selected={a.id === selectedAgentId}
            isRunning={runningAgentIds.has(a.id)}
            onSelect={() => selectAgent(a.id)}
          />
        ))}
      </div>
    </div>
  );
}
