@echo off
setlocal

cd /d "%~dp0"
chcp 65001 >nul

set "SPEC_FILE=build_app.spec"
set "BUILD_DIR=build"
set "DIST_DIR=dist"
set "PYTHON_EXE=py"

py -V >nul 2>&1
if errorlevel 1 if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

echo ========================================
echo PaperLab build script
echo ========================================
echo.

echo [1/5] Cleaning old artifacts...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
echo Old artifacts cleaned.
echo.

echo [2/5] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)
echo.

echo [3/5] Checking icon file...
if not exist "logo.ico" (
    echo Missing logo.ico.
    pause
    exit /b 1
)
echo Icon file found.
echo.

echo [4/5] Running PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
if errorlevel 1 (
    echo PyInstaller failed.
    pause
    exit /b 1
)
echo.

if not exist "%DIST_DIR%" (
    echo PyInstaller returned success, but the dist directory was not created.
    pause
    exit /b 1
)

dir /b "%DIST_DIR%" | findstr /r /c:".*" >nul
if errorlevel 1 (
    echo PyInstaller returned success, but the dist directory is empty.
    pause
    exit /b 1
)

echo [5/5] Build completed.
echo Output files:
dir /b "%DIST_DIR%"
echo.
pause
