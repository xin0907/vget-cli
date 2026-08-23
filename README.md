# vget

`vget` 是一个专注于 MP4/HLS 的纯命令行视频下载器，使用独立站点解析器和自研下载
内核，不依赖 `yt-dlp`。

> [!IMPORTANT]
> 仅下载你拥有或获准保存的内容，并遵守网站条款和当地法律。`vget` 不绕过 DRM、
> SAMPLE-AES、验证码、付费墙或账号权限。

## 功能

- HLS 画质选择、并发分片、AES-128、BYTERANGE 和断点续传
- 直接 MP4 的 HTTP Range 并发、断点续传与单连接回退
- 总进度、实时速度和预计剩余时间
- FFmpeg 流复制封装，不重新编码
- HTTP/HTTPS/SOCKS 代理、Netscape Cookie 和自定义 Referer
- 批量 URL、标准输入、封面、安全文件名和聊天链接还原

## 支持来源

| 来源 | 媒体类型 | 说明 |
| --- | --- | --- |
| JableTV / `fs1.app` | HLS | 专用页面解析器 |
| MissAV 常用域名 | HLS | 专用页面解析器 |
| SupJav | HLS / MP4 | FST、Streamtape 和 TV 备用来源 |
| Hanime1 | MP4 | 签名直链与画质选择 |
| 直接链接 | MP4 / M3U8 | 直接输入媒体 URL |
| 普通网页 | MP4 / M3U8 | 仅限 HTML 中直接暴露的地址 |

网站结构和风控策略会变化，支持列表不代表目标站点始终可访问。

## 安装

需要 Python 3.11 或更高版本。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\vget.exe --version
```

激活环境后可以直接运行 `vget`：

```powershell
.\.venv\Scripts\Activate.ps1
vget --help
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
vget --version
```

Windows Git Bash 将激活命令改为 `source .venv/Scripts/activate`。

## 快速开始

下载一个页面并限制最高 1080p：

```bash
vget -q 1080p -o "./videos" "https://example.com/video-page"
```

仅解析媒体信息：

```bash
vget --info "https://example.com/video-page"
```

下载直接媒体地址：

```bash
vget "https://cdn.example/video.mp4"
vget "https://cdn.example/master.m3u8"
```

批量下载，地址文件每行一个 URL：

```bash
vget --input-file urls.txt
```

### 代理和 Cookie

代理地址应使用本地代理软件提供的 HTTP、HTTPS 或 SOCKS 端口：

```bash
vget --proxy "http://127.0.0.1:10808" "https://example.com/video-page"
```

代理只能切换网络线路，不能代替登录授权或保证通过 Cloudflare。需要已有登录状态时，可
导出 Netscape 格式 Cookie 文件：

```bash
vget --cookies "cookies.txt" "https://example.com/video-page"
```

Cookie 文件可能包含账号凭据，已被默认忽略，不应提交到 Git。

## 断点续传

未完成状态保存在输出目录的 `.vget-parts`。使用相同 URL、输出目录和文件名重新运行命令，
程序会跳过已完成分片。成功生成 MP4 后默认清理临时数据；使用 `--keep-parts` 可保留。

如果 HLS 播放清单发生变化，计划指纹会随之改变，旧分片不会与新媒体混用。

## 常用参数

| 参数 | 作用 |
| --- | --- |
| `-o, --output DIR` | 保存目录，默认 `downloads` |
| `-q, --quality VALUE` | `best`、`1080p`、`720p`、`480p`、`360p`、`lowest` |
| `-w, --workers N` | 每个视频的并发数，范围 1–16 |
| `--retries N` | 单个资源的重试次数 |
| `--proxy URL` | HTTP、HTTPS 或 SOCKS 代理 |
| `--cookies FILE` | Netscape 格式 Cookie 文件 |
| `--referer URL` | 覆盖媒体请求 Referer |
| `--thumbnail` | 同时保存封面 |
| `--overwrite` | 覆盖同名成品 |
| `--keep-parts` | 成功后保留分片 |
| `--info` | 只解析，不下载 |
| `--verbose` | 显示详细诊断 |

完整参数以 `vget --help` 为准。

## 字幕

画面内已经烧录的硬字幕会自然保留。当前版本尚未下载独立 WebVTT/SRT/TTML 或 HLS
字幕轨道。

## 故障排查

- **403、429 或 Cloudflare**：尝试合适网络或 `--proxy`；需要登录权限时使用自己的
  Cookie。程序不处理验证码绕过。
- **网站能播放但无法解析**：运行 `vget --verbose --info URL`，目标网站可能已经改版。
- **HLS 封装失败**：确认磁盘空间充足，并使用 `--verbose` 查看 FFmpeg 错误。
- **下载中断**：重新运行相同命令，不要删除输出目录中的 `.vget-parts`。

## 开发

代码结构、修改约束和验证命令见[开发代理说明](AGENT.md)。
