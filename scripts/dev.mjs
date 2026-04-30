#!/usr/bin/env node
// Run backend (uvicorn) and frontend (Vite) in parallel with merged stdout.
// Each line is prefixed with [be]/[fe] in colour. Ctrl+C stops both.
// Cross-platform: relies only on Node's child_process.spawn.

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";

// shell:true so PATH lookup and Windows .cmd shims (pnpm.cmd) work uniformly.
// We pass the full command as a single string and an empty args array, which
// sidesteps Node's DEP0190 deprecation warning about shell + args[].
const spawnOpts = (cwd) => ({ cwd, shell: true, env: {
  ...process.env,
  PYTHONUNBUFFERED: "1",
  FORCE_COLOR: "1",
}});

const procs = [
  { tag: "be", color: 36, command: "uv run dev", cwd: path.join(repoRoot, "backend")  },
  { tag: "fe", color: 35, command: "pnpm dev",   cwd: path.join(repoRoot, "frontend") },
];

const reset = "\x1b[0m";
function makePrefixer(tag, color) {
  const prefix = `\x1b[${color}m[${tag}]${reset} `;
  let buf = "";
  return (chunk) => {
    buf += chunk.toString("utf8");
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() ?? "";
    for (const line of lines) process.stdout.write(prefix + line + "\n");
  };
}

let stopping = false;
const children = [];

function stopAll(reason) {
  if (stopping) return;
  stopping = true;
  if (reason) process.stdout.write(`\n[dev] ${reason}; stopping the other...\n`);
  for (const child of children) {
    if (child.killed || child.exitCode !== null) continue;
    if (isWindows) {
      // taskkill kills the whole process tree (uvicorn → python, pnpm → node).
      try { spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" }); }
      catch { /* ignore */ }
    } else {
      try { process.kill(-child.pid, "SIGTERM"); } catch { /* ignore */ }
    }
  }
}

for (const { tag, color, command, cwd } of procs) {
  const opts = spawnOpts(cwd);
  if (!isWindows) opts.detached = true; // own process group → kill tree via -pid
  const child = spawn(command, [], opts);
  children.push(child);

  const onLine = makePrefixer(tag, color);
  child.stdout.on("data", onLine);
  child.stderr.on("data", onLine);
  child.on("error", (err) => {
    process.stdout.write(`\x1b[${color}m[${tag}]${reset} spawn error: ${err.message}\n`);
    stopAll(`${tag} failed to start`);
  });
  child.on("exit", (code, signal) => {
    const why = signal ? `signal ${signal}` : `code ${code}`;
    stopAll(`${tag} exited (${why})`);
  });
}

for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(sig, () => stopAll(`received ${sig}`));
}
