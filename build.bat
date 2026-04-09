@echo off
setlocal

cd /d "%~dp0"
chcp 65001 >nul

set "SPEC_FILE=build_app.spec"
set "BUILD_DIR=build"
set "DIST_DIR=dist"
set "PYTHON_EXE=py"
set "PYTHONNOUSERSITE=1"

py -V >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
    ) else (
        echo Python launcher not found.
        if not defined CI pause
        exit /b 1
    )
)

echo ========================================
echo PaperLab build script
echo ========================================
echo.

echo [1/6] Cleaning old artifacts...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
echo Old artifacts cleaned.
echo.

echo [2/6] Checking dependencies...
"%PYTHON_EXE%" -c "import importlib.util, sys; required = ['docx', 'PIL', 'fitz', 'PyInstaller']; missing = [name for name in required if importlib.util.find_spec(name) is None]; missing.extend(['win32api'] if sys.platform == 'win32' and importlib.util.find_spec('win32api') is None else []); raise SystemExit(1 if missing else 0)"
if errorlevel 1 (
    echo Installing dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo Dependency installation failed.
        if not defined CI pause
        exit /b 1
    )
    echo Dependencies installed.
) else (
    echo Dependencies already available.
)
echo.

echo [3/6] Checking icon file...
if not exist "logo.ico" (
    echo Missing logo.ico.
    if not defined CI pause
    exit /b 1
)
echo Icon file found.
echo.

echo [4/6] Running PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
if errorlevel 1 (
    echo PyInstaller failed.
    if not defined CI pause
    exit /b 1
)
echo.

if not exist "%DIST_DIR%" (
    echo PyInstaller returned success, but the dist directory was not created.
    if not defined CI pause
    exit /b 1
)

dir /b "%DIST_DIR%" | findstr /r /c:".*" >nul
if errorlevel 1 (
    echo PyInstaller returned success, but the dist directory is empty.
    if not defined CI pause
    exit /b 1
)

echo [5/6] Validating release contents...
set "HAS_FORBIDDEN_ITEMS="
for %%I in (config.enc history.json usage_events.jsonl config_dir.json logs temp) do (
    if exist "%DIST_DIR%\%%~I" (
        echo Forbidden item found in dist: %%~I
        set "HAS_FORBIDDEN_ITEMS=1"
    )
)
if defined HAS_FORBIDDEN_ITEMS (
    echo Release validation failed.
    if not defined CI pause
    exit /b 1
)
echo Release validation passed.
echo.

echo [6/6] Build completed.
echo Output files:
dir /b "%DIST_DIR%"
echo.
if not defined CI pause
