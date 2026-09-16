@echo off
REM ============================================================
REM  PriceMatcher - Windows build script
REM  Result: dist\PriceMatcher\PriceMatcher.exe  (portable folder)
REM ============================================================
setlocal

echo.
echo [1/5] checking python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found in PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)

echo [2/5] creating virtual environment...
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate.bat

echo [3/5] installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo [4/5] running tests...
REM unittest exits non-zero when a test fails AND when it discovers nothing,
REM so a renamed or unimportable test file can never slip through silently
python -m unittest discover -s tests -t . -v
if errorlevel 1 (
    echo.
    echo Tests failed or no tests were found - build aborted.
    echo Test classes must subclass unittest.TestCase and live in tests\test_*.py
    pause
    exit /b 1
)

echo [5/5] building EXE (onedir)...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
pyinstaller PriceMatcher.spec --noconfirm
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

REM config.json must sit NEXT TO the exe so the user can edit thresholds
copy /y config.json dist\PriceMatcher\config.json >nul
mkdir dist\PriceMatcher\logs 2>nul

echo.
echo ============================================================
echo  Done:  dist\PriceMatcher\PriceMatcher.exe
echo  Copy the whole "dist\PriceMatcher" folder to any Windows PC.
echo ============================================================
pause
endlocal
