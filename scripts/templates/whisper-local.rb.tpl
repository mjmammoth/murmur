class WhisperLocal < Formula
  include Language::Python::Virtualenv

  desc "Local real-time voice transcription TUI using Whisper"
  homepage "https://github.com/$REPOSITORY"
  url "$WHEEL_URL"
  sha256 "$WHEEL_SHA256"
  license "MIT"

  depends_on arch: :arm64
  depends_on "portaudio"
  depends_on "python@3.12"
  depends_on "whisper-cpp"

  resource "whisper-local-tui" do
    url "$TUI_URL"
    sha256 "$TUI_SHA256"
  end

  def install
    virtualenv_create(libexec, "python3.12")
    # Strip Homebrew's SHA256 cache prefix to restore PEP 427 wheel filename for pip
    wheel_name = cached_download.basename.to_s.sub(/\A[0-9a-f]{64}--/i, "")
    wheel_path = buildpath/wheel_name
    cp cached_download, wheel_path
    # Install wheel with dependencies from PyPI (venv.pip_install uses --no-deps)
    system "python3.12", "-m", "pip", "--python=#{libexec}/bin/python",
           "install", "--no-cache-dir", wheel_path

    # Pre-set bundled dylib IDs to the path Homebrew's post-install expects,
    # so its relinking step finds them already correct and skips them.
    # Some pip wheel dylibs (e.g. PyAV's FFmpeg libs) have Mach-O headers
    # too small for the long opt-prefix path.  Stripping the informational
    # LC_SOURCE_VERSION load command frees enough header space.
    Dir.glob(libexec/"lib/python3.12/site-packages/**/*.dylib", File::FNM_DOTMATCH) do |dylib|
      chmod 0644, dylib
      rel = Pathname.new(dylib).relative_path_from(prefix)
      target_id = "#{opt_prefix}/#{rel}"

      # Strip code signature so header edits don't invalidate it.
      quiet_system "codesign", "--remove-signature", dylib
      # Remove LC_SOURCE_VERSION (16 bytes) to widen header padding.
      mv "#{dylib}.tmp", dylib if quiet_system "vtool", "-remove-source-version",
                                                         "-output", "#{dylib}.tmp", dylib

      MachO::Tools.change_dylib_id(dylib, target_id)
      system "codesign", "--force", "--sign", "-", dylib
    end

    resource("whisper-local-tui").stage do
      (libexec/"bin").install "whisper-local-tui"
    end
    chmod 0755, libexec/"bin/whisper-local-tui"

    tui_bin = libexec/"bin/whisper-local-tui"
    (bin/"whisper-local").write_env_script(
      libexec/"bin/whisper-local", WHISPER_LOCAL_TUI_BIN: tui_bin
    )
    if (libexec/"bin/whisper.local").exist?
      (bin/"whisper.local").write_env_script(
        libexec/"bin/whisper.local", WHISPER_LOCAL_TUI_BIN: tui_bin
      )
    end
  end

  def caveats
    <<~EOS
      whisper.local requires macOS microphone + input monitoring permissions.
      Grant permissions in System Settings > Privacy & Security.

      First run downloads the selected model and may take a few minutes.

      Optional RNNoise support:
        brew install --cask rnnoise
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/whisper-local --help")
    assert_match "bridge", shell_output("#{bin}/whisper-local bridge --help")
  end
end
