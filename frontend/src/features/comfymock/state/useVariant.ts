/** URL `?variant=` reader/writer with localStorage fallback for last
 *  visited variant. See docs/comfy-agents-ui-mock-plan.md.
 *
 *  The mock playground has narrowed down to a single shipping
 *  layout — `d-tree-drawer`. The variant infrastructure stays around
 *  in case we want to A/B more layouts later, but right now the
 *  switcher only has one option. */
import { useCallback, useEffect, useState } from "react";

export const VARIANT_IDS = ["d-tree-drawer"] as const;
export type VariantId = (typeof VARIANT_IDS)[number];

export const VARIANT_LABEL: Record<VariantId, string> = {
  "d-tree-drawer": "D · tree: side drawer",
};

const STORAGE_KEY = "comfymock:variant";

function readUrlParam(): VariantId | null {
  const url = new URL(window.location.href);
  const raw = url.searchParams.get("variant");
  return (VARIANT_IDS as readonly string[]).includes(raw ?? "")
    ? (raw as VariantId)
    : null;
}

function readStorage(): VariantId | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return (VARIANT_IDS as readonly string[]).includes(raw ?? "")
      ? (raw as VariantId)
      : null;
  } catch {
    return null;
  }
}

export function useVariant(): [VariantId, (next: VariantId) => void] {
  const [variant, setVariantState] = useState<VariantId>(
    () => readUrlParam() ?? readStorage() ?? "d-tree-drawer",
  );

  // Keep state in sync with browser back/forward navigation.
  useEffect(() => {
    const onPop = () => {
      const next = readUrlParam();
      if (next && next !== variant) setVariantState(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [variant]);

  const setVariant = useCallback((next: VariantId) => {
    setVariantState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore quota */
    }
    const url = new URL(window.location.href);
    url.searchParams.set("variant", next);
    window.history.replaceState({}, "", url.toString());
  }, []);

  return [variant, setVariant];
}
