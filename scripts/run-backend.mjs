import { existsSync } from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const projectRoot = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const venvPython = join(
  projectRoot,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
);
const python = existsSync(venvPython)
  ? venvPython
  : process.platform === "win32" ? "python" : "python3";
const hfHome = process.env.HF_HOME ?? join(projectRoot, ".venv", "hf-cache");
const environment = {
  ...process.env,
  MPLCONFIGDIR: join(projectRoot, ".matplotlib-cache"),
  HF_HOME: hfHome,
  UNIFACE_CACHE_DIR: process.env.UNIFACE_CACHE_DIR ?? join(projectRoot, ".venv", "uniface-cache"),
};

if (existsSync(join(hfHome, "hub", "models--Qwen--Qwen3-ASR-0.6B"))) {
  environment.HF_HUB_OFFLINE ??= "1";
  environment.TRANSFORMERS_OFFLINE ??= "1";
}

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
  { cwd: projectRoot, env: environment, stdio: "inherit" }
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
