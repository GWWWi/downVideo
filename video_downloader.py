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
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import imageio_ffmpeg  # 可选依赖：自带 ffmpeg 二进制
except Exception:  # pragma: no cover
    imageio_ffmpeg = None

_WINDOWED = False  # 是否处于无控制台（windowed exe）模式，_ensure_streams 中设置
_NODE_CACHE = None   # find_node_exe 结果缓存，避免每次构建选项都启动 node --version
_DENO_CACHE = None   # find_deno_exe 结果缓存
_JS_RT_CACHE = None  # find_js_runtime 结果缓存：(name, path)


def _ensure_streams():
    """windowed（无控制台）模式下 sys.stdout / sys.stderr 为 None，
    任何 .write() 调用都会抛 'NoneType' object has no attribute 'write'。
    此处替换为安全的写日志流（写文件、不崩溃），有控制台时保持不变。"""
    global _WINDOWED
    if sys.stdout is not None and sys.stderr is not None:
        return
    _WINDOWED = True

    # 日志写在与脚本/EXE 同目录的 downloader.log，便于排查真实下载错误
    try:
        _base = os.path.dirname(os.path.abspath(__file__))
        _logf = open(os.path.join(_base, "downloader.log"), "a", encoding="utf-8", errors="replace")
    except Exception:
        _logf = None

    class _SafeStream:
        def __init__(self, logf):
            self._logf = logf

        def write(self, s, *a, **k):
            try:
                if self._logf is not None:
                    self._logf.write(s)
                    self._logf.flush()
            except Exception:
                pass
            return 0

        def flush(self, *a, **k):
            try:
                if self._logf is not None:
                    self._logf.flush()
            except Exception:
                pass

        def isatty(self, *a, **k):
            return False

        def fileno(self, *a, **k):
            return -1

    if sys.stdout is None:
        sys.stdout = _SafeStream(_logf)
    if sys.stderr is None:
        sys.stderr = _SafeStream(_logf)


