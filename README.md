# downVideo

基于 **yt-dlp** + **ffmpeg** 开发的跨平台视频下载工具，提供**图形界面（GUI）**与**命令行（CLI）**两种用法，支持 YouTube、X(Twitter)、Pornhub、B 站、TikTok、Vimeo、Facebook 等 yt-dlp 支持的上千个站点。

> 国内访问 YouTube / X / Pornhub 需要代理或 VPN，工具内置「本地代理」设置，下载与检测分辨率都会走该代理。

## 功能特性

- **图形界面**：粘贴链接即可下载
  - 分辨率检测：自动拉取视频真实可选清晰度，精确挑选
  - **下载列表**：每个链接独立一行，显示状态图标 / 标题 / 进度条 / 百分比·速度·ETA·大小
  - **自动关机**：勾选「全部下载完成后自动关机」，可设延迟分钟，到点执行（窗口关闭前可取消）
  - 本地代理、Cookie（浏览器或文件）、记住输出目录
- **命令行**：批量下载、画质预设、格式列表、信息预览、多线程
- **自带 ffmpeg**，无需另行安装
- 可一键打包为**自包含便携 exe**，拷贝到任意 Windows 直接双击使用

## 支持的网站

YouTube、X/Twitter、Pornhub（prohub）、Bilibili、TikTok、Vimeo、Facebook、Instagram 等——只要 yt-dlp 支持的站点都可用。

## 方式一：便携版（推荐，零安装）

到 [Releases](https://github.com/GWWWi/downVideo/releases) 下载 `VideoDownloader-portable-win64.zip`，解压后双击 `VideoDownloader.exe` 即可使用，无需安装 Python / ffmpeg。

> 仅支持 64 位 Windows。

## 方式二：源码运行

```bat
pip install -r requirements.txt
python gui_downloader.py                                  :: 打开图形界面
python video_downloader.py "URL" -q 1080p -o ./downloads  :: 命令行下载
```

> 注意：本机若开了 HTTPS MITM 类代理会破坏 pip / yt-dlp 的 TLS，安装依赖时用
> `env -u HTTP_PROXY -u HTTPS_PROXY pip install -r requirements.txt`。

## 图形界面操作

1. 在「链接」框粘贴视频地址（支持多行批量）
2. 选「输出目录」（点「浏览…」选择，会自动记住）
3. 选「分辨率」——可先点「检测分辨率」拉取该视频真实清晰度再挑选
4. 需要登录态的站点（X / Pornhub / 年龄限制 / 会员）填「Cookie 浏览器」或「Cookie 文件」
5. 国内访问在「本地代理」填代理地址，如 `http://127.0.0.1:7890`（Clash / V2Ray 的 HTTP 代理）
6. 点「开始下载」，下方「下载列表」会为每个链接显示独立进度（图标 / 标题 / 进度条 / 百分比·速度·ETA·大小）
7. 如需下载完自动关机：勾选「完成动作」里的「全部下载完成后自动关机」，并设置「关机延迟(分钟)」（0 = 立即）；关机计划在执行前可点「取消关机」中止

## 命令行示例

```bat
:: 下载单个（1080p）
python video_downloader.py "URL" -q 1080p -o ./downloads

:: 批量（urls.txt 每行一个链接，# 开头为注释）
python video_downloader.py -a urls.txt -q best -o ./downloads

:: 仅查看视频信息 / 列出可用格式
python video_downloader.py --print-info "URL"
python video_downloader.py --list-formats "URL"

:: 走本地代理 + Cookie 文件
python video_downloader.py "URL" --proxy http://127.0.0.1:7890 --cookie-file cookies.txt -o ./downloads
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `-q/--quality` | `best` `2160p` `1440p` `1080p` `720p` `480p` `360p` `audio` |
| `-a FILE` | 从文件批量读取链接 |
| `--proxy URL` | 本地代理，如下载与检测分辨率都走它 |
| `--cookies-from-browser` | `chrome` `firefox` `edge` `brave` `opera` `safari` `chromium` |
| `--cookie-file FILE` | Netscape 格式 Cookie 文件 |
| `--threads N` | 多线程批量下载 |
| `--no-playlist` | 播放列表只下载单个 |

## Cookie 说明（重要）

- 普通公开视频**不需要** Cookie。
- X / Pornhub / 年龄限制视频建议用 **Cookie 文件**（浏览器插件如 *Cookie-Editor* / *Get cookies.txt LOCALLY* 导出 Netscape 格式 `cookies.txt`），比「从浏览器读取」更稳定。
- 若选「Cookie 浏览器 = Chrome」报 `Could not copy Chrome cookie database`：请完全退出 Chrome（含后台进程）再试，或改用 Cookie 文件方式。

## 一键打包便携 exe

```bat
build.bat
```

产物在 `dist\VideoDownloader\`，整文件夹拷贝到别的电脑双击即用。

## 常见问题

- **双击打不开 / 报 `Failed to load Python DLL`**：请运行 `dist\VideoDownloader\VideoDownloader.exe`，不要运行 `build\` 目录下那个 PyInstaller 中间产物。
- **YouTube 无响应**：确认「本地代理」已填且代理可用；yt-dlp 会自动读取该代理。
- **pip 装不上**：用 `env -u HTTP_PROXY -u HTTPS_PROXY pip install -r requirements.txt` 绕开本机 MITM 代理。

## 合规声明

请仅下载你有权下载的内容，遵守各站点服务条款与当地法律法规。本工具仅用于合法的个人下载与学习用途。
