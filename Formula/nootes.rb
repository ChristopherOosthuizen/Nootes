class Nootes < Formula
  include Language::Python::Virtualenv

  desc "AI-powered CLI notes organizer with background daemon"
  homepage "https://github.com/OWNER/nootes"
  url "https://github.com/OWNER/nootes/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "MIT"

  depends_on "python@3.12"

  # Resource stanzas for Python dependencies.
  # Generate with: pip install homebrew-pypi-poet && poet nootes
  # Then paste the output resource blocks here.

  def install
    virtualenv_install_with_resources
  end

  service do
    run [opt_bin/"nootes", "watch"]
    keep_alive true
    log_path var/"log/nootes.log"
    error_log_path var/"log/nootes.log"
  end

  test do
    assert_match "nootes", shell_output("#{bin}/nootes --help")
  end
end
