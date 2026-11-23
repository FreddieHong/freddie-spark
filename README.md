# Freddie Spark 1.1

一个给中文使用者的 Mac 外语视频理解工作台。采用已确认的「沉浸式工作台」设计：左侧视频与智能总结，右侧原文阅读。左右两栏独立滚动，阅读时不打断视频播放。

## 打开软件

构建后的应用位于 `dist/Freddie Spark.app`，双击打开。当前版本面向 **Apple Silicon Mac，macOS 14 或更新版本**。

1. 在「设置 → 离线模型」下载约 150 MB 的多语言识别包。
2. 若使用云端，在设置中填写 OpenAI 兼容的服务地址、模型名称和 API Key。地址通常以 `/v1` 结尾，具体以服务商文档为准。
3. 建议同时下载约 1 GB 的离线翻译与总结包，作为断网保底。
4. 将本地视频拖入窗口，或使用「导入视频」/ `⌘O`。未满足处理条件时，界面会引导准备模型或云端设置。
5. 处理后切换原文、双语、中文；点击字幕时间或总结章节定位视频。原文阅读右上角的复制按钮提供 SRT（带毫秒时间戳）和 TXT（纯文本），按当前选项卡复制到系统剪贴板。也可导出 Markdown、TXT 和 SRT 文件。

### 三种处理模式

- **自动**：配置了云端则优先云端；云端失败时使用已安装的离线模型。没有云端配置时直接使用本地模型。
- **优先云端**：按用户明确选择使用云端；出错会提示重试或切换自动/本地。
- **仅本地**：语音识别、翻译和总结都在本机完成，不发送内容到模型服务。

语音识别始终在本机进行。云端模式仅发送转写文字，不上传原视频或音频；模型服务商仍会按其政策处理收到的文字。API Key 优先存入 macOS 钥匙串；如果钥匙串不可用，只在本次运行内保存，并在设置中说明。视频路径、原文、中文与总结保存在 `~/Library/Application Support/Freddie Lingua/`。原视频不被删除或改写。

离线包需提前下载。离线翻译和总结的准确性会受本地模型能力、视频语种及专业术语影响；可用时间出处核对原文。当前识别的是语音，不读取视频画面中的幻灯片文字。MKV 等 WebKit 不支持的编码仍可识别音频，但播放器会提示无法预览；使用 H.264/AAC 的 MP4 通常兼容最好。

## 版本记录

- `v1.0`：保留最初的 Freddie Lingua 沉浸式工作台，源码已打版本标签，本机应用保存在 `dist/versions/1.0/Freddie Lingua.app`。
- `v1.1`：更名 Freddie Spark；字幕按当前阅读模式复制 SRT / TXT；视频与总结在左，原文在右，左右独立滚动。

为保留原有项目、离线模型与密钥，1.1 沿用 `com.freddie.lingua` 应用标识和原本的 `Freddie Lingua` 数据目录，无需重新下载模型。

## 项目结构

- `frontend/`：HTML/CSS/JavaScript 界面，无 Node 构建依赖。
- `backend/`：Python 本机服务、SQLite 项目保存、模型管理与 AI 引擎。
- `native/`：AppKit、WKWebView 窗口，原生导入、拖放及保存对话框。
- `scripts/`：开发启动、Mac 应用构建与实际流程验证。
- `tests/`：标准库 unittest 测试。

## 开发与构建

需要 Swift Command Line Tools、FFmpeg/FFprobe 和 Python 3.12。项目使用独立的 python-build-standalone 运行时，构建时随应用打包；不会要求最终用户安装 Python、Node 或 Homebrew。

首次准备运行时（示例使用 uv）：

```sh
uv python install 3.12 --install-dir .runtime --no-bin
uv pip install --python .runtime/cpython-3.12.16-macos-aarch64-none/bin/python3.12 \
  --target .runtime/cpython-3.12.16-macos-aarch64-none/lib/python3.12/site-packages \
  -r requirements.txt
```

目录中的具体 Python 补丁版本以 `uv python install` 输出为准，调整命令中的版本。仓库不含运行时、模型或凭据。

```sh
# 启动本地开发界面（终端打印的 token 用于首次打开页面）
.runtime/cpython-3.12.16-macos-aarch64-none/bin/python3.12 scripts/run_dev.py

# 单元与本机 HTTP 集成测试；需要允许绑定 loopback 端口
python3 -m unittest discover -s tests -v

# 六种复制模式的格式校验（Node.js 18+，无需额外依赖）
node --test tests/test_transcript_copy.js

# 浏览器剪贴板、滚轮隔离、持续播放与窄窗口检查（需要 Playwright 和 Chrome）
node tests/test_workbench_ui.cjs

# 构建并验证 .app；自动打包运行时及 FFmpeg 的 Homebrew 动态库
python3 scripts/build_app.py

# 修改界面/后端后可复用已有运行时，缩短构建时间
python3 scripts/build_app.py --reuse-runtime
```

构建产物采用本机 ad-hoc 签名，尚未使用 Apple Developer 证书签名或公证。当前适合在这台 Mac 上直接使用；对外分发前应完成开发者签名、公证和第三方许可核查。

本机服务只监听 `127.0.0.1` 的随机端口。访问项目需要启动时的会话 Cookie，写请求检查来源；媒体支持 Range，长视频无需整段加载到内存。重启后会保留已完成内容，未完成任务可重新处理。模型只在用户点击下载时获取，推理使用本地模型路径。
