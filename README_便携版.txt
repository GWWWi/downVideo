视频下载器 · 便携版使用说明
============================

本工具已打包成一个「自包含文件夹」，里面自带 Python 运行环境、yt-dlp 和 ffmpeg，
不需要在目标电脑上安装任何东西。

【如何在别的电脑上使用】
1. 把整个  dist\VideoDownloader\  文件夹拷到目标电脑（U 盘 / 网盘 / 直接复制均可）。
2. 双击其中的  VideoDownloader.exe  即可打开图形界面。
3. 首次打开会让你选「输出目录」，建议选一个空间充足的文件夹。
4. 国内访问 YouTube / X / Pornhub 需要代理：在界面「本地代理」里填你的代理地址，
   例如  http://127.0.0.1:7890  （Clash 的 HTTP 代理）或 socks5://127.0.0.1:7891 。
5. 需要登录态的站点（X、Pornhub、年龄限制视频）：建议用「Cookie 文件」方式
   （浏览器插件导出 Netscape 格式 cookies.txt 后，在界面「Cookie 文件」里选中），
   比「Cookie 浏览器」更稳，也避免 Chrome 锁库报错。

【说明】
- 选过的「输出目录」和「代理」会自动记到文件夹里的 gui_config.json，下次打开自动带出。
- 下载的视频按站点分子文件夹存放，例如  downloads/YouTube/标题 [ID].mp4 。
- 仅支持 64 位 Windows（打包机为 Windows x64）。若目标电脑是 ARM 版 Windows，
  需在同一架构的机器上重新打包。

【如何自己重新打包】（可选，仅在打包机需要）s
前置：pip install pyinstaller yt-dlp imageio-ffmpeg
双击  build.bat  即可，生成的便携包在 dist\VideoDownloader\ 。
