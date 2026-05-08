/** Renders the "filled by …" badge that surfaces under every workflow
 *  slot. Two flavours:
 *
 *  - **agent filler** (binding=llm): a workflow slot is filled by some
 *    agent's output. Three states:
 *    - bound + has value: agent has run, value is ready.
 *    - bound + no value: agent claims this slot but hasn't run yet.
 *    - unbound: no agent owns this slot. Generate will fail.
 *  - **source filler** (binding=user_image): a workflow slot is fed
 *    by one of the session's source slots. Three states:
 *    - ready: source slot exists and has an image bound.
 *    - pending: source slot exists but no image bound yet.
 *    - unbound: no source-slot reference, or the referenced slot was
 *      deleted.
 *
 *  See docs/comfy-agents-ui-mock-plan.md.
 */
import type { SlotFiller, SourceFiller } from "./slot-helpers";
import styles from "./FillerHint.module.css";

export function FillerHint({
  filler,
  cls = styles,
}: {
  filler: SlotFiller | null;
  cls?: typeof styles;
}) {
  if (filler) {
    return (
      <div
        className={cls.line}
        data-state={filler.hasValue ? "ready" : "pending"}
      >
        <span className={cls.dot} aria-hidden="true" />
        <span className={cls.text}>
          filled by <strong>{filler.agentName}</strong> ›{" "}
          <code>{filler.outputLabel}</code>
        </span>
        {!filler.hasValue && (
          <span className={cls.tag}>not run yet</span>
        )}
      </div>
    );
  }
  return (
    <div className={cls.line} data-state="unbound">
      <span className={cls.dot} aria-hidden="true" />
      <span className={cls.text}>no agent bound — Generate will fail</span>
    </div>
  );
}

/** Renders the source-slot binding hint under a binding=user_image
 *  workflow slot. Mirrors FillerHint's three-state visual but for the
 *  Source-slot table instead of agents. */
export function SourceFillerHint({
  source,
  cls = styles,
}: {
  source: SourceFiller | null;
  cls?: typeof styles;
}) {
  if (!source) {
    return (
      <div className={cls.line} data-state="unbound">
        <span className={cls.dot} aria-hidden="true" />
        <span className={cls.text}>no source slot — pick one in the editor</span>
      </div>
    );
  }
  if (source.imageFilename) {
    return (
      <div className={cls.line} data-state="ready">
        <span className={cls.dot} aria-hidden="true" />
        <span className={cls.text}>
          source <strong>{source.slotKey}</strong> ›{" "}
          <code>{source.imageFilename}</code>
        </span>
      </div>
    );
  }
  return (
    <div className={cls.line} data-state="pending">
      <span className={cls.dot} aria-hidden="true" />
      <span className={cls.text}>
        source <strong>{source.slotKey}</strong> — image not bound yet
      </span>
      <span className={cls.tag}>unbound</span>
    </div>
  );
}
