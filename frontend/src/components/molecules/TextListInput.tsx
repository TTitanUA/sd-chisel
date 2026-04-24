import { TextInput } from "./FormField";

export function TextListInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}) {
  return (
    <TextInput
      label={label}
      value={value.join(", ")}
      placeholder={placeholder}
      onChange={(event) => {
        const next = event.currentTarget.value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        onChange([...new Set(next)]);
      }}
    />
  );
}
