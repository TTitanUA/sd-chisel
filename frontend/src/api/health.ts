import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

type Health = { status: "ok" };

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/health"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
