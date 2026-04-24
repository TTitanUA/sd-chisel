import MDEditor from "@uiw/react-md-editor";
import { FormField } from "./FormField";

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
      <div data-color-mode="dark">
        <MDEditor height={220} value={value} onChange={(next) => onChange(next ?? "")} />
      </div>
    </FormField>
  );
}
