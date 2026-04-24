import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import type { Family } from "@/api/library";
import fstyles from "@/components/molecules/LibraryFilterBar.module.css";

export function ModelFilterControls({
  families,
  familyId,
  onChange,
}: {
  families: Family[];
  familyId: string | null;
  onChange: (id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={fstyles.filters}>
      {familyId && (
        <span className={fstyles.chip}>
          <span className={fstyles.chipKind}>family</span>
          <span className={fstyles.chipVal}>{familyId}</span>
          <button
            type="button"
            className={fstyles.chipX}
            onClick={() => onChange(null)}
            aria-label="Remove filter"
          >
            <Icon name="X" size={9} />
          </button>
        </span>
      )}
      <div className={fstyles.wrap}>
        <button type="button" className={fstyles.addBtn} onClick={() => setOpen((o) => !o)}>
          <Icon name="Plus" size={10} />
          Family
        </button>
        {open && (
          <div className={fstyles.popover} role="dialog" aria-label="Filter by family">
            <div className={fstyles.popoverTab}>FAMILY</div>
            <div>
              {families.map((fam) => (
                <button
                  key={fam.id}
                  type="button"
                  className={fstyles.popoverRow}
                  onClick={() => {
                    onChange(fam.id);
                    setOpen(false);
                  }}
                >
                  {fam.display_name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {familyId && (
        <button
          type="button"
          className={fstyles.clear}
          onClick={() => {
            onChange(null);
            setOpen(false);
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}
