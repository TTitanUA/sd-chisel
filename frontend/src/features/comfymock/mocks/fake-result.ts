/**
 * Render a placeholder "generation result" image for the gallery card +
 * snapshot viewer. A canvas with a coloured gradient + workflow name +
 * a few bound-slot labels overlaid as text. Returns a `data:image/png`
 * URL so the snapshot can stash it in localStorage. See
 * docs/comfy-agents-ui-mock-plan.md.
 */

export type FakeResultInput = {
  workflowName: string;
  boundValues: Record<string, unknown>;
  jobId: string;
};

const COLOR_PAIRS: Array<[string, string]> = [
  ["#1a1a2e", "#162447"],
  ["#0f3057", "#00587a"],
  ["#2d1b69", "#11052c"],
  ["#3a1c71", "#d76d77"],
  ["#44318d", "#2a1b3d"],
];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function renderFakeResult(input: FakeResultInput): string {
  const w = 512;
  const h = 512;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const [c1, c2] = COLOR_PAIRS[hash(input.jobId) % COLOR_PAIRS.length];
  const grad = ctx.createLinearGradient(0, 0, w, h);
  grad.addColorStop(0, c1);
  grad.addColorStop(1, c2);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  // Subtle noise band so cards aren't dead-flat.
  ctx.globalAlpha = 0.05;
  for (let i = 0; i < 200; i++) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2);
  }
  ctx.globalAlpha = 1;

  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "bold 28px system-ui, sans-serif";
  ctx.fillText(input.workflowName, 24, 56);

  ctx.fillStyle = "rgba(255,255,255,0.65)";
  ctx.font = "14px system-ui, sans-serif";
  ctx.fillText(`mock job ${input.jobId.slice(0, 8)}`, 24, 80);

  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.font = "13px system-ui, sans-serif";
  let y = 132;
  const entries = Object.entries(input.boundValues).slice(0, 8);
  for (const [label, value] of entries) {
    const summary =
      typeof value === "string"
        ? value.length > 60
          ? value.slice(0, 60) + "…"
          : value
        : String(value);
    ctx.fillText(`${label}: ${summary}`, 24, y);
    y += 24;
  }

  return canvas.toDataURL("image/png");
}
