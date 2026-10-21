# ComfyWebKit

ComfyWebKit is a downstream fork of [WebKit](https://webkit.org/) that exposes selected private APIs through the framework’s public headers so applications can use them directly. It also adds convenience APIs for media playback information and visible text extraction.

The changes currently focus on Cocoa APIs, including macOS-specific media and context menu functionality. The underlying browser engine and build tooling come from WebKit.

## What this fork exposes

### Now Playing information (macOS)

The `WKWebView (NowPlaying)` category exposes:

- `_requestActiveNowPlayingSessionInfo:` for the active Now Playing session’s control visibility, application registration, title, duration, current time, identifier, and update time.
- `_requestActiveNowPlayingSessionInfoWithPlayback:` adds playback state, artwork URL, and playback rate to that information.

### Text extraction

The `WKWebView (TextExtractionDebug)` category exposes `_debugTextWithConfiguration:completionHandler:` and adds `_debugTextVisibleTextWithCompletionHandler:`, a convenience method that creates a text extraction configuration with `filterOptions` set to zero.

These methods are annotated for macOS 26.4, iOS 26.4, and visionOS 26.4 and later.

### WebContent process identifier

`WKWebView._webProcessIdentifier` exposes the PID of the WebContent process hosting the page. Read it when needed: navigation or process termination can change the PID. Media decoding and audio output may run in other processes.

### Context menus (macOS)

`WKUIDelegate` exposes `_webView:getContextMenuFromProposedMenu:forElement:userInfo:completionHandler:` so applications can customize the proposed context menu.

`_WKContextMenuElementInfo` and `_WKHitTestResult` are included in the public framework headers and the `WebKit.h` umbrella header.

These APIs retain their underscore-prefixed names. “Public” here means exposed by **this fork**; they are not additions to Apple’s system WebKit SDK. Applications need to compile against and run with the ComfyWebKit build to use the fork’s additions.

### Individual user script removal

`WKUserContentController.h` exposes `removeUserScript:` to remove a specific `WKUserScript` without permanently removing other registered scripts.
```swift
webView.configuration.userContentController.removeUserScript(popupBlockingScript)
```
Unlike `removeAllUserScripts()`, this method preserves the remaining registered scripts and their order.

Implementation note: The current implementation removes all registered scripts internally, then re-adds every script except the specified one. It does not undo JavaScript that has already executed in existing pages.

### Content blocking notifications

`WKNavigationDelegate` exposes the optional `webView:didJustBlock:blockedURL:` delegate method, allowing applications to receive notifications when a URL is blocked by a registered content rule list.

The `blockedURL` parameter identifies the URL that triggered the blocking rule, enabling applications to monitor blocked requests, display blocking statistics, or provide feedback to users.

### WKWebView Focus on load 

`_setShouldSuppressFirstResponderChanges` allows control on the `WKWebView` for it to take firstResponder on load or not

### Allow Picture In Picture on macOS

`setAllowsPictureInPictureMediaPlayback` allows control on `WKPreferences` to allow picture in picture

**Usage:**

```swift
func webView(_ webView: WKWebView, didJustBlock blockedURL: URL) {
    print("Blocked URL: \(blockedURL)")
}
```

## Patch-based development in one checkout

Work and build in this directory. `WebKitBuild/` stays where it is. The published
branch keeps the Safari 7625 snapshot, patches, and workflow files; customized
source is committed only to a local development branch as an automatic baseline.
Those source commits are never merged into or pushed from the published branch.

### The normal cycle

```sh
git clone https://github.com/AryanRogye/ComfyWebKit.git
cd ComfyWebKit
python3 comfy-tools/patches.py setup
```

**Setup installs the safeguards, creates a fresh local `comfy-dev/...` branch, and
applies the entire patch series here, and records one local baseline commit.**
`git status` then shows only your new edits (plus any pre-existing workflow edits).
No second checkout is created. Now edit WebKit files, build, run your app, and test
as usual:

```sh
Tools/Scripts/build-webkit --debug
Tools/Scripts/run-webkit-app --debug /path/to/YourApp.app
```

When the change works:

```sh
./apply_patches.sh
```

Despite the historical filename, this command now **exports your additional edits
as the next numbered patch, restores the original upstream source, and switches
back to the publishing branch you started from**. The default patch subject is
`Local WebKit changes`. To give it a useful name:

```sh
./apply_patches.sh --subject "Expose the API needed by my app"
```

Then review and commit only the patch changes:

```sh
git diff -- comfy-patches/series
git status --short
# Open/review the new .patch file too (untracked files do not appear in git diff).
git add comfy-patches/
git commit -m "Add WebKit patch for my change"
```

Repeat `python3 comfy-tools/patches.py setup` whenever you want the customized
source back. It includes your new patch. Repeating setup during an active session
preserves your edits. Repeating `./apply_patches.sh` after finishing does nothing.
Finishing without additional source edits creates no patch and returns you to the
publishing branch. Do not manually switch branches during an active session.

The existing `WebKitBuild/`, `DerivedData`, and ignored build outputs are never
cleaned, moved, or included in a patch. This reuses the same build directory.
Files changed by applying/restoring patches can trigger incremental rebuilds;
the workflow does not promise zero recompilation.

### Abort and return to the publishing branch

Stay on the development branch and run:

```sh
python3 comfy-tools/patches.py abort
```

Abort returns to your starting branch (normally `main`) without creating or
refreshing patches. It first saves tracked/staged source edits as a recovery patch
under `.git/comfy-aborted-sessions/`; the command prints its exact path. The session
record also retains the original index tree and staged diff. Untracked source
files, workflow edits and staging, and ignored build artifacts stay in place.
No source edits are silently discarded. Repeating abort after completion does
nothing. An interrupted abort can be resumed by rerunning the same command.

To recover saved source edits later, run setup and apply the printed recovery file:

```sh
python3 comfy-tools/patches.py setup
git apply /absolute/path/printed/by/abort.patch
```

Use the same patch position (`--through`, if used) and patch series when recovering.
If finish has already begun exporting a patch, complete that transaction by
rerunning `./apply_patches.sh`; abort will refuse to interrupt it.

### New files and staged changes

Changes to tracked source files, deletions, binary files, and executable bits are
captured automatically. For new files use an explicit argument:

```sh
./apply_patches.sh --subject "Add a helper" --add Source/path/to/helper.cpp
```

Repeat `--add` for multiple files. New source files already staged with `git add`
are also included. Other untracked files are left alone, and ignored files cannot
be added through this command. Do not run `git commit` on the development branch.
Your changes are saved as a patch before the source files are restored.

Dirty README, tooling, patch files, and their staging are preserved through branch
switches; they are not folded into a new source patch. Setup refuses pre-existing
tracked/staged source edits rather than mixing them with the applied series.
An untracked file that collides with a patch also causes setup to stop safely.

### Update an existing patch

Start from the publishing branch, stopping at the patch you want to edit:

```sh
python3 comfy-tools/patches.py setup \
  --through 0006-updating-to-use-250k-content-rules-instead-of-150k.patch
# Edit source here. Later patches are not applied in this prefix session.
./apply_patches.sh \
  --refresh 0006-updating-to-use-250k-content-rules-instead-of-150k.patch
```

Refresh keeps the patch's position, author/message headers, and historical
workflow/documentation hunks. It validates all later patches before saving.
If a dependency conflicts, it stops with your edits and old patch intact.
Narrow or adjust the edit before retrying. It will not fold later patches into an
earlier patch. To build/test the complete refreshed stack, run setup again without
`--through`. No second checkout is involved.

The equivalent explicit commands are `python3 comfy-tools/patches.py finish`
(or `create`) and `python3 comfy-tools/patches.py refresh PATCH_FILENAME`.

### Verify and export

```sh
python3 comfy-tools/patches.py verify
# Historical references, if present in your clone:
python3 comfy-tools/patches.py verify --against comfy-build
python3 comfy-tools/patches.py verify --against backup/comfy-safari
python3 comfy-tools/patches.py export ../ComfyWebKit-patch-export
python3 comfy-tools/test_workflow.py
```

Verification uses an isolated Git index without another source checkout.
`--against` compares every source path, excluding explicitly permitted workflow
metadata. Export copies the patch files, `base`, and `series`; it refuses to
overwrite differing files. Integration tests use tiny disposable repositories.

`comfy-patches/series` defines the order. `comfy-patches/base` pins the original
patch baseline, `b809551f8a0a4ac2e2a82d1fb1d1edb0201448a5`. Use a full clone so this
commit is available. The original 11 patch files remain unchanged. Their old
README/ignore-rule hunks are validated as part of the series, but setup applies
only source hunks to your checkout, retaining your current publishing metadata.

### Safety and recovery

Setup creates a uniquely named branch at the current publishing commit. Existing
branches, including `comfy-build` and all backups, are never reset, deleted, or
rewritten. Local development branches retain their automatic source baseline commit.
Setup creates it from the known patched tree, excluding your dirty/staged work;
it appends history and never resets a branch. It may upgrade an existing session
in place: rerun setup to clear the staged patch noise while preserving your edits. Setup can also start from a publishing feature branch whose source
matches the pinned baseline; finish returns to that branch. The push hook permits
only main-to-main pushes.

Git hooks block manual commits during development sessions, block upstream source
commits on publishing branches, and block pushes of
development branches, backups, tags, detached refs, or history containing source
changes after the pinned baseline. Only patches, workflow files, README, ignore
rules, and the root launcher may be committed. Hooks are local safeguards and can
be bypassed; every clone must run setup. Existing hook configurations are preserved
by refusing to replace them. No command fetches, pushes, or alters GitHub settings.

Session state, saved source tree objects, a staged diff, and a finish recovery
record live under `.git/comfy-inplace.json`. Completed recovery records are retained
in `.git/comfy-session-history/` when starting the next session. A file lock prevents overlapping
workflow commands. Finish saves and validates the patch before restoring only the
source files belonging to the session; unrelated files and workflow staging stay
in place. If setup is interrupted, rerun setup. If finish is interrupted, rerun
`./apply_patches.sh`; its saved transaction can resume even between patch and
series writes. If additional edits, moved branch tips, or changed patches make
recovery ambiguous, it stops with the saved record intact. Never delete that
record, run `git reset --hard`, or run `git clean` to recover; inspect the state
and saved tree first. Do not run branch-changing commands during a session.

This adopts [Helium's ordered patch/edit/refresh model](https://github.com/imputnet/helium/blob/main/CONTRIBUTING.md#working-with-patches).
[Helium uses quilt](https://github.com/imputnet/helium-macos/blob/main/docs/building.md#development-build-and-environment)
for stack navigation and file tracking. Git already provides the index and binary
patch support needed here. Quilt would add a dependency and require migrating the
existing format-patch series, so this workflow uses Git and Python 3.9+ only.

## Building on macOS

Install Xcode, then install its command line tools and Metal toolchain:

```sh
xcode-select --install
xcodebuild -downloadComponent MetalToolchain
```

Run `python3 comfy-tools/patches.py setup` first, then build here using the existing
`WebKitBuild/` directory. Build a debug version:

```sh
Tools/Scripts/build-webkit --debug
```

For a release build:

```sh
Tools/Scripts/build-webkit --release
```

To include debug symbols in a release build:

```sh
Tools/Scripts/build-webkit --release DEBUG_INFORMATION_FORMAT=dwarf-with-dsym
```

You can also open `WebKit.xcworkspace` in Xcode and select the **Everything up to WebKit + Tools** scheme. If you use Xcode’s default build location, set the workspace’s advanced build location to **Custom → Relative to Workspace**, with `WebKitBuild` for both Products and Intermediates.

## Running your app with the local build

Use WebKit’s launcher to run a macOS application with the locally built frameworks:

```sh
Tools/Scripts/run-webkit-app --debug /path/to/YourApp.app
```

Use `--release` if you built the release configuration. When compiling your application, use the headers and framework from the same ComfyWebKit build so the added declarations are available.

## Upstream and licensing

ComfyWebKit is maintained separately from upstream [WebKit](https://github.com/WebKit/WebKit). Report issues with this fork’s API changes in the [ComfyWebKit issue tracker](https://github.com/AryanRogye/ComfyWebKit/issues).

The original WebKit copyright notices and licenses remain applicable. See the license files and source file notices throughout the repository.
