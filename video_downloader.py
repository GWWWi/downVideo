#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用视频下载器 (Universal Video Downloader)
============================================
基于 yt-dlp 的跨平台视频下载工具，支持 YouTube、X(Twitter)、Pornhub
以及 yt-dlp 支持的上千个站点（Bilibili、TikTok、Vimeo、Facebook…）。

特性:
  - 单个 / 批量下载（文件 -a 或管道）
  - 画质预设 (best / 2160p / 1440p / 1080p / 720p / 480p / 360p / audio)
  - 自定义 yt-dlp 格式串 (--format)
  - 从浏览器直接读取 Cookie（用于 X、Pornhub 等需登录/年龄验证的站点）
  - 自定义 Netscape Cookie 文件 (--cookie-file)
  - 仅打印信息不下载 (--print-info)
  - 列出可用格式 (--list-formats)
  - 多线程批量下载 (--threads)
  - 自动定位 ffmpeg（通过 imageio-ffmpeg 内置二进制）

用法示例:
  python video_downloader.py "https://www.youtube.com/watch?v=xxxx"
  python video_downloader.py "URL" -q 720p -o ./downloads
  python video_downloader.py -a urls.txt -q best --threads 4
  python video_downloader.py "URL" --cookies-from-browser chrome
  python video_downloader.py "URL" --print-info
  python video_downloader.py "URL" --list-formats
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import imageio_ffmpeg  # 可选依赖：自带 ffmpeg 二进制
except Exception:  # pragma: no cover
    imageio_ffmpeg = None

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError


# ---------------------------------------------------------------------------
# 画质预设：映射为 yt-dlp 的 format 选择串
# ---------------------------------------------------------------------------
QUALITY_PRESETS = {
    "best": "bv*+ba/best",
    "2160p": "bv[height<=2160]+ba/best[height<=2160]",
    "1440p": "bv[height<=1440]+ba/best[height<=1440]",
    "1080p": "bv[height<=1080]+ba/best[height<=1080]",
    "720p": "bv[height<=720]+ba/best[height<=720]",
    "480p": "bv[height<=480]+ba/best[height<=480]",
    "360p": "bv[height<=360]+ba/best[height<=360]",
    "audio": "ba/bestaudio",
}

PLATFORM_ICON = {
    "youtube": "▶ YouTube",
    "twitter": "𝕏 X / Twitter",
    "pornhub": "🔞 Pornhub",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def locate_ffmpeg() -> str | None:
    """优先使用 imageio-ffmpeg 自带的 ffmpeg，其次在 PATH 中查找。"""
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def get_platform_label(info: dict) -> str:
    extractor = (info.get("extractor") or info.get("extractor_key") or "unknown")
    key = (extractor or "").lower()
    for k, v in PLATFORM_ICON.items():
        if k in key:
            return v
    return extractor


def _human(num: float | None) -> str:
    num = num or 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}PB"


# ---------------------------------------------------------------------------
# 进度回调
# ---------------------------------------------------------------------------
class ProgressReporter:
    """把 yt-dlp 的进度字典转交给外部回调（CLI 打印 / GUI 日志）。"""

    def __init__(self, callback=None):
        self.callback = callback

    def hook(self, d: dict):
        if self.callback:
            self.callback(d)


