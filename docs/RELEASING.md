# Releasing

The repository and app releases are public. Share the
[latest release link](https://github.com/yimingluo-md/phewas_browser/releases/latest) so users
download the original DMG through a web browser. Study data is never part of a public release;
share `.phewasds` bundles separately through an approved institutional channel. There is no
auto-updater: a new version is a new DMG dragged over the old one; the dataset library in
Application Support is untouched.

The first public v0.5.0 macOS artifacts were built from commit `f778b395fdee2738c3d3bf34cfb185deab71f33d`
in Actions run `34341919407`, then signed locally with Developer ID, accepted by Apple's
notary service, stapled, and checked with Gatekeeper. The release includes `SHA256SUMS.txt`
and `release-info.json` with artifact hashes and notarization submission IDs. Preserve those
verified files when publishing; do not replace them with unsigned Actions artifacts.

## One-time setup for signed, notarized macOS builds

You need an Apple Developer Program membership (the $99/year individual or organization
account — **not** App Store distribution). Then:

1. **Developer ID Application certificate.** In Xcode → Settings → Accounts → *Manage
   Certificates* → **+** → *Developer ID Application* (or at developer.apple.com → Certificates).
   In Keychain Access, find "Developer ID Application: Your Name (TEAMID)", right-click →
   *Export…* as a `.p12` with a password.
2. **App-specific password** for notarization: appleid.apple.com → Sign-In and Security →
   App-Specific Passwords → generate one (name it "phewas notarization").
3. **Team ID**: developer.apple.com → Membership details (10 characters).
4. Add these **repository secrets** (GitHub → Settings → Secrets and variables → Actions):

   | Secret | Value |
   |---|---|
   | `APPLE_CERTIFICATE` | the `.p12`, base64-encoded: `base64 -i cert.p12 \| pbcopy` |
   | `APPLE_CERTIFICATE_PASSWORD` | the password you chose when exporting the `.p12` |
   | `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Your Name (TEAMID)` — exactly as Keychain Access shows it |
   | `APPLE_ID` | the Apple ID email of the developer account |
   | `APPLE_PASSWORD` | the app-specific password from step 2 |
   | `APPLE_TEAM_ID` | the Team ID from step 3 |

When these secrets exist, the *Release build* workflow imports the certificate into a temporary
keychain, signs every Mach-O of the frozen Python sidecar with the hardened runtime and the
app's entitlements (`scripts/sign_sidecar.sh`), lets Tauri sign and notarize the `.app`,
notarizes and staples the DMG, and verifies the result with `codesign`, `spctl` and `stapler`
before uploading. Tagged macOS release builds fail when signing is not configured, preventing
accidental publication of unsigned replacements. Manual workflow runs can still produce
ad-hoc development builds; these are not the public notarized release.

The entitlements (`apps/desktop/src-tauri/entitlements.plist`) disable library validation and
allow unsigned executable memory because the sidecar is a CPython process loading its own
extension modules; both are standard for embedded Python and accepted by notarization.

## Cutting a release

```bash
# bump the version in the four places that carry it (or run the helper):
scripts/set_version.sh 1.0.0
git commit -am "Release 1.0.0" && git tag v1.0.0 && git push && git push --tags
```

The tag triggers *Release build*; when all three targets finish, a GitHub Release named after
the tag is created with the DMGs (arm64 + Intel), zipped `.app`s and the Windows installer.
`Actions → Release build → Run workflow` builds the same artifacts from `main` without a tag.

## Handing a build to a collaborator

1. Send the public release link. They download the DMG for their Mac (Apple Silicon or Intel)
   in Safari or another web browser. Avoid email attachments and share the original DMG,
   rather than an unpacked `.app`.
2. Export the dataset for them: **Library → Export…** (or `phewas export <id> file.phewasds`).
   The bundle carries the dataset's own RUO notes and a checksum; send it the same way.
3. They open the DMG, copy the app to Applications (or `~/Applications` without administrator
   access), launch it, and use **Import… → Dataset bundle** to load the `.phewasds`.
   Imported data stays on their machine.

## Windows code signing (optional)

Windows builds are unsigned; SmartScreen shows *More info → Run anyway* once. An Authenticode
certificate (or Azure Trusted Signing) can be wired into `tauri.conf.json` → `bundle.windows`
later; nothing in the app depends on it.
