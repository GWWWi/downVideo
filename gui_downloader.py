#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用视频下载器 - 图形界面 (tkinter)
====================================
运行:  python gui_downloader.py
依赖:  yt-dlp, imageio-ffmpeg（见 requirements.txt）

功能:
  - 选择下载分辨率（预设 + 一键「检测分辨率」获取真实可选清晰度）
  - 实时进度条（百分比 / 速度 / 剩余时间）
  - 批量下载、多线程、浏览器 Cookie、日志
"""
import os
import sys
import threading

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_downloader import download_batch, locate_ffmpeg, _human

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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("通用视频下载器")
        root.geometry("780x640")
        root.resizable(True, True)

        self.fmt_map = dict(PRESETS)  # 标签 -> 格式串/key

        cfg = _load_config()

        # ---- 设置区 ----
        frm_top = ttk.LabelFrame(root, text="下载设置", padding=8)
        frm_top.pack(fill="x", padx=10, pady=8)

        ttk.Label(frm_top, text="视频链接（每行一个）:").grid(row=0, column=0, sticky="nw", pady=2)
        self.url_text = scrolledtext.ScrolledText(frm_top, height=6, width=72)
        self.url_text.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(frm_top, text="输出目录:").grid(row=1, column=0, sticky="w", pady=2)
        self.out_var = tk.StringVar(value=cfg.get("output_dir") or os.path.abspath("./downloads"))
        ttk.Entry(frm_top, textvariable=self.out_var, width=52).grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Button(frm_top, text="浏览…", command=self._choose_dir).grid(row=1, column=3, padx=4, pady=2)

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
        ttk.Entry(frm_top, textvariable=self.cookie_var, width=52).grid(row=4, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Button(frm_top, text="选择…", command=self._choose_cookie).grid(row=4, column=3, padx=4, pady=2)

        ttk.Label(frm_top, text="本地代理:").grid(row=5, column=0, sticky="w", pady=2)
        self.proxy_var = tk.StringVar(value=cfg.get("proxy", ""))
        ttk.Entry(frm_top, textvariable=self.proxy_var, width=52).grid(row=5, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(frm_top, text="例: http://127.0.0.1:7890", foreground="#888").grid(row=5, column=3, sticky="w", padx=4, pady=2)

        ttk.Label(frm_top, text="并发线程:").grid(row=6, column=0, sticky="w", pady=2)
        self.threads_var = tk.IntVar(value=1)
        ttk.Spinbox(frm_top, from_=1, to=8, textvariable=self.threads_var, width=10).grid(row=6, column=1, sticky="w", pady=2)

        ffmpeg = locate_ffmpeg()
        ttk.Label(frm_top, text=f"ffmpeg: {ffmpeg or '未找到'}").grid(row=7, column=1, columnspan=3, sticky="w", pady=2)

        # ---- 进度区 ----
        frm_prog = ttk.LabelFrame(root, text="下载进度", padding=8)
        frm_prog.pack(fill="x", padx=10, pady=4)
        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 4))
        self.progress_label = ttk.Label(frm_prog, text="0.0%  等待开始")
        self.progress_label.pack(anchor="w")

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
        self.log_box = scrolledtext.ScrolledText(frm_log, height=12, state="normal")
        self.log_box.pack(fill="both", expand=True)

        self._append("就绪。粘贴链接后点击「开始下载」。\n")
        self._append("提示: 点「检测分辨率」可获取该视频真实可选清晰度；X / Pornhub 等建议先选「Cookie 浏览器」。\n")

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
        self._append("🔍 正在获取可用分辨率…\n")
        threading.Thread(target=self._detect_worker, daemon=True, args=(urls[0],)).start()

    def _detect_worker(self, url):
        try:
            opts = {"quiet": True, "no_warnings": True, "simulate": True}
            browser = self.browser_var.get()
            cookie = self.cookie_var.get()
            proxy = self.proxy_var.get().strip()
            if browser != "无":
                opts["cookiesfrombrowser"] = (browser,)
            if cookie:
                opts["cookiefile"] = cookie
            if proxy:
                opts["proxy"] = proxy
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
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
            self.root.after(0, self._append, f"✅ 检测到分辨率: {', '.join(labels)}\n")
        except Exception as e:
            self.root.after(0, self._append, f"❌ 检测失败: {e}\n")
        finally:
            self.root.after(0, lambda: self.detect_btn.config(state="normal"))

    def _apply_resolutions(self, labels, fmt_map):
        self.fmt_map = fmt_map
        self.res_combo["values"] = labels
        if labels:
            self.res_var.set(labels[0])

    # -------- 下载 --------
    def _on_download(self):
        urls = [u.strip() for u in self.url_text.get("1.0", tk.END).splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("提示", "请输入至少一个视频链接")
            return
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

        self.progress["value"] = 0
        self.progress_label["text"] = "0.0%  开始下载…"
        self.download_btn.config(state="disabled")
        self._append(f"\n=== 开始下载 {len(urls)} 个任务 → {out} | 分辨率: {self.res_var.get()}"
                     + (f" | 代理: {proxy}" if proxy else "") + " ===\n")
        threading.Thread(
            target=self._worker, daemon=True,
            args=(urls, out, sel, browser, cookie, threads, proxy),
        ).start()

    def _worker(self, urls, out, sel, browser, cookie, threads, proxy):
        def cb(d):
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                pct = (downloaded / total * 100) if total else 0.0
                self.root.after(0, self._update_progress, pct,
                                downloaded, total, d.get("speed", 0) or 0, d.get("eta", 0) or 0)
            elif status == "finished":
                self.root.after(0, self._update_progress, 100.0, 0, 0, 0, 0)
                self.root.after(0, self._append, "  ✅ 片段完成，合并中…\n")
            elif status == "error":
                self.root.after(0, self._append, f"  ❌ 错误: {d.get('msg')}\n")

        try:
            results = download_batch(
                urls, threads=threads, progress_callback=cb,
                output_dir=out, quality=sel,
                cookies_browser=(browser if browser != "无" else None),
                cookies_file=(cookie if cookie else None),
                proxy=(proxy or None),
                quiet=False,
            )
            ok = sum(1 for r in results if r[1])
            self.root.after(0, self._update_progress, 100.0, 0, 0, 0, 0)
            self.root.after(0, self._append, f"\n✅ 完成：成功 {ok}/{len(results)}\n")
        except Exception as e:
            self.root.after(0, self._append, f"💥 异常: {e}\n")
        finally:
            self.root.after(0, lambda: self.download_btn.config(state="normal"))

    def _update_progress(self, pct, downloaded, total, speed, eta):
        self.progress["value"] = pct
        self.progress_label["text"] = (
            f"{pct:.1f}%   {_human(downloaded)}/{_human(total)}   "
            f"{_human(speed)}/s   ETA {int(eta)}s"
        )

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
