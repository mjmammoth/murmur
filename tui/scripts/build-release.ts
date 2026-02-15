import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

type PackageJson = {
  version: string;
};

/**
 * Execute a command synchronously and return its trimmed standard output.
 *
 * @param command - The executable to run
 * @param args - Arguments to pass to the command
 * @param cwd - Working directory in which to run the command
 * @returns The command's stdout, trimmed of leading and trailing whitespace
 * @throws Error if the process exits with a non-zero status; the error message contains the command, arguments, and captured stderr or stdout
 */
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

/**
 * Builds and packages the TUI binary for macOS ARM64 and writes a release manifest.
 *
 * Performs a production build of the TUI, ensures the resulting binary is executable,
 * creates a tar.gz archive of the binary under dist/tui, writes a manifest.json
 * containing name, version, arch, build timestamp, git SHA, binary and tarball names,
 * and emits a short success message with the created tarball path.
 */
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