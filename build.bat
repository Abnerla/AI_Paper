@echo off
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHON_EXE=py"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

echo ========================================
echo 纸研社 - 打包脚本
echo ========================================
echo.

echo [1/5] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo 旧产物已清理
echo.

echo [2/5] 安装依赖...
"%PYTHON_EXE%" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo 依赖安装失败，请检查Python是否正常
    pause
    exit /b 1
)

echo [3/5] 生成程序图标...
"%PYTHON_EXE%" .\tools\generate_logo_icon.py
if errorlevel 1 (
    echo 图标生成失败！
    pause
    exit /b 1
)
echo 图标文件已同步
echo.

echo [4/5] 开始打包...
"%PYTHON_EXE%" -m PyInstaller --noconfirm 纸研社.spec

if errorlevel 1 (
    echo 打包失败！
    pause
    exit /b 1
)

echo [5/5] 打包完成！
echo 可执行文件位于 dist\纸研社.exe
echo.
pause
