class Candid < Formula
  include Language::Python::Virtualenv

  desc "Local-first job-search copilot: match, tailor, track, prep, negotiate"
  homepage "https://github.com/K7S3/candid"
  url "https://files.pythonhosted.org/packages/source/c/candid/candid-0.3.0.tar.gz"
  # PLACEHOLDER: not yet published. On release, build the sdist and paste its
  # real sha256 here. Formula bumps happen at release time only.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "python@3.12"

  # candid is stdlib-only (no compiled deps, no extra requirements), so the
  # plain virtualenv install is enough; the optional pypdf PDF support can be
  # added later with `pipx runpip candid install pypdf`.
  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "candid", shell_output("#{bin}/candid --version")
  end
end
