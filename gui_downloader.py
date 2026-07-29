#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用视频下载器 - 图形界面 (tkinter)
====================================
运行:  python gui_downloader.py
依赖:  yt-dlp, imageio-ffmpeg（见 requirements.txt）

功能:
  - 选择下载分辨率（预设 + 一键「检测分辨率」获取真实可选清晰度）
  - 下载列表：每个链接独立一行，显示图标 / 标题 / 进度条 / 百分比·速度·ETA·大小
  - 全部下载完成后自动关机（可设延迟分钟数，可取消）
  - 批量下载、多线程、浏览器 Cookie、本地代理、日志
"""
import os
import sys
import subprocess
import datetime
import threading

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_downloader import download_batch, locate_ffmpeg, _human, _resolve_cookiefile, build_ydl_opts

try:
    from yt_dlp import YoutubeDL
except Exception:  # pragma: no cover
    YoutubeDL = None

# 预设分辨率：标签 -> yt-dlp 画质 key
PRESETS = [
    ("最佳画质", "best"),
    ("2160p (4K)", "2160p"),
    ("1440p", "1440p"),
    ("1080p", "1080p"),
    ("720p", "720p"),
    ("480p", "480p"),
    ("360p", "360p"),
    ("仅音频", "audio"),
]

BROWSERS = ["无", "chrome", "firefox", "edge", "brave", "opera", "safari", "chromium"]

# 记住上次用过的输出目录 / 代理，写在脚本同目录的配置文件里
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_config.json")


def _load_config():
    try:
        import json
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data: dict):
    try:
        import json
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _trunc(s: str, n: int = 60) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def _auth_hint(err) -> str:
    """针对 YouTube 年龄限制 / 需要登录 / 格式不可用 的报错，给出中文操作提示。"""
    e = str(err)
    low = e.lower()
    if "confirm your age" in low or "age-restricted" in low or "sign in to confirm" in low:
        return ("（该视频为年龄限制内容，需在「Cookie 浏览器」选择已登录 YouTube 的浏览器，"
                "或提供 Cookie 文件后再试。注意：账号本身需在 YouTube 完成年龄验证）")
    if "requested format is not available" in low:
        return ("（所选清晰度在该视频上不可用。请改选「最佳画质」重试；"
                "若是年龄限制视频，需确保 Cookie 对应的 YouTube 账号已完成年龄验证且 Cookie 未过期，"
                "可在能正常观看该视频的浏览器里重新导出 Cookie）")
    if "cookies" in low or "authentication" in low or "login" in low:
        return "（该视频可能需要登录，请在「Cookie 浏览器」选择已登录的浏览器，或提供 Cookie 文件）"
    return ""


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("通用视频下载器")
        root.geometry("820x720")
        root.resizable(True, True)

        self.fmt_map = dict(PRESETS)  # 标签 -> 格式串/key
        self.task_map = {}            # url -> 任务行控件字典
        self.tasks = []               # 任务行列表
        self._shutdown_pending = False

        cfg = _load_config()

        # ---- 设置区 ----
        frm_top = ttk.LabelFrame(root, text="下载设置", padding=8)
        frm_top.pack(fill="x", padx=10, pady=8)

        ttk.Label(frm_top, text="视频链接（每行一个）:").grid(row=0, column=0, sticky="nw", pady=2)
        self.url_text = scrolledtext.ScrolledText(frm_top, height=6, width=76)
        self.url_text.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(frm_top, text="输出目录:").grid(row=1, column=0, sticky="w", pady=2)
        self.out_var = tk.StringVar(value=cfg.get("output_dir") or os.path.abspath("./downloads"))
        ttk.Entry(frm_top, textvariable=self.out_var, width=56).grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Button(frm_top, text="浏览\u2026", command=self._choose_dir).grid(row=1, column=3, padx=4, pady=2)

        ttk.Label(frm_top, text="分辨率:").grid(row=2, column=0, sticky="w", pady=2)
        self.res_var = tk.StringVar(value=PRESETS[0][0])
        self.res_combo = ttk.Combobox(frm_top, textvariable=self.res_var,
                                      values=[l for l, _ in PRESETS], state="readonly", width=14)
        self.res_combo.grid(row=2, column=1, sticky="w", pady=2)
        self.detect_btn = ttk.Button(frm_top, text="检测分辨率", command=self._on_detect)
        self.detect_btn.grid(row=2, column=2, padx=4, pady=2, sticky="w")

        ttk.Label(frm_top, text="Cookie 浏览器:").grid(row=3, column=0, sticky="w", pady=2)
        self.browser_var = tk.StringVar(value="无")
        ttk.Combobox(frm_top, textvariable=self.browser_var, values=BROWSERS,
                     state="readonly", width=12).grid(row=3, column=1, sticky="w", pady=2)

        ttk.Label(frm_top, text="Cookie 文件:").grid(row=4, column=0, sticky="w", pady=2)
        self.cookie_var = tk.StringVar()
        ttk.Entry(frm_top, textvariable=self.cookie_var, width=56).grid(row=4, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Button(frm_top, text="选择\u2026", command=self._choose_cookie).grid(row=4, column=3, padx=4, pady=2)

        ttk.Label(frm_top, text="本地代理:").grid(row=5, column=0, sticky="w", pady=2)
        self.proxy_var = tk.StringVar(value=cfg.get("proxy", ""))
        ttk.Entry(frm_top, textvariable=self.proxy_var, width=56).grid(row=5, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(frm_top, text="例: http://127.0.0.1:7890", foreground="#888").grid(row=5, column=3, sticky="w", padx=4, pady=2)

        ttk.Label(frm_top, text="并发线程:").grid(row=6, column=0, sticky="w", pady=2)
        self.threads_var = tk.IntVar(value=1)
        ttk.Spinbox(frm_top, from_=1, to=8, textvariable=self.threads_var, width=10).grid(row=6, column=1, sticky="w", pady=2)

        ffmpeg = locate_ffmpeg()
        ttk.Label(frm_top, text=f"ffmpeg: {ffmpeg or '未找到'}").grid(row=7, column=1, columnspan=3, sticky="w", pady=2)

        # ---- 下载列表区（每个任务一行）----
        frm_tasks = ttk.LabelFrame(root, text="下载列表", padding=8)
        frm_tasks.pack(fill="x", padx=10, pady=4)
        self.task_canvas = tk.Canvas(frm_tasks, height=200, borderwidth=0)
        self.task_scroll = ttk.Scrollbar(frm_tasks, orient="vertical", command=self.task_canvas.yview)
        self.task_inner = ttk.Frame(self.task_canvas)
        self.task_inner.bind(
            "<Configure>",
            lambda e: self.task_canvas.configure(scrollregion=self.task_canvas.bbox("all")),
        )
        self.task_canvas.create_window((0, 0), window=self.task_inner, anchor="nw")
        self.task_canvas.configure(yscrollcommand=self.task_scroll.set)
        self.task_canvas.pack(side="left", fill="both", expand=True)
        self.task_scroll.pack(side="right", fill="y")
        # 鼠标滚轮滚动列表
        self.task_canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.task_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        # ---- 完成动作（自动关机）----
        frm_sd = ttk.LabelFrame(root, text="完成动作", padding=8)
        frm_sd.pack(fill="x", padx=10, pady=4)
        self.shutdown_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_sd, text="全部下载完成后自动关机", variable=self.shutdown_var).grid(
            row=0, column=0, sticky="w")
        ttk.Label(frm_sd, text="关机延迟(分钟):").grid(row=0, column=1, sticky="w", padx=(14, 2))
        self.delay_var = tk.IntVar(value=0)
        ttk.Spinbox(frm_sd, from_=0, to=120, textvariable=self.delay_var, width=6).grid(row=0, column=2, sticky="w")
        self.cancel_btn = ttk.Button(frm_sd, text="取消关机", command=self._cancel_shutdown, state="disabled")
        self.cancel_btn.grid(row=0, column=3, padx=10)
        self.shutdown_status = ttk.Label(frm_sd, text="", foreground="#c0392b")
        self.shutdown_status.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # ---- 操作按钮 ----
        frm_btn = ttk.Frame(root)
        frm_btn.pack(fill="x", padx=10, pady=4)
        self.download_btn = ttk.Button(frm_btn, text="开始下载", command=self._on_download)
        self.download_btn.pack(side="left", padx=4)
        ttk.Button(frm_btn, text="清空日志", command=lambda: self.log_box.delete("1.0", tk.END)).pack(side="left", padx=4)
        ttk.Button(frm_btn, text="清空链接", command=lambda: self.url_text.delete("1.0", tk.END)).pack(side="left", padx=4)

        # ---- 日志区 ----
        frm_log = ttk.LabelFrame(root, text="日志", padding=8)
        frm_log.pack(fill="both", expand=True, padx=10, pady=8)
        self.log_box = scrolledtext.ScrolledText(frm_log, height=10, state="normal")
        self.log_box.pack(fill="both", expand=True)

        self._append("就绪。粘贴链接后点击「开始下载」。\n")
        self._append("提示: 点「检测分辨率」可获取该视频真实可选清晰度；X / Pornhub 等建议先选「Cookie 浏览器」。\n")

        # 关闭窗口时若有待执行关机，先取消
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -------- 文件选择 --------
    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get())
        if d:
            self.out_var.set(d)
            cfg = _load_config()
            cfg["output_dir"] = d
            _save_config(cfg)

    def _choose_cookie(self):
        f = filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt"), ("All", "*.*")])
        if f:
            self.cookie_var.set(f)

    # -------- 检测分辨率 --------
    def _on_detect(self):
        urls = [u.strip() for u in self.url_text.get("1.0", tk.END).splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("提示", "请先粘贴一个视频链接")
            return
        if YoutubeDL is None:
            messagebox.showerror("错误", "未安装 yt-dlp")
            return
        self.detect_btn.config(state="disabled")
        self._append("\ud83d\udd0d 正在获取可用分辨率\u2026\n")
        threading.Thread(target=self._detect_worker, daemon=True, args=(urls[0],)).start()

    def _detect_worker(self, url):
        try:
            browser = self.browser_var.get()
            cookie = self.cookie_var.get()
            proxy = self.proxy_var.get().strip()
            if proxy:
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
            # 用与下载完全一致的健壮设置（User-Agent / 重试 / nocheckcertificate / socket_timeout），
            # 并以 best 探测，避免手写极简 opts 缺省 UA 或在 simulate 阶段因所选分辨率过滤而报
            # "Requested format is not available"。探测目的是列出可选清晰度，故不套用用户所选画质过滤。
            opts = build_ydl_opts(
                output_dir=".",
                quality="best",
                print_info=True,
                quiet=True,
                cookies_browser=(browser if browser != "\u65e0" else None),
                cookies_file=(cookie if cookie else None),
                proxy=(proxy or None),
            )
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats") or []
            heights = {}
            for f in formats:
                h = f.get("height")
                if h and f.get("vcodec") not in (None, "none"):
                    heights.setdefault(h, f)
            fmt_map = dict(PRESETS)
            labels = [l for l, _ in PRESETS]
            for h in sorted(heights.keys(), reverse=True):
                label = f"{h}p"
                if label in fmt_map:
                    continue
                fmt_map[label] = f"bv[height={h}]+ba/best[height={h}]"
                labels.append(label)
            self.root.after(0, self._apply_resolutions, labels, fmt_map)
            self.root.after(0, self._append, f"\u2705 检测到分辨率: {', '.join(labels)}\n")
        except Exception as e:
            self.root.after(0, self._append, f"\u274c 检测失败: {e}\n")
            hint = _auth_hint(e)
            if hint:
                self.root.after(0, self._append, hint + "\n")
        finally:
            self.root.after(0, lambda: self.detect_btn.config(state="normal"))

    def _apply_resolutions(self, labels, fmt_map):
        self.fmt_map = fmt_map
        self.res_combo["values"] = labels
        if labels:
            self.res_var.set(labels[0])

    # -------- 下载列表 UI --------
    def _build_tasks(self, urls):
        for w in self.task_inner.winfo_children():
            w.destroy()
        self.task_map = {}
        self.tasks = []
        for u in urls:
            self._add_task_row(u)
        n = len(urls)
        self.task_canvas.configure(height=min(260, max(80, 20 + n * 62)))
        self.task_canvas.configure(scrollregion=self.task_canvas.bbox("all"))

    def _add_task_row(self, url):
        row = ttk.Frame(self.task_inner)
        row.pack(fill="x", padx=2, pady=3)
        icon = ttk.Label(row, text="\u23f3", width=3)  # ⏳
        icon.grid(row=0, column=0)
        title_lbl = ttk.Label(row, text=_trunc(url, 70), anchor="w")
        title_lbl.grid(row=0, column=1, sticky="ew")
        row.columnconfigure(1, weight=1)
        bar = ttk.Progressbar(row, mode="determinate", maximum=100, value=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        detail = ttk.Label(row, text="等待开始", foreground="#666")
        detail.grid(row=2, column=0, columnspan=2, sticky="w")
        task = {
            "url": url, "title": url, "title_is_url": True,
            "icon": icon, "title_lbl": title_lbl, "bar": bar, "detail": detail,
            "status": "\u7b49\u5f85",
        }
        self.task_map[url] = task
        self.tasks.append(task)

    # -------- 下载 --------
    def _on_download(self):
        urls = [u.strip() for u in self.url_text.get("1.0", tk.END).splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("提示", "请输入至少一个视频链接")
            return
        # 若上一次关机计划还在，先取消再开始新任务
        if self._shutdown_pending:
            self._cancel_shutdown()
        out = self.out_var.get() or "./downloads"
        sel = self.fmt_map.get(self.res_var.get(), self.res_var.get())
        browser = self.browser_var.get()
        cookie = self.cookie_var.get()
        threads = max(1, int(self.threads_var.get()))
        proxy = self.proxy_var.get().strip()

        # 自动建好输出目录，并记住本次选择（下次打开自动带出）
        out = os.path.abspath(out)
        os.makedirs(out, exist_ok=True)
        cfg = _load_config()
        cfg["output_dir"] = out
        if proxy:
            cfg["proxy"] = proxy
        _save_config(cfg)

        self._build_tasks(urls)
        self.download_btn.config(state="disabled")
        self._append(f"\n=== 开始下载 {len(urls)} 个任务 \u2192 {out} | 分辨率: {self.res_var.get()}"
                     + (f" | 代理: {proxy}" if proxy else "") + " ===\n")
        threading.Thread(
            target=self._worker, daemon=True,
            args=(urls, out, sel, browser, cookie, threads, proxy),
        ).start()

    def _worker(self, urls, out, sel, browser, cookie, threads, proxy):
        def cb(url, d):
            self.root.after(0, self._on_progress, url, d)

        try:
            results = download_batch(
                urls, threads=threads, progress_callback=cb,
                output_dir=out, quality=sel,
                cookies_browser=(browser if browser != "\u65e0" else None),
                cookies_file=(cookie if cookie else None),
                proxy=(proxy or None),
                quiet=True,  # windowed 模式下不向 None 流输出；进度由回调展示，错误写入 downloader.log
            )
        except Exception as e:
            self.root.after(0, self._append, f"\ud83d\udca5 异常: {e}\n")
            hint = _auth_hint(e)
            if hint:
                self.root.after(0, self._append, hint + "\n")
            self.root.after(0, lambda: self.download_btn.config(state="normal"))
            return

        # 汇总每个任务最终状态
        ok = 0
        for (u, success, payload) in results:
            task = self.task_map.get(u)
            if task is None:
                continue
            if success:
                task["bar"]["value"] = 100
                task["icon"].config(text="\u2705")  # ✅
                task["status"] = "\u5b8c\u6210"
                task["detail"].config(text="\u2705 已完成", foreground="#1a7f37")
                ok += 1
            else:
                task["icon"].config(text="\u274c")  # ❌
                task["status"] = "\u5931\u8d25"
                task["detail"].config(text="\u274c " + _trunc(str(payload), 90), foreground="#c0392b")
        self.root.after(0, self._on_all_done, ok, len(results))

    def _on_progress(self, url, d):
        task = self.task_map.get(url)
        if task is None:
            return
        info = d.get("info_dict") or {}
        title = info.get("title")
        if title and task.get("title_is_url"):
            task["title_lbl"].config(text=_trunc(title, 70))
            task["title_is_url"] = False
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl = d.get("downloaded_bytes", 0)
            pct = (dl / total * 100) if total else 0.0
            speed = d.get("speed", 0) or 0
            eta = d.get("eta", 0) or 0
            task["bar"]["value"] = pct
            task["detail"].config(
                text=f"{pct:.1f}%  {_human(dl)}/{_human(total)}  {_human(speed)}/s  ETA {int(eta)}s",
                foreground="#333",
            )
            if task["status"] != "\u4e0b\u8f7d\u4e2d":
                task["status"] = "\u4e0b\u8f7d\u4e2d"
                task["icon"].config(text="\u2b07\ufe0f")  # ⬇️
        elif st == "finished":
            task["bar"]["value"] = 100
            task["detail"].config(text="\u2705 下载完成，正在合并/后处理\u2026", foreground="#333")
            task["icon"].config(text="\u23f3")  # ⏳
            task["status"] = "\u5b8c\u6210"
        elif st == "error":
            task["detail"].config(text="\u274c " + _trunc(str(d.get("msg", "\u9519\u8bef")), 90), foreground="#c0392b")
            task["icon"].config(text="\u26d4")  # ⛔
            task["status"] = "\u5931\u8d25"

    def _on_all_done(self, ok, total):
        self.download_btn.config(state="normal")
        self._append(f"\n\u2705 完成：成功 {ok}/{total}\n")
        if self.shutdown_var.get():
            self._schedule_shutdown(self.delay_var.get())

    # -------- 自动关机 --------
    def _schedule_shutdown(self, delay_min: int):
        delay_min = int(delay_min)
        secs = max(0, delay_min * 60)
        shut_at = datetime.datetime.now() + datetime.timedelta(seconds=secs)
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["shutdown", "/s", "/t", str(secs)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                # Linux / macOS
                mins = max(1, delay_min) if delay_min > 0 else 1
                subprocess.Popen(
                    ["shutdown", "-h", f"+{mins}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            self._shutdown_pending = True
            self.cancel_btn.config(state="normal")
            msg = f"\u23fb 已安排自动关机：{shut_at.strftime('%H:%M:%S')}"
            if delay_min > 0:
                msg += f"（{delay_min} 分钟后）"
            self.shutdown_status.config(text=msg + "  \u2014  关闭前可点「取消关机」中止")
            self._append("🔌 " + msg + "（可在关闭程序前点击「取消关机」中止）。\n")
        except Exception as e:
            self.shutdown_status.config(text=f"⚠️ 关机命令失败: {e}")
            self._append(f"⚠️ 自动关机命令执行失败: {e}\n")

    def _cancel_shutdown(self):
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["shutdown", "/a"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            self._shutdown_pending = False
            self.cancel_btn.config(state="disabled")
            self.shutdown_status.config(text="已取消自动关机", foreground="#1a7f37")
            self._append("🚫 已取消自动关机。\n")
        except Exception as e:
            self._append(f"⚠️ 取消关机失败: {e}\n")

    def _on_close(self):
        if self._shutdown_pending:
            self._cancel_shutdown()
        self.root.destroy()

    def _append(self, msg):
        self.log_box.insert(tk.END, msg)
        self.log_box.see(tk.END)

    def log(self, msg):
        self.root.after(0, lambda: self._append(msg))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
