import AppKit
import WebKit
import UniformTypeIdentifiers

final class VideoWebView: WKWebView {
    var onFiles: (([String]) -> Void)?
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        sender.draggingPasteboard.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) ? .copy : []
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL], !urls.isEmpty else { return false }
        onFiles?(urls.map(\.path)); return true
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: VideoWebView!
    private var backend: Process?
    private var backendOutput = Data()
    private var stderrTail = Data()
    private var backendURL: URL?
    private var quitting = false
    private var started = false
    private var pendingPaths: [String] = []
    private var dataDirectory: URL!
    private let launchToken = UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        createMenu()
        createWindow()
        startBackend()
    }

    private func createMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "关于 Freddie Lingua", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "设置…", action: #selector(openSettings), keyEquivalent: ",")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "隐藏 Freddie Lingua", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "退出 Freddie Lingua", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let fileItem = NSMenuItem(); menu.addItem(fileItem)
        let file = NSMenu(title: "文件"); fileItem.submenu = file
        file.addItem(withTitle: "导入视频…", action: #selector(chooseVideo), keyEquivalent: "o")
        file.addItem(withTitle: "打开本地数据文件夹", action: #selector(openDataFolder), keyEquivalent: "")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(NSMenuItem.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let windowItem = NSMenuItem(); menu.addItem(windowItem)
        let windows = NSMenu(title: "窗口"); windowItem.submenu = windows
        windows.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windows.addItem(withTitle: "缩放", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        NSApp.windowsMenu = windows
        NSApp.mainMenu = menu
    }

    private func createWindow() {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 1000)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: min(1440, screen.width - 60), height: min(980, screen.height - 60)), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Freddie Lingua"
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(srgbRed: 0.043, green: 0.055, blue: 0.075, alpha: 1)
        window.minSize = NSSize(width: 920, height: 650)
        window.center(); window.delegate = self
        window.isReleasedWhenClosed = false
        let controller = WKUserContentController()
        controller.add(self, name: "freddie")
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = VideoWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.registerForDraggedTypes([.fileURL])
        webView.onFiles = { [weak self] paths in self?.sendPaths(paths) }
        window.contentView = webView
        webView.loadHTMLString("<html><meta charset='utf-8'><body style='margin:0;background:#0b0e13;color:#91ead8;font:16px -apple-system;display:grid;place-items:center;height:100vh'><div>Freddie Lingua<span style='display:block;color:#8291a1;font-size:12px;margin-top:12px'>正在启动本地工作台…</span></div></body></html>", baseURL: nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func startBackend() {
        guard let resources = Bundle.main.resourceURL else { return showError("找不到应用资源，请重新构建应用。") }
        let python = resources.appendingPathComponent("runtime/bin/python3.12")
        let app = resources.appendingPathComponent("app")
        if let override = ProcessInfo.processInfo.environment["FREDDIE_DATA_DIR"], !override.isEmpty {
            dataDirectory = URL(fileURLWithPath: override, isDirectory: true)
        } else {
            dataDirectory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Freddie Lingua", isDirectory: true)
        }
        do { try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true) }
        catch { return showError("无法创建本地数据文件夹：\(error.localizedDescription)") }
        let process = Process()
        process.executableURL = python
        process.currentDirectoryURL = app
        process.arguments = ["-m", "backend.server", "--port", "0", "--data-dir", dataDirectory.path, "--frontend-dir", app.appendingPathComponent("frontend").path, "--token", launchToken]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = resources.appendingPathComponent("bin").path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["HF_HOME"] = dataDirectory.appendingPathComponent("cache/huggingface").path
        environment["MPLCONFIGDIR"] = dataDirectory.appendingPathComponent("cache/matplotlib").path
        environment["NUMBA_CACHE_DIR"] = dataDirectory.appendingPathComponent("cache/numba").path
        environment["TORCH_HOME"] = dataDirectory.appendingPathComponent("cache/torch").path
        environment["XDG_CACHE_HOME"] = dataDirectory.appendingPathComponent("cache").path
        process.environment = environment
        let output = Pipe(), errors = Pipe()
        process.standardOutput = output; process.standardError = errors
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            guard !bytes.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.handleOutput(bytes) }
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            guard !bytes.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                self?.stderrTail.append(bytes)
                if let count = self?.stderrTail.count, count > 12000 { self?.stderrTail.removeFirst(count - 12000) }
            }
        }
        process.terminationHandler = { [weak self] task in
            DispatchQueue.main.async {
                guard let self, !self.quitting else { return }
                self.showError("本地处理服务已停止（\(task.terminationStatus)）。请重新打开 Freddie Lingua。\n" + (self.started ? "" : String(data: self.stderrTail, encoding: .utf8) ?? ""))
            }
        }
        backend = process
        do { try process.run() }
        catch { showError("无法启动本地运行时：\(error.localizedDescription)") }
    }

    private func handleOutput(_ bytes: Data) {
        guard !started else { return }
        backendOutput.append(bytes)
        while let newline = backendOutput.firstIndex(of: 10) {
            let line = backendOutput.prefix(upTo: newline)
            backendOutput.removeSubrange(...newline)
            if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let port = obj["port"] as? Int {
                guard (1...65535).contains(port), let url = URL(string: "http://127.0.0.1:\(port)") else { continue }
                started = true; backendURL = url
                var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
                components.path = "/"; components.queryItems = [URLQueryItem(name: "token", value: launchToken)]
                webView.load(URLRequest(url: components.url!)); return
            }
        }
        if backendOutput.count > 65536 { backendOutput.removeAll() }
    }

    @objc private func chooseVideo() {
        let panel = NSOpenPanel()
        panel.title = "选择本地视频"; panel.prompt = "导入"
        panel.allowedContentTypes = [.movie, .audio, UTType(filenameExtension: "mkv") ?? .data]
        panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { [weak self] response in
            if response == .OK { self?.sendPaths(panel.urls.map(\.path)) }
        }
    }

    private func sendPaths(_ paths: [String]) {
        if !started || webView.isLoading { pendingPaths = paths; return }
        dispatch("freddie:import", detail: ["paths": paths])
    }

    private func dispatch(_ name: String, detail: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: detail), let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('\(name)',{detail:\(json)}))", completionHandler: nil)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              let origin = backendURL, message.frameInfo.securityOrigin.host == origin.host,
              message.frameInfo.securityOrigin.port == origin.port,
              let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        switch action {
        case "chooseVideo": chooseVideo()
        case "openDataFolder": openDataFolder()
        case "export": if let path = body["url"] as? String { saveExport(path) }
        case "copy": if let text = body["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
        case "openExternal":
            if let raw = body["url"] as? String, let url = URL(string: raw), url.scheme == "https" { NSWorkspace.shared.open(url) }
        default: break
        }
    }

    private func saveExport(_ path: String) {
        guard let base = backendURL, let url = URL(string: path, relativeTo: base)?.absoluteURL,
              url.host == base.host, url.port == base.port, url.scheme == "http",
              url.path.hasPrefix("/api/projects/"), url.path.hasSuffix("/export") else { return }
        webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self] cookies in
            var request = URLRequest(url: url)
            request.allHTTPHeaderFields = HTTPCookie.requestHeaderFields(with: cookies.filter { $0.domain == "127.0.0.1" })
            URLSession.shared.dataTask(with: request) { data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    guard error == nil, let response = response as? HTTPURLResponse, response.statusCode == 200, let data else {
                        self.dispatch("freddie:error", detail: ["message": "导出失败，请确认内容已生成后重试。"]); return
                    }
                    let ext = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "format" })?.value ?? "md"
                    let panel = NSSavePanel(); panel.title = "保存导出内容"
                    panel.nameFieldStringValue = "Freddie Lingua.\(ext)"
                    panel.allowedContentTypes = [UTType(filenameExtension: ext) ?? .plainText]
                    panel.canCreateDirectories = true
                    panel.beginSheetModal(for: self.window) { result in
                        guard result == .OK, let destination = panel.url else { return }
                        do { try data.write(to: destination, options: .atomic); self.dispatch("freddie:exported", detail: ["path": destination.path]) }
                        catch { self.dispatch("freddie:error", detail: ["message": "文件保存失败：\(error.localizedDescription)"]) }
                    }
                }
            }.resume()
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard started else { return }
        if !pendingPaths.isEmpty { let paths = pendingPaths; pendingPaths = []; sendPaths(paths) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.scheme == "http" && url.host == "127.0.0.1" && url.port == backendURL?.port) { decisionHandler(.allow) }
        else { decisionHandler(.cancel) }
    }

    @objc private func openDataFolder() { if let dataDirectory { NSWorkspace.shared.open(dataDirectory) } }
    @objc private func openSettings() { webView.evaluateJavaScript("document.getElementById('settings-button')?.click()", completionHandler: nil) }
    @objc private func showAbout() {
        let alert = NSAlert(); alert.messageText = "Freddie Lingua"
        alert.informativeText = "听懂世界，留住重点。\n版本 1.0 · Apple Silicon\n本地语音识别 · 云端增强 · 离线保底"
        alert.beginSheetModal(for: window)
    }
    private func showError(_ text: String) {
        let alert = NSAlert(); alert.alertStyle = .warning
        alert.messageText = "Freddie Lingua 暂时无法继续"; alert.informativeText = text
        alert.addButton(withTitle: "知道了"); alert.beginSheetModal(for: window)
    }
    func application(_ sender: NSApplication, openFiles filenames: [String]) { sendPaths(filenames); sender.reply(toOpenOrPrint: .success) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { quitting = true; if backend?.isRunning == true { backend?.terminate() } }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
