import { useContext } from "react";
import {
  ComfyContext,
  type ComfyContextShape,
} from "./ComfyProvider";

export function useComfy(): ComfyContextShape {
  const ctx = useContext(ComfyContext);
  if (!ctx) {
    throw new Error("useComfy must be used inside ComfyProvider");
  }
  return ctx;
}
