// @ts-nocheck
// ClawSpec — OpenClaw gateway bridge plugin
// Registers `clawspec` tool for contract-first testing of skills and agents.
// Part of the ClawSuite: https://github.com/austinmao/clawspec

import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const DEFAULT_TIMEOUT_MS = 60_000;

function resolveConfig(api) {
  const cfg = api?.pluginConfig ?? {};
  const repoRoot = (typeof cfg.repoRoot === "string" && cfg.repoRoot.trim()) ||
    process.env.OPENCLAW_WORKSPACE || process.cwd();
  const pythonBin = (typeof cfg.pythonBin === "string" && cfg.pythonBin.trim()) ||
    path.join(repoRoot, "clawpipe", ".venv", "bin", "python");
  const timeoutMs = (typeof cfg.timeoutMs === "number" && Number.isFinite(cfg.timeoutMs))
    ? cfg.timeoutMs : DEFAULT_TIMEOUT_MS;
  return { repoRoot, pythonBin, timeoutMs };
}

function textResult(payload) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }] };
}

async function runCli(pythonBin, repoRoot, args, timeoutMs) {
  const { stdout, stderr } = await execFileAsync(
    pythonBin, ["-m", "clawspec", ...args],
    {
      cwd: repoRoot, timeout: timeoutMs, maxBuffer: 2 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: repoRoot },
    }
  );
  const raw = stdout.trim();
  if (!raw) throw new Error(`clawspec CLI empty stdout${stderr ? ` (${stderr.trim()})` : ""}`);
  try { return JSON.parse(raw); }
  catch { return { output: raw.slice(0, 2000), stderr: (stderr || "").trim().slice(0, 500) }; }
}

export function register(api) {
  const { repoRoot, pythonBin, timeoutMs } = resolveConfig(api);

  api.registerTool({
    name: "clawspec",
    description: "Contract-first testing for OpenClaw skills and agents. Validate contracts, run assertions, check coverage, manage baselines.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        action: {
          type: "string",
          enum: ["validate", "run", "init", "coverage", "baseline-capture", "baseline-show", "baseline-reset"],
          description: "Action to perform",
        },
        contract_path: { type: "string", description: "Path to contract YAML file" },
        scenario: { type: "string", description: "Scenario name to run" },
        target: { type: "string", description: "Target skill/agent to test" },
        runs_dir: { type: "string", description: "Directory containing run results" },
        output_format: { type: "string", enum: ["json", "text", "yaml"], description: "Output format" },
        baseline_name: { type: "string", description: "Baseline name for capture/show/reset" },
        count: { type: "number", description: "Number of runs for baseline capture" },
      },
      required: ["action"],
    },
    async execute(_id, params) {
      const action = String(params.action);
      let args;

      switch (action) {
        case "validate":
          if (!params.contract_path) return textResult({ status: "error", error: "contract_path required" });
          args = ["validate", String(params.contract_path)];
          break;
        case "run":
          if (!params.contract_path) return textResult({ status: "error", error: "contract_path required" });
          args = ["run", String(params.contract_path)];
          if (params.scenario) args.push("--scenario", String(params.scenario));
          if (params.target) args.push("--target", String(params.target));
          break;
        case "init":
          args = ["init"];
          if (params.target) args.push("--target", String(params.target));
          break;
        case "coverage":
          args = ["coverage"];
          if (params.runs_dir) args.push("--runs-dir", String(params.runs_dir));
          if (params.output_format) args.push("--format", String(params.output_format));
          break;
        case "baseline-capture":
          args = ["baseline", "capture"];
          if (params.baseline_name) args.push("--name", String(params.baseline_name));
          if (params.count) args.push("--count", String(params.count));
          break;
        case "baseline-show":
          args = ["baseline", "show"];
          if (params.baseline_name) args.push("--name", String(params.baseline_name));
          break;
        case "baseline-reset":
          args = ["baseline", "reset"];
          if (params.baseline_name) args.push("--name", String(params.baseline_name));
          break;
        default:
          return textResult({ status: "error", error: `Unknown action: ${action}` });
      }

      try {
        return textResult(await runCli(pythonBin, repoRoot, args, timeoutMs));
      } catch (err) {
        return textResult({ status: "error", error: err.message || String(err), action });
      }
    },
  });

  console.log("[clawspec] tool registered");
}

export function activate(api) { register(api); }
export default { register, activate };
