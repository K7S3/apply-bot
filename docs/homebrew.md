# Install with Homebrew

The fastest way to install candid on macOS (or Linux with Homebrew) is the
`K7S3/tap` tap.

## Tap and install

```bash
brew tap K7S3/tap
brew install candid
```

## Upgrade

```bash
brew upgrade candid
```

## Uninstall

```bash
brew uninstall candid
brew untap K7S3/tap   # optional: remove the tap as well
```

## Verify

After install you should see the version:

```bash
candid --version
```

## For maintainers: bump the formula on release

The formula lives at `Formula/candid.rb` and is pinned to a specific
version and sdist hash, so every release needs a bump:

1. Build and upload the release to PyPI (this creates the sdist the formula
   points at). See the release workflow for the exact steps.
2. Get the sdist sha256:
   ```bash
   curl -sL https://files.pythonhosted.org/packages/source/c/candid/candid-<VERSION>.tar.gz | shasum -a 256
   ```
   (Replace `<VERSION>` with the new version.)
3. In `Formula/candid.rb`, update the `url` and paste the real `sha256`,
   replacing the `PLACEHOLDER` value.
4. Run the tap's CI formula audit (`brew audit --new candid`) and the test
   block: `brew test candid`.
5. Commit and push; users get the new version via `brew upgrade candid`.

Until the first real PyPI release, the `sha256` in the formula is a marked
`PLACEHOLDER` and the formula is not installable.
