import { chmodSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { devNull } from "node:os";
import solidTransformPlugin from "@opentui/solid/bun-plugin";

type PackageJson = {
  version: string;
  dependencies?: Record<string, string>;
};

type BuildTarget = {
  id: string;
  bunTarget: string;
  binaryName: string;
  archiveName: string;
};

const DEFAULT_TARGET_IDS = [
  "darwin-arm64",
  "darwin-x64",
  "linux-x64",
  "linux-arm64",
  "windows-x64",
] as const;

function run(command: string, args: string[], cwd: string): string {
  const result = spawnSync(command, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf-8",
  });
  if (result.error) {
    const errorCode = (result.error as NodeJS.ErrnoException).code;
    const codeSuffix = errorCode ? ` (${String(errorCode)})` : "";
    throw new Error(
      `Command failed to start: ${command} ${args.join(" ")}\n${result.error.message}${codeSuffix}`,
    );
  }
  if (result.status !== 0) {
    throw new Error(
      `Command failed: ${command} ${args.join(" ")}\n${result.stderr || result.stdout}`,
    );
  }
  return result.stdout.trim();
}

function parseRequestedTargets(): readonly string[] {
  const cliArg = process.argv.find((arg) => arg.startsWith("--targets="));
  const fromCli = cliArg ? cliArg.slice("--targets=".length) : "";
  const fromEnv = process.env.WHISPER_LOCAL_TUI_TARGETS ?? "";
  const raw = fromCli || fromEnv;
  if (!raw.trim()) {
    return DEFAULT_TARGET_IDS;
  }
  const parsed = Array.from(
    new Set(
      raw
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
  if (parsed.length === 0) {
    return DEFAULT_TARGET_IDS;
  }
  return parsed;
}

function resolveTargets(requested: readonly string[]): BuildTarget[] {
  const supported = new Set(DEFAULT_TARGET_IDS);
  const targets: BuildTarget[] = [];
  for (const id of Array.from(new Set(requested))) {
    if (!supported.has(id as (typeof DEFAULT_TARGET_IDS)[number])) {
      throw new Error(`Unsupported target '${id}'. Supported targets: ${DEFAULT_TARGET_IDS.join(", ")}`);
    }
    const isWindows = id.startsWith("windows-");
    const binaryName = isWindows ? "whisper-local-tui.exe" : "whisper-local-tui";
    targets.push({
      id,
      bunTarget: `bun-${id}`,
      binaryName,
      archiveName: `whisper-local-tui-${id}.tar.gz`,
    });
  }
  return targets;
}

function targetInstallPlatform(target: BuildTarget): { os: string; cpu: string } {
  const [rawOs, rawCpu] = target.id.split("-");
  if (!rawOs || !rawCpu) {
    throw new Error(`Invalid build target id '${target.id}'`);
  }

  return { os: rawOs === "windows" ? "win32" : rawOs, cpu: rawCpu };
}

function targetCorePackageName(target: BuildTarget): string {
  const platform = targetInstallPlatform(target);
  return `@opentui/core-${platform.os}-${platform.cpu}`;
}

function normalizeVersionRange(versionRange: string): string {
  const match = versionRange.match(/\d+\.\d+\.\d+/);
  if (!match) {
    throw new Error(
      `Unsupported @opentui/core version range '${versionRange}'. Expected semver-like value.`,
    );
  }
  return match[0];
}

function runtimePackagePath(tuiRoot: string, packageName: string): string {
  return resolve(tuiRoot, "node_modules", ...packageName.split("/"));
}

function runtimePackageIsPresent(tuiRoot: string, packageName: string): boolean {
  const packagePath = runtimePackagePath(tuiRoot, packageName);
  return (
    existsSync(packagePath) &&
    existsSync(resolve(packagePath, "package.json")) &&
    existsSync(resolve(packagePath, "index.ts"))
  );
}

async function fetchRuntimePackageTarball(
  {
    packageName,
    version,
    tuiRoot,
  }: {
    packageName: string;
    version: string;
    tuiRoot: string;
  },
): Promise<void> {
  const packageSlug = packageName.includes("/") ? packageName.split("/")[1] : packageName;
  const tarballFile = `${packageSlug}-${version}.tgz`;
  const packageUrl = `https://registry.npmjs.org/${encodeURIComponent(packageName)}/-/${tarballFile}`;
  const timeoutMs = 30_000;
  const signal = AbortSignal.timeout(timeoutMs);
  let tarballBuffer: Buffer;
  try {
    const response = await fetch(packageUrl, {
      headers: { "User-Agent": "whisper-local-build-release" },
      signal,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to download ${packageName}@${version} tarball: ${response.status} ${response.statusText}`,
      );
    }
    tarballBuffer = Buffer.from(await response.arrayBuffer());
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(
        `Timed out downloading ${packageName}@${version} tarball after ${timeoutMs}ms`,
      );
    }
    throw err;
  }
  const tempDir = resolve(tuiRoot, ".build-release-tmp");
  mkdirSync(tempDir, { recursive: true });
  const tarballPath = resolve(tempDir, tarballFile);
  writeFileSync(tarballPath, tarballBuffer);

  const packagePath = runtimePackagePath(tuiRoot, packageName);
  mkdirSync(packagePath, { recursive: true });
  try {
    run(
      "tar",
      ["-xzf", tarballPath, "-C", packagePath, "--strip-components=1"],
      tuiRoot,
    );
  } finally {
    if (existsSync(tarballPath)) {
      unlinkSync(tarballPath);
    }
  }
}

async function main(): Promise<void> {
  const scriptDir = dirname(fileURLToPath(import.meta.url));
  const tuiRoot = resolve(scriptDir, "..");
  const repoRoot = resolve(tuiRoot, "..");

  const packageJsonPath = resolve(tuiRoot, "package.json");
  let packageJson: PackageJson;
  try {
    packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8")) as PackageJson;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`Failed to read/parse package.json at ${packageJsonPath}: ${msg}`);
  }
  if (typeof packageJson.version !== "string" || packageJson.version.trim().length === 0) {
    throw new Error(`package.json at ${packageJsonPath} is missing a valid "version" field`);
  }

  const targets = resolveTargets(parseRequestedTargets());
  const distRoot = resolve(repoRoot, "dist", "tui");
  mkdirSync(distRoot, { recursive: true });
  const coreVersionRange = packageJson.dependencies?.["@opentui/core"];
  if (!coreVersionRange) {
    throw new Error("package.json is missing dependency '@opentui/core'");
  }
  const coreVersion = normalizeVersionRange(coreVersionRange);

  const bundlePath = resolve(tuiRoot, ".build-tmp.js");
  const buildResult = await Bun.build({
    entrypoints: [resolve(tuiRoot, "src/index.tsx")],
    outdir: tuiRoot,
    naming: ".build-tmp.js",
    target: "bun",
    minify: true,
    plugins: [solidTransformPlugin],
  });
  if (!buildResult.success) {
    throw new Error(`Bun.build() failed:\n${buildResult.logs.map(String).join("\n")}`);
  }

  try {
    for (const target of targets) {
      const binDir = resolve(distRoot, target.id);
      const binPath = resolve(binDir, target.binaryName);
      const archivePath = resolve(distRoot, target.archiveName);
      const installPlatform = targetInstallPlatform(target);
      const runtimePackageName = targetCorePackageName(target);

      mkdirSync(binDir, { recursive: true });

      // `@opentui/core` uses optional target packages. Re-run install with the
      // target platform so the matching runtime package is present before compile.
      run(
        "bun",
        [
          "install",
          "--frozen-lockfile",
          "--no-save",
          "--force",
          `--os=${installPlatform.os}`,
          `--cpu=${installPlatform.cpu}`,
          `${runtimePackageName}@${coreVersion}`,
        ],
        tuiRoot,
      );
      if (!runtimePackageIsPresent(tuiRoot, runtimePackageName)) {
        await fetchRuntimePackageTarball({
          packageName: runtimePackageName,
          version: coreVersion,
          tuiRoot,
        });
      }
      if (!runtimePackageIsPresent(tuiRoot, runtimePackageName)) {
        throw new Error(
          `Missing required runtime package after install/fallback for target ${target.id}: ${runtimePackageName}`,
        );
      }

      const compileResult = spawnSync(
        "bun",
        [
          "build",
          bundlePath,
          "--compile",
          "--production",
          `--target=${target.bunTarget}`,
          "--outfile",
          binPath,
        ],
        {
          cwd: tuiRoot,
          stdio: ["ignore", "pipe", "pipe"],
          encoding: "utf-8",
          env: { ...process.env, BUN_CONFIG_FILE: devNull },
        },
      );
      if (compileResult.status !== 0) {
        throw new Error(
          `Compile failed for ${target.id}: bun build --compile\n${compileResult.stderr || compileResult.stdout}`,
        );
      }
      if (!target.id.startsWith("windows-")) {
        chmodSync(binPath, 0o755);
      }

      run("tar", ["-czf", archivePath, "-C", binDir, target.binaryName], repoRoot);
    }
  } finally {
    if (existsSync(bundlePath)) {
      try {
        unlinkSync(bundlePath);
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code !== "ENOENT") {
          throw err;
        }
      }
    }
  }

  const gitSha = run("git", ["rev-parse", "HEAD"], repoRoot);
  const manifestPath = resolve(distRoot, "manifest.json");
  const manifest = {
    name: "whisper-local-tui",
    version: packageJson.version,
    build_timestamp: new Date().toISOString(),
    git_sha: gitSha,
    artifacts: targets.map((target) => ({
      target: target.id,
      binary: target.binaryName,
      archive: target.archiveName,
    })),
  };
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  process.stdout.write(
    `Built TUI artifacts: ${targets.map((item) => item.archiveName).join(", ")}\n`,
  );
}

await main();
