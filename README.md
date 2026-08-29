# vget

网上的视频下载插件大多要付费，磁力链接下载又经常很慢。为了把“复制链接，直接下载”
这件事做简单，索性写了 `vget`：它能解析网页中的 MP4/HLS 视频，并通过并发下载尽量
跑满可用带宽。

## 支持网站

- [Jable](https://jable.tv/)
- [MissAV](https://missav.ai/)
- [SupJav](https://supjav.com/)

### 暂不支持

| 网站 | 状态 |
| --- | --- |
| [YouTube](https://www.youtube.com/) | ❌ 暂不支持 |
| [哔哩哔哩](https://www.bilibili.com/) | ❌ 暂不支持 |
| [优酷](https://www.youku.com/) | ❌ 暂不支持 |
| [爱奇艺](https://www.iqiyi.com/) | ❌ 暂不支持 |
| [腾讯视频](https://v.qq.com/) | ❌ 暂不支持 |
| [Vimeo](https://vimeo.com/) | ❌ 暂不支持 |

上述暂不支持的平台通常通过 JavaScript、接口签名或 DRM 动态生成播放地址，普通网页解析器无法直接取得媒体 URL。
网站结构和风控策略可能变化，上述结果不代表目标站点始终可访问。

## 核心用法

```bash
vget "URL"
```

例如：

```bash
vget "https://example.com/video-page"
```

默认下载最佳画质，并保存到 `downloads` 目录。下载中断后，重新运行同一条命令即可续传。

> [!IMPORTANT]
> 仅下载你拥有或获准保存的内容，并遵守网站条款和当地法律。`vget` 不绕过 DRM、
> SAMPLE-AES、验证码、付费墙或账号权限。

## 安装

需要 Python 3.11 或更高版本。

### Windows

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

安装后，在项目根目录运行：

```bash
# Git Bash
./vget "URL"
```

```powershell
# PowerShell / CMD
.\vget.cmd "URL"
```

如果希望直接使用 `vget URL`，先激活虚拟环境：

```bash
# Git Bash
source .venv/Scripts/activate
```

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 常用用法

```bash
# 指定最高画质和保存目录
vget -q 1080p -o ./videos "URL"

# 只解析视频信息，不下载
vget --info "URL"

# 直接下载 MP4 或 M3U8
vget "https://cdn.example/video.mp4"
vget "https://cdn.example/master.m3u8"

# 批量下载，每行一个 URL
vget --input-file urls.txt
```

完整参数以 `vget --help` 为准。

## 配置

复制 `.env.example` 为 `.env`，可设置默认代理、画质、输出目录、并发数和重试次数：

```dotenv
VGET_PROXY=socks5h://127.0.0.1:10808
VGET_QUALITY=best
VGET_OUTPUT_DIR=downloads
VGET_WORKERS=8
VGET_RETRIES=4
```

配置优先级：

```text
内置默认值 < .env < 系统环境变量 < 命令行参数
```

临时使用代理或已有登录 Cookie：

```bash
vget --proxy "socks5h://127.0.0.1:10808" "URL"
vget --cookies cookies.txt "URL"
```

Cookie 文件可能包含账号凭据，不应提交到 Git。代理也不能代替登录授权或绕过验证码。

## 常用参数

| 参数 | 作用 |
| --- | --- |
| `-o, --output DIR` | 保存目录，默认为 `downloads` |
| `-q, --quality VALUE` | `best`、`1080p`、`720p`、`480p`、`360p` 或 `lowest` |
| `-w, --workers N` | 并发数，范围 1–16 |
| `--proxy URL` | 临时指定 HTTP、HTTPS 或 SOCKS 代理 |
| `--cookies FILE` | 使用 Netscape 格式 Cookie 文件 |
| `--thumbnail` | 同时保存封面 |
| `--overwrite` | 覆盖同名文件 |
| `--keep-parts` | 成功后保留下载分片 |
| `--info` | 只解析，不下载 |
| `--verbose` | 显示详细诊断信息 |

## 说明

- 支持 HLS 分片和 MP4 Range 并发下载、断点续传、AES-128 与 BYTERANGE。
- 使用 FFmpeg 流复制封装，不重新编码。
- 画面中已有的硬字幕会保留，暂不下载独立字幕轨道。
- 遇到 403、429 或 Cloudflare 时，可尝试更换网络、设置代理或使用自己的登录 Cookie。
- 网站能播放但无法解析时，运行 `vget --verbose --info URL` 获取诊断信息。

## 开发

代码结构、修改约束和验证命令见[开发代理说明](AGENT.md)。
