require "digest"

class MurmurPreview < Formula
  include Language::Python::Virtualenv

  desc "Local real-time voice transcription TUI using Whisper"
  homepage "https://github.com/$REPOSITORY"
  url "$WHEEL_URL"
  sha256 "$WHEEL_SHA256"
  license "MIT"

  depends_on "portaudio"
  depends_on "python@3.12"
  depends_on "whisper-cpp"

  conflicts_with "murmur", because: "preview formula installs the same executables"

  def install
    virtualenv_create(libexec, "python3.12")
    # Strip Homebrew's SHA256 cache prefix to restore PEP 427 wheel filename for pip
    wheel_name = cached_download.basename.to_s.sub(/\A[0-9a-f]{64}--/i, "")
    wheel_path = buildpath/wheel_name
    cp cached_download, wheel_path

    system "python3.12", "-m", "pip", "--python=#{libexec}/bin/python",
           "install", "--no-cache-dir", wheel_path

    if OS.mac?
      # Pre-set bundled dylib IDs to the path Homebrew's post-install expects,
      # so its relinking step finds them already correct and skips them.
      Dir.glob(libexec/"lib/python3.12/site-packages/**/*.dylib", File::FNM_DOTMATCH) do |dylib|
        chmod 0644, dylib
        rel = Pathname.new(dylib).relative_path_from(prefix)
        target_id = "#{opt_prefix}/#{rel}"

        quiet_system "codesign", "--remove-signature", dylib
        mv "#{dylib}.tmp", dylib if quiet_system "vtool", "-remove-source-version",
                                                           "-output", "#{dylib}.tmp", dylib

        MachO::Tools.change_dylib_id(dylib, target_id)
        system "codesign", "--force", "--sign", "-", dylib
      end
    end

    tui_assets = {
      darwin: {
        arm:   [
          "$TUI_URL_DARWIN_ARM64",
          "$TUI_SHA256_DARWIN_ARM64",
        ],
        intel: [
          "$TUI_URL_DARWIN_X64",
          "$TUI_SHA256_DARWIN_X64",
        ],
      },
      linux:  {
        arm:   [
          "$TUI_URL_LINUX_ARM64",
          "$TUI_SHA256_LINUX_ARM64",
        ],
        intel: [
          "$TUI_URL_LINUX_X64",
          "$TUI_SHA256_LINUX_X64",
        ],
      },
    }

    platform_key = if OS.mac?
      :darwin
    elsif OS.linux?
      :linux
    else
      odie "Unsupported platform for murmur formula"
    end
    arch_key = if Hardware::CPU.arm?
      :arm
    elsif Hardware::CPU.intel?
      :intel
    else
      odie "Unsupported CPU architecture for murmur formula"
    end
    tui_url, tui_sha = tui_assets.fetch(platform_key).fetch(arch_key)
    expected_binary_name = "murmur-tui"

    tui_archive = buildpath/"murmur-tui.tar.gz"
    system "curl", "-fsSL", "-o", tui_archive, tui_url

    actual_sha = Digest::SHA256.file(tui_archive).hexdigest
    odie "TUI artifact SHA mismatch" if actual_sha != tui_sha

    (libexec/"bin").mkpath
    extraction_marker = buildpath/"murmur-tui-path.txt"
    extraction_script = <<~PY
      from pathlib import Path
      import sys

      from murmur.archive_extract import install_tui_binary_from_archive

      archive_path = Path(sys.argv[1])
      target_dir = Path(sys.argv[2])
      expected_binary_name = sys.argv[3]
      marker_path = Path(sys.argv[4])
      installed = install_tui_binary_from_archive(
          archive_path=archive_path,
          target_dir=target_dir,
          expected_binary_name=expected_binary_name,
      )
      marker_path.write_text(str(installed), encoding="utf-8")
    PY
    system libexec/"bin/python", "-c", extraction_script,
           tui_archive, libexec/"bin", expected_binary_name, extraction_marker

    tui_bin = Pathname.new(extraction_marker.read.strip)
    chmod 0755, tui_bin
    (bin/"murmur").write_env_script(
      libexec/"bin/murmur", MURMUR_TUI_BIN: tui_bin
    )
  end

  def caveats
    <<~EOS
      murmur can run as a background service:
        murmur start
        murmur status
        murmur tui

      On Wayland, global key swallowing may be unavailable.
      Bind a desktop shortcut to:
        murmur trigger toggle

      First run downloads the selected model and may take a few minutes.
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/murmur --help")
    assert_match "Service", shell_output("#{bin}/murmur status")
  end
end
