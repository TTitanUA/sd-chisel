import { useContext } from "react";
import {
  ComfyMockContext,
  type ComfyMockContextShape,
} from "./ComfyMockProvider";

export function useComfyMock(): ComfyMockContextShape {
  const ctx = useContext(ComfyMockContext);
  if (!ctx) {
    throw new Error("useComfyMock must be used inside ComfyMockProvider");
  }
  return ctx;
}