_ensure_streams()  # 必须在 import yt_dlp 之前，确保 yt-dlp 捕获到安全的流

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
# Cookie 文件格式兼容：yt-dlp 只认 Netscape 文本格式
# 浏览器扩展（Cookie-Editor 等）导出的 JSON 需先转换
# ---------------------------------------------------------------------------
def _resolve_cookiefile(cookies_file: str | None) -> str | None:
    """返回真正传给 yt-dlp 的 cookie 文件路径。

    - 传入 None -> 返回 None
    - 传入已是 Netscape 文本（cookies.txt）-> 原样返回
    - 传入 JSON（浏览器扩展导出）-> 转成临时 Netscape 文件并返回其路径
      该临时文件以 `ydl_cookies_` 为前缀，供调用方在下载结束后清理
    """
    if not cookies_file:
        return None
    try:
        with open(cookies_file, "r", encoding="utf-8-sig") as f:
            head = f.read(1024).lstrip()
    except Exception:
        return cookies_file  # 读不到就交给 yt-dlp 自己报错
    if not head or head[0] not in "[{":
        return cookies_file  # 非 JSON，按 Netscape 原样处理

    try:
        with open(cookies_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return cookies_file
    if isinstance(data, dict):
        data = data.get("cookies", data)
    if not isinstance(data, list):
        return cookies_file

    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.se/docs/http-cookies.html",
        "",
    ]
    for c in data:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", ""))
        value = str(c.get("value", ""))
        # 含制表符/换行的字段会破坏 Netscape 行格式，跳过该条
        if "\t" in name or "\t" in value or "\n" in value:
            continue
        domain = c.get("domain") or ""
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        exp = c.get("expirationDate") or c.get("expires") or 0
        try:
            exp = int(float(exp))
        except Exception:
            exp = 0
        lines.append("\t".join([domain, flag, path, secure, str(exp), name, value]))

    if len(lines) <= 3:
        return cookies_file  # 没解析出任何有效 cookie

    try:
        fd, tmp = tempfile.mkstemp(prefix="ydl_cookies_", suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        return cookies_file
    return tmp


def find_node_exe() -> str | None:
    """定位 node 可执行文件，返回绝对路径（找不到返回 None）。

    yt-dlp 新版需要 JS 运行时解 YouTube 的 n/nsig 反爬挑战。不同 node 版本
    兼容性不同：实测 yt-dlp 2026.7.4 把 node 20.x 标记为 "unsupported"，
    而 node 22.x 才能正常解出真实格式（否则 "n challenge solving failed"，
    只能拿到 sb0~sb3 缩略图 → "Requested format is not available"）。
    因此这里在所有候选里挑**版本最高**的 node，避免挑到不被支持的旧版本。
    结果带缓存（_NODE_CACHE），避免每次构建下载选项都启动一次 node --version。"""
    global _NODE_CACHE
    if _NODE_CACHE is not None:
        return _NODE_CACHE
    import glob
    import re
    import subprocess

    patterns = (
        # WorkBuddy 自带 node（22.x，已验证可解 n 挑战）优先纳入候选
        os.path.expanduser("~/.workbuddy/binaries/node/versions/*/node.exe"),
        "C:/Users/*/.workbuddy/binaries/node/versions/*/node.exe",
        "C:/Program Files/nodejs/node.exe",
        "C:/Program Files (x86)/nodejs/node.exe",
        os.path.expanduser("~/AppData/Local/Programs/nodejs/node.exe"),
        os.path.expanduser("~/scoop/apps/nodejs*/current/node.exe"),
        os.path.expanduser("~/AppData/Roaming/nvm/*/node.exe"),
    )
    candidates: list[str] = []
    which_hit = shutil.which("node")  # 可能返回不受支持的旧 node（如 nvm4w 的 20.x）
    if which_hit:
        candidates.append(which_hit)
    for pat in patterns:
        candidates.extend(sorted(glob.glob(pat), reverse=True))

    # 去重（保留顺序）
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        c = os.path.abspath(c)
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append(c)

    best = None
    best_ver = (-1, -1, -1)
    for c in uniq:
        if not os.path.isfile(c):
            continue
        try:
            out = subprocess.run(
                [c, "--version"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
            if not m:
                continue
            ver = tuple(int(x) for x in m.groups())
        except Exception:
            continue
        if ver > best_ver:
            best_ver = ver
            best = c
    _NODE_CACHE = best
    return best


def find_deno_exe() -> str | None:
    """定位 deno 可执行文件，返回绝对路径（找不到返回 None）。

    deno 是 yt-dlp 默认且官方推荐的 JS 运行时，用于解 YouTube 的 n/nsig 挑战。
    用户本机已装 deno，优先使用它（不再依赖 node）。结果带缓存。"""
    global _DENO_CACHE
    if _DENO_CACHE is not None:
        return _DENO_CACHE
    import glob
    import re
    import subprocess

    patterns = (
        # 官方安装器默认位置
        os.path.expanduser("~/.deno/bin/deno"),
        os.path.expanduser("~/.deno/bin/deno.exe"),
        "C:/Users/*/.deno/bin/deno",
        "C:/Users/*/.deno/bin/deno.exe",
        # scoop
        os.path.expanduser("~/scoop/shims/deno.exe"),
        os.path.expanduser("~/scoop/apps/deno/*/deno.exe"),
        # chocolatey / winget 常见位置
        "C:/ProgramData/chocolatey/bin/deno.exe",
        "C:/Program Files/Deno Software/Deno/deno.exe",
        "C:/Program Files/deno/deno.exe",
    )
    candidates: list[str] = []
    which_hit = shutil.which("deno")
    if which_hit:
        candidates.append(which_hit)
    for pat in patterns:
        candidates.extend(sorted(glob.glob(pat), reverse=True))

    # 去重（保留顺序）
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        c = os.path.abspath(c)
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append(c)

    best = None
    best_ver = (-1, -1, -1)
    for c in uniq:
        if not os.path.isfile(c):
            continue
        try:
            out = subprocess.run(
                [c, "--version"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
            if not m:
                continue
            ver = tuple(int(x) for x in m.groups())
        except Exception:
            continue
        if ver > best_ver:
            best_ver = ver
            best = c
    _DENO_CACHE = best
    return best


def find_js_runtime():
    """返回用于解 YouTube n 挑战的 JS 运行时 (name, exe_path)，找不到返回 None。

    优先 deno（用户本机已装），找不到 deno 时才退回 node 兜底。
    返回绝对路径，避免依赖 PATH。结果带缓存。"""
    global _JS_RT_CACHE
    if _JS_RT_CACHE is not None:
        return _JS_RT_CACHE
    deno = find_deno_exe()
    if deno:
        _JS_RT_CACHE = ("deno", deno)
        return _JS_RT_CACHE
    node = find_node_exe()
    if node:
        _JS_RT_CACHE = ("node", node)
        return _JS_RT_CACHE
    _JS_RT_CACHE = None
    return None


def ensure_js_runtime_on_path():
    """把所选 JS 运行时所在目录加进 PATH（兜底，通常显式传 path 已足够）。"""
    rt = find_js_runtime()
    if rt:
        rt_dir = os.path.dirname(rt[1])
        if rt_dir.lower() not in os.environ.get("PATH", "").lower():
            os.environ["PATH"] = rt_dir + os.pathsep + os.environ.get("PATH", "")


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
    rt = find_js_runtime()  # 优先 deno，兜底 node；供 yt-dlp 解 YouTube n 挑战
    if rt:
        rt_dir = os.path.dirname(rt[1])
        if rt_dir.lower() not in os.environ.get("PATH", "").lower():
            os.environ["PATH"] = rt_dir + os.pathsep + os.environ.get("PATH", "")
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
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        # 代理型 TLS 中断（SSL UNEXPECTED_EOF）常由中间人证书引起，放宽校验以提升连通性
        "nocheckcertificate": True,
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
    # yt-dlp 用 JS 运行时解 YouTube 的 n/nsig 挑战；优先 deno（本机已装），
    # 显式传绝对路径，不依赖 PATH，否则 n 挑战失败只能解出 storyboard 缩略图（sb0~sb3）
    if rt:
        opts["js_runtimes"] = {rt[0]: {"path": rt[1]}}
    # windowed（无控制台）exe 下开启 verbose，把完整诊断写入 downloader.log，
    # 便于排查“只有 sb0~sb3 / 格式不可用”这类问题（正常控制台运行不受影响）
    if _WINDOWED and not print_info:
        opts["verbose"] = True
        opts["quiet"] = False
        opts["no_warnings"] = False
    if no_mtime:
        opts["updatetime"] = False
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if cookies_file:
        opts["cookiefile"] = _resolve_cookiefile(cookies_file)
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
def download_one(url: str, progress_callback=None, error_callback=None, **opts_kwargs) -> dict:
    """下载单个 URL，返回视频信息字典。失败抛出 RuntimeError。

    若所选画质在该视频上不可用（如年龄限制视频格式受限、地区限制），
    会自动回退到 "best"（bv*+ba/best）再尝试一次，最大化下载成功率。
    """
    proxy = opts_kwargs.get("proxy")
    if proxy:
        # 同时注入进程环境变量，确保 ffmpeg 子进程（m3u8 分片）也走代理
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    # 把 url 一并交给回调，便于上层（GUI）按任务区分进度
    cb = (lambda d: progress_callback(url, d)) if progress_callback else None
    quality = opts_kwargs.get("quality", "best")
    # 先试用户指定画质；若不可用则回退 best（仅回退一次）
    attempts = [quality, "best"] if quality not in (None, "", "best") else [quality]
    last_err = None
    for q in attempts:
        opts = build_ydl_opts(progress_callback=cb, **{**opts_kwargs, "quality": q})
        simulate = opts.get("simulate", False)
        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=not simulate)
                # 用完即删：自动转换生成的临时 cookie 文件
                _cleanup_cookiefile(opts.get("cookiefile"))
                return info or {}
            except (DownloadError, ExtractorError) as e:
                _cleanup_cookiefile(opts.get("cookiefile"))
                msg = str(e)
                # 画质不可用时，回退 best 再试一次
                if "Requested format is not available" in msg and q != "best":
                    last_err = e
                    continue
                errmsg = f"下载失败 [{url}]: {e}"
                # 实时把报错回调出去（GUI 写入日志窗口；CLI 写 stderr）
                if error_callback:
                    try:
                        error_callback(errmsg)
                    except Exception:
                        pass
                raise RuntimeError(errmsg) from e
    errmsg = f"下载失败 [{url}]: 所选画质不可用且回退 best 仍失败: {last_err}"
    if error_callback:
        try:
            error_callback(errmsg)
        except Exception:
            pass
    raise RuntimeError(errmsg) from last_err


def _cleanup_cookiefile(path: str | None):
    """删除 _resolve_cookiefile 生成的临时 Netscape cookie 文件（仅限系统临时目录内）。"""
    if not path:
        return
    try:
        if os.path.basename(path).startswith("ydl_cookies_") and os.path.dirname(path) == tempfile.gettempdir():
            os.remove(path)
    except Exception:
        pass


def download_batch(urls, threads: int = 1, progress_callback=None, error_callback=None, **opts_kwargs):
    """批量下载，返回 [(url, ok, payload)] 列表。单线程逐条，多线程用线程池。

    error_callback(msgstr): 每个任务失败时回调，便于 GUI 实时把报错写进日志窗口。
    """
    results = []

    def _run(u):
        return download_one(u, progress_callback=progress_callback, error_callback=error_callback, **opts_kwargs)

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
