/** Full editor for the selected agent. Used by every variant — they
 *  just frame it differently (panel, strip, popover). Per-agent
 *  **Run** button fires the LLM emulator.
 *
 *  Note on `agent.source_scope` and `agent.loras_enabled`: those
 *  fields still exist on the backend record but the editor no longer
 *  surfaces them — the same controls are now per-input via the
 *  Source / LoRAs input slots, which give the user finer-grained
 *  scoping than a session-wide toggle. The backend defaults
 *  ("all" / false) stay where they were and don't get touched on
 *  save. See docs/comfy-agents-ui-mock-plan.md.
 */
import { useState } from "react";
import { useUpdateAgent, useDeleteAgent, type Agent } from "@/api/comfy";
import { useComfyMock } from "../state/useComfyMock";
import { AgentInputSlotsEditor } from "./AgentInputSlotsEditor";
import { AgentModelSection } from "./AgentModelSection";
import { AgentSlotsEditor } from "./AgentSlotsEditor";
import styles from "./AgentEditor.module.css";

export function AgentEditor({ agent }: { agent: Agent }) {
  const { runningAgentIds, runAgent, session } = useComfyMock();
  const update = useUpdateAgent(session.id);
  const remove = useDeleteAgent(session.id);

  const [name, setName] = useState(agent.name);
  const [prompt, setPrompt] = useState(agent.prompt);

  const isRunning = runningAgentIds.has(agent.id);
  const dirty = name !== agent.name || prompt !== agent.prompt;

  const save = async () => {
    await update.mutateAsync({
      agentId: agent.id,
      body: { name, prompt },
    });
  };

  return (
    <div className={styles.editor}>
      <div className={styles.field}>
        <label className={styles.fieldLabel}>Name</label>
        <input
          className={styles.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== agent.name) save();
          }}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Prompt</label>
        <textarea
          className={styles.textarea}
          rows={5}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onBlur={() => {
            if (prompt !== agent.prompt) save();
          }}
          placeholder="Describe what this agent should compose…"
        />
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.run}
          onClick={() => runAgent(agent.id)}
          disabled={isRunning || dirty}
          title={
            dirty
              ? "Save edits first (blur a field) before running."
              : isRunning
              ? "Running…"
              : "Run this agent (10 s)"
          }
        >
          {isRunning ? "Running… ●●●" : "Run agent"}
        </button>
        {dirty && (
          <button type="button" onClick={save}>
            Save
          </button>
        )}
        <button
          type="button"
          className={styles.delete}
          onClick={() => {
            if (confirm(`Delete agent "${agent.name}"?`)) {
              remove.mutate(agent.id);
            }
          }}
        >
          Delete agent
        </button>
      </div>

      <AgentModelSection agent={agent} />
      <AgentInputSlotsEditor agent={agent} />
      <AgentSlotsEditor agent={agent} />
    </div>
  );
}
