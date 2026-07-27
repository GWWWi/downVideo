@echo off
setlocal
REM Build a portable onedir package using the managed venv (absolute path).
REM This avoids relying on system PATH, which does not include the venv.
cd /d "%~dp0"
set VENV=C:\Users\fangbo\.workbuddy\binaries\python\envs\default
if exist "%VENV%\Scripts\pyinstaller.exe" (
    set PI="%VENV%\Scripts\pyinstaller.exe"
) else (
    set PI="%VENV%\Scripts\python.exe" -m PyInstaller
)
echo Using PyInstaller: %PI%
%PI% -y --noconfirm --clean --name VideoDownloader --windowed --collect-submodules yt_dlp --collect-all imageio_ffmpeg gui_downloader.py
if exist "dist\VideoDownloader\VideoDownloader.exe" (
    echo BUILD OK: dist\VideoDownloader\VideoDownloader.exe
) else (
    echo BUILD FAILED. See output above.
    echo If it says "No module named ...", install deps in the venv:
    echo   "%VENV%\Scripts\pip.exe" install pyinstaller yt-dlp imageio-ffmpeg
)
pause
