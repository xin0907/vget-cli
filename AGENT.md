# vget 开发代理说明

本文件供后续维护本仓库的 AI Agent 和开发者阅读。开始修改前，请先阅读
`README.md`；如果本地存在 `docs/technical-design.md`，再阅读该技术方案。

## 项目目标

`vget` 是一个不依赖 `yt-dlp` 的纯 CLI 视频下载器。它通过专用站点解析器取得
MP4/HLS 媒体源，再由本项目的下载内核执行并发下载、续传、解密和封装。

项目只处理用户有权保存的公开或已授权内容。不要实现 DRM、SAMPLE-AES、付费墙、
账号权限或其他访问控制的绕过逻辑。

## 代码地图

- `src/vget/arguments.py`：命令行参数、URL 清理和输入验证。
- `src/vget/cli.py`：任务调度、退出码和用户可见错误。
- `src/vget/constants.py`：跨模块共享的协议值、默认限制、超时和文件后缀。
- `src/vget/http.py`：HTTP 会话、浏览器特征、代理、Cookie 和重试。
- `src/vget/extraction/`：通用解析基础、站点解析器和注册表。
- `src/vget/download/`：共用工具、MP4 Range、HLS 和下载服务编排。
- `src/vget/models.py`：跨模块数据模型。
- `src/vget/errors.py`：面向 CLI 的错误类型。
- `tests/`：离线单元测试；测试不得依赖真实成人站点或不稳定公网资源。

## 修改约束

1. 保持 Python 3.11+ 兼容，尽量使用标准库和现有依赖。
2. 不要静默吞掉错误。可预期故障应转换成 `VgetError` 子类并给出中文可操作提示。
3. 下载成品必须先写临时文件，完整成功后再原子发布，避免留下伪装成成品的残缺 MP4。
4. 保持断点续传兼容；不要随意更改 `.vget-parts` 的定位和指纹算法。
5. 并发共享状态必须加锁；禁止多个线程同时写同一分片文件。
6. 站点变化应优先局部修改对应解析器，不要把站点规则泄漏到通用下载内核。
7. 保留 `LICENSE` 和 `NOTICE` 中的 Apache-2.0 许可与上游归属说明。
8. 用户可能从聊天界面复制 `[文字](URL)`；URL 和代理入口应继续兼容这种格式。
9. Windows 是主要运行环境，同时避免破坏其他平台的 `pathlib` 和 FFmpeg 行为。

## 验证要求

完成代码修改后至少运行：

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

涉及下载内核时，应补充本地 HTTP fixture 测试，覆盖中断恢复、Range、HLS 分片、
AES-128 或 BYTERANGE 中相关路径。涉及真实站点的验证默认只做 `--info`，不要在测试中
下载实际内容。

## 文档同步

参数、支持站点、目录格式、续传语义、依赖或限制发生变化时，同步更新公开的
`README.md`。本地存在 `docs/technical-design.md` 时，也应同步其中的设计说明；`docs/`
属于本地维护笔记，不提交到 Git。
