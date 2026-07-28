@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
REM 打包为便携版 onedir 程序，完成后自动清理 build 中间文件，并给出提示。
REM 使用 VideoDownloader.spec 作为唯一定义来源，避免每次覆盖自定义 spec。
cd /d "%~dp0"

set "VENV=C:\Users\fangbo\.workbuddy\binaries\python\envs\default"
set "SPEC=VideoDownloader.spec"
set "OUT_DIR=dist\VideoDownloader"
set "BUILD_DIR=build"

echo ============================================================
echo  [1/4] 准备打包环境...
echo ============================================================
if not exist "%VENV%\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先创建 venv 并安装依赖：
    echo   python -m venv "%VENV%"
    echo   "%VENV%\Scripts\pip.exe" install pyinstaller yt-dlp imageio-ffmpeg
    goto :fail
)
if exist "%VENV%\Scripts\pyinstaller.exe" (
    set "PI=%VENV%\Scripts\pyinstaller.exe"
) else (
    set "PI=%VENV%\Scripts\python.exe" -m PyInstaller
)
echo  使用 PyInstaller: %PI%
echo  spec 文件: %SPEC%

echo.
echo ============================================================
echo  [2/4] 正在打包 VideoDownloader（基于 %SPEC%）...
echo ============================================================
%PI% -y --noconfirm --clean "%SPEC%"
if errorlevel 1 (
    echo [错误] 打包过程失败，请查看上方输出。
    goto :fail
)

echo.
echo ============================================================
echo  [3/4] 校验产物...
echo ============================================================
if not exist "%OUT_DIR%\VideoDownloader.exe" (
    echo [错误] 未找到产物: %OUT_DIR%\VideoDownloader.exe
    goto :fail
)
echo  [OK] 产物已生成: %OUT_DIR%\VideoDownloader.exe

echo.
echo ============================================================
echo  [4/4] 清理 build 中间文件...
echo ============================================================
if exist "%BUILD_DIR%" (
    rmdir /s /q "%BUILD_DIR%"
    echo  [OK] 已删除 build 中间目录
) else (
    echo  [提示] 未找到 build 目录，跳过
)
if exist "__pycache__" (
    rmdir /s /q "__pycache__"
    echo  [OK] 已删除 __pycache__
)

echo.
echo ============================================================
echo  [完成] 打包成功！产物位于: %OUT_DIR%
echo ============================================================
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('打包成功！产物位于：%OUT_DIR%', 'VideoDownloader 打包', 'OK', 'Information')" 2>nul
pause
goto :eof

:fail
echo.
echo ============================================================
echo  [失败] 打包未成功完成，请检查上方错误信息。
echo ============================================================
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('打包失败，请查看控制台输出。', 'VideoDownloader 打包', 'OK', 'Error')" 2>nul
pause
exit /b 1
