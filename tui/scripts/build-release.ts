import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

type PackageJson = {
  version: string;
};

function run(command: string, args: string[], cwd: string): string {
  const result = spawnSync(command, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf-8",
  });
  if (result.status !== 0) {
    throw new Error(
      `Command failed: ${command} ${args.join(" ")}\n${result.stderr || result.stdout}`,
    );
  }
  return result.stdout.trim();
}

function main(): void {
  const scriptDir = dirname(fileURLToPath(import.meta.url));
  const tuiRoot = resolve(scriptDir, "..");
  const repoRoot = resolve(tuiRoot, "..");

  const packageJsonPath = resolve(tuiRoot, "package.json");
  const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8")) as PackageJson;

  const arch = "darwin-arm64";
  const distRoot = resolve(repoRoot, "dist", "tui");
  const binDir = resolve(distRoot, arch);
  const binPath = resolve(binDir, "whisper-local-tui");
  const tarPath = resolve(distRoot, `whisper-local-tui-${arch}.tar.gz`);
  const manifestPath = resolve(distRoot, "manifest.json");

  mkdirSync(binDir, { recursive: true });

  run(
    "bun",
    [
      "build",
      "src/index.tsx",
      "--compile",
      "--production",
      "--target=bun-darwin-arm64",
      "--outfile",
      binPath,
    ],
    tuiRoot,
  );

  chmodSync(binPath, 0o755);

  run("tar", ["-czf", tarPath, "-C", binDir, "whisper-local-tui"], repoRoot);

  const gitSha = run("git", ["rev-parse", "HEAD"], repoRoot);
  const manifest = {
    name: "whisper-local-tui",
    version: packageJson.version,
    arch,
    build_timestamp: new Date().toISOString(),
    git_sha: gitSha,
    binary: "whisper-local-tui",
    tarball: `whisper-local-tui-${arch}.tar.gz`,
  };
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  // Short success output for logs.
  process.stdout.write(`Built ${tarPath}\n`);
}

main();
