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

## Getting the source

```sh
git clone https://github.com/AryanRogye/ComfyWebKit.git
cd ComfyWebKit
```

## Building on macOS

Install Xcode, then install its command line tools and Metal toolchain:

```sh
xcode-select --install
xcodebuild -downloadComponent MetalToolchain
```

From the repository root, build a debug version:

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
