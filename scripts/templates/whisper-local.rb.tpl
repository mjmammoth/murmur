class WhisperLocal < Formula
  include Language::Python::Virtualenv

  desc "Local real-time voice transcription TUI using Whisper"
  homepage "https://github.com/$REPOSITORY"
  url "$WHEEL_URL"
  sha256 "$WHEEL_SHA256"
  version "$VERSION"
  license "MIT"

  depends_on arch: :arm64
  depends_on "python@3.12"
  depends_on "portaudio"
  depends_on "whisper-cpp"

  resource "whisper-local-tui" do
    url "$TUI_URL"
    sha256 "$TUI_SHA256"
  end

  def install
    venv = virtualenv_create(libexec, "python3.12")
    # Strip Homebrew's SHA256 cache prefix to restore PEP 427 wheel filename for pip
    wheel_name = cached_download.basename.to_s.sub(/\A[0-9a-f]{64}--/i, "")
    wheel_path = buildpath/wheel_name
    cp cached_download, wheel_path
    # Install wheel with dependencies from PyPI (venv.pip_install uses --no-deps)
    system "python3.12", "-m", "pip", "--python=#{libexec}/bin/python",
           "install", "--no-cache-dir", wheel_path

    # Fix bundled dylib IDs to use @loader_path so Homebrew skips relinking.
    # Pip wheels bundle native libs with short placeholder IDs that can't
    # accommodate the full Cellar path due to Mach-O header size limits.
    Dir.glob(libexec/"lib/python3.12/site-packages/**/*.dylib") do |dylib|
      quiet_system "install_name_tool", "-id", "@loader_path/#{File.basename(dylib)}", dylib
    end

    resource("whisper-local-tui").stage do
      (libexec/"bin").install "whisper-local-tui"
    end
    chmod 0755, libexec/"bin/whisper-local-tui"

    (bin/"whisper-local").write_env_script libexec/"bin/whisper-local", WHISPER_LOCAL_TUI_BIN: libexec/"bin/whisper-local-tui"
    if (libexec/"bin/whisper.local").exist?
      (bin/"whisper.local").write_env_script libexec/"bin/whisper.local", WHISPER_LOCAL_TUI_BIN: libexec/"bin/whisper-local-tui"
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
