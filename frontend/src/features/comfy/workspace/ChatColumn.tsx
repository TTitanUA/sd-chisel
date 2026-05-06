import type { Session } from "@/api/sessions";
import { ChatPane } from "@/components/molecules/ChatPane";
import { PromptPane } from "@/components/organisms/PromptPane";
import styles from "./ChatColumn.module.css";

/** Left column of the comfy workspace.
 *
 * For Mock PR this composes the existing ChatPane + PromptPane (the
 * latter already renders the comfy payload preview). Phase 3 will
 * replace PromptPane here with per-slot editable textareas + a LoRA
 * list and per-slot copy buttons. */
export function ChatColumn({ session }: { session: Session }) {
  return (
    <div className={styles.column}>
      <div className={styles.chat}>
        <ChatPane session={session} />
      </div>
      <div className={styles.prompt}>
        <PromptPane session={session} />
      </div>
    </div>
  );
}
