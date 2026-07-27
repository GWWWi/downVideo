@echo off
REM ============================================================
REM  Build a portable onedir package.
REM  Requires (on the build machine only):
REM    pip install pyinstaller yt-dlp imageio-ffmpeg
REM  Output: dist\VideoDownloader\VideoDownloader.exe
REM  NOTE: You do NOT need this on the target PC. Just copy the
REM        already-built dist\VideoDownloader folder to it.
REM ============================================================
setlocal

where pyinstaller >nul 2>nul
if not errorlevel 1 (
    set PI=pyinstaller
) else (
    set PI=python -m PyInstaller
)

%PI% -y --noconfirm --clean --name VideoDownloader --windowed --collect-submodules yt_dlp --collect-all imageio_ffmpeg gui_downloader.py

if exist "dist\VideoDownloader\VideoDownloader.exe" (
    echo BUILD OK: dist\VideoDownloader\VideoDownloader.exe
) else (
    echo BUILD FAILED. See output above.
)
pause