def _cli_status(url: str, d: dict):
    """CLI 模式下的进度打印（输出到 stderr，不污染 stdout 的 JSON）。url 参数被忽略。"""
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes", 0)
        pct = (downloaded / total * 100) if total else 0.0
        speed = d.get("speed") or 0
        eta = d.get("eta") or 0
        sys.stderr.write(
            f"\r  ⏬ {pct:5.1f}% | {_human(downloaded)}/{_human(total)} "
            f"| {_human(speed)}/s | ETA {int(eta)}s "
        )
        sys.stderr.flush()
    elif d.get("status") == "finished":
        sys.stderr.write("\n  ✅ 片段完成，正在合并/后处理…\n")
        sys.stderr.flush()
    elif d.get("status") == "error":
        sys.stderr.write(f"\n  ❌ 下载错误: {d.get('msg')}\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# 构建 yt-dlp 选项
# ---------------------------------------------------------------------------
def build_ydl_opts(
    output_dir: str,
    quality: str = "best",
    cookies_browser: str | None = None,
    cookies_file: str | None = None,
    print_info: bool = False,
    quiet: bool = False,
    no_mtime: bool = False,
    no_playlist: bool = False,
    proxy: str | None = None,
    progress_callback=None,
) -> dict:
    ffmpeg = locate_ffmpeg()
    fmt = QUALITY_PRESETS.get(quality, quality)  # 未知串（自定义格式）原样使用
    outtmpl = os.path.join(output_dir, "%(extractor)s", "%(title)s [%(id)s].%(ext)s")

    opts = {
        "format": fmt,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "noplaylist": no_playlist,
        "quiet": quiet,
        "no_warnings": quiet,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
        "noprogress": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
        "progress_hooks": [ProgressReporter(progress_callback).hook],
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if no_mtime:
        opts["updatetime"] = False
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if proxy:
        opts["proxy"] = proxy
    if print_info:
        opts["simulate"] = True
        opts["dump_single_json"] = True
        opts["quiet"] = True
        opts["no_warnings"] = True
        opts["progress_hooks"] = []
    return opts


# ---------------------------------------------------------------------------
# 下载逻辑
# ---------------------------------------------------------------------------
def download_one(url: str, progress_callback=None, **opts_kwargs) -> dict:
    """下载单个 URL，返回视频信息字典。失败抛出 RuntimeError。"""
    proxy = opts_kwargs.get("proxy")
    if proxy:
        # 同时注入进程环境变量，确保 ffmpeg 子进程（m3u8 分片）也走代理
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    # 把 url 一并交给回调，便于上层（GUI）按任务区分进度
    cb = (lambda d: progress_callback(url, d)) if progress_callback else None
    opts = build_ydl_opts(progress_callback=cb, **opts_kwargs)
    simulate = opts.get("simulate", False)
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=not simulate)
        except (DownloadError, ExtractorError) as e:
            raise RuntimeError(f"下载失败 [{url}]: {e}") from e
    return info or {}


def download_batch(urls, threads: int = 1, progress_callback=None, **opts_kwargs):
    """批量下载，返回 [(url, ok, payload)] 列表。单线程逐条，多线程用线程池。"""
    results = []

    def _run(u):
        return download_one(u, progress_callback=progress_callback, **opts_kwargs)

    if threads <= 1:
        for u in urls:
            try:
                info = _run(u)
                results.append((u, True, info))
            except Exception as e:  # 单线程：记录失败继续下一个
                results.append((u, False, str(e)))
                sys.stderr.write(f"  ❌ {u}: {e}\n")
        return results

    with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
        fut_map = {ex.submit(_run, u): u for u in urls}
        for fut in as_completed(fut_map):
            u = fut_map[fut]
            try:
                info = fut.result()
                results.append((u, True, info))
            except Exception as e:
                results.append((u, False, str(e)))
                sys.stderr.write(f"  ❌ {u}: {e}\n")
    return results


# ---------------------------------------------------------------------------
# 辅助：读取 URL 列表 / 列出格式 / 精简信息
# ---------------------------------------------------------------------------
def _read_urls(path: str):
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def _read_urls_stream(stream):
    urls = []
    for line in stream:
        line = line.strip()
        if line:
            urls.append(line)
    return urls


def _list_formats(url: str, proxy: str | None = None):
    opts = {"quiet": True, "no_warnings": True, "simulate": True}
    if proxy:
        opts["proxy"] = proxy
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        sys.stdout.write(f"\n=== {get_platform_label(info)} | {info.get('title')} ===\n")
        ydl.list_formats(info)


def _trim_info(info: dict) -> dict:
    keep = [
        "id", "title", "extractor", "extractor_key", "webpage_url", "url",
        "duration", "view_count", "like_count", "uploader", "uploader_id",
        "upload_date", "channel", "channel_id", "age_limit", "format",
        "format_id", "width", "height", "fps", "vcodec", "acodec",
        "abr", "vbr", "filesize", "filesize_approx", "protocol",
    ]
    return {k: info.get(k) for k in keep if k in info}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="video_downloader",
        description="通用视频下载器（YouTube / X / Pornhub 等，基于 yt-dlp）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("urls", nargs="*", help="视频链接（可多个）")
    parser.add_argument("-a", "--batch-file", help="从文件读取 URL（每行一个，# 开头为注释）")
    parser.add_argument("-o", "--output", default="./downloads", help="输出目录（默认 ./downloads）")
    parser.add_argument("-q", "--quality", default="best", choices=list(QUALITY_PRESETS.keys()),
                        help="画质预设（默认 best）")
    parser.add_argument("--format", dest="custom_format", help="自定义 yt-dlp 格式串，覆盖 -q")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="从浏览器读取 Cookie: chrome/firefox/edge/brave/opera/safari/chromium")
    parser.add_argument("--cookie-file", help="Netscape 格式 Cookie 文件路径")
    parser.add_argument("--proxy", metavar="URL",
                        help="本地代理地址，如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7891")
    parser.add_argument("--print-info", action="store_true", help="仅打印视频信息，不下载")
    parser.add_argument("--list-formats", action="store_true", help="列出可用格式后退出")
    parser.add_argument("--threads", type=int, default=1, help="批量下载并发线程数（默认 1）")
    parser.add_argument("--no-playlist", action="store_true", help="遇到播放列表只下载单个视频")
    parser.add_argument("--no-mtime", action="store_true", help="不修改文件修改时间为视频时间")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细进度")
    args = parser.parse_args(argv)

    # 收集 URL
    urls = list(args.urls)
    if args.batch_file:
        urls += _read_urls(args.batch_file)
    if not urls and not sys.stdin.isatty():
        urls += _read_urls_stream(sys.stdin)
    if not urls:
        parser.print_help()
        return 1

    quality = args.custom_format if args.custom_format else args.quality

    ffmpeg = locate_ffmpeg()
    print(f"🎬 待处理 {len(urls)} 个任务 | 输出: {args.output}")
    print(f"🛠 ffmpeg: {ffmpeg or '未找到（部分功能受限，建议安装 ffmpeg）'}")
    if args.proxy:
        print(f"🌐 代理: {args.proxy}")
    os.makedirs(args.output, exist_ok=True)

    if args.list_formats:
        for u in urls:
            _list_formats(u, proxy=args.proxy)
        return 0

    if args.print_info:
        for u in urls:
            try:
                info = download_one(
                    u, output_dir=args.output, quality=quality,
                    cookies_browser=args.cookies_from_browser,
                    cookies_file=args.cookie_file, print_info=True, quiet=True,
                    no_playlist=args.no_playlist, proxy=args.proxy,
                )
                print(json.dumps(_trim_info(info), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"❌ {u}: {e}", file=sys.stderr)
        return 0

    results = download_batch(
        urls, threads=args.threads, progress_callback=(_cli_status if args.verbose else None),
        output_dir=args.output, quality=quality,
        cookies_browser=args.cookies_from_browser, cookies_file=args.cookie_file,
        quiet=not args.verbose, no_mtime=args.no_mtime, no_playlist=args.no_playlist,
        proxy=args.proxy,
    )
    ok = sum(1 for r in results if r[1])
    print(f"\n✅ 完成：成功 {ok}/{len(results)}")
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    sys.exit(main())
