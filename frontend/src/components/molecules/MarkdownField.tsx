import MDEditor, { commands } from "@uiw/react-md-editor";
import { FormField } from "./FormField";
import styles from "./MarkdownField.module.css";

const TOOLBAR = [
  commands.bold,
  commands.italic,
  commands.divider,
  commands.link,
  commands.code,
  commands.quote,
  commands.divider,
  commands.unorderedListCommand,
  commands.orderedListCommand,
  commands.divider,
  commands.codeEdit,
  commands.codePreview,
];

export function MarkdownField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  return (
    <FormField label={label} hint={hint}>
      <div className={styles.editor} data-color-mode="light">
        <MDEditor
          height={500}
          visibleDragbar
          value={value}
          onChange={(next) => onChange(next ?? "")}
          commands={TOOLBAR}
          extraCommands={[]}
        />
      </div>
    </FormField>
  );
}
