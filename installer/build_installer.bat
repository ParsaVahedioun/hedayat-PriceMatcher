@echo off
REM ============================================================
REM  PriceMatcher - build the EXE and then the Setup installer
REM  Run this on ONE Windows PC that has Python + Inno Setup.
REM  The result runs on any Windows PC without Python.
REM ============================================================
setlocal
cd /d "%~dp0\.."

echo.
echo === STEP 1: building PriceMatcher.exe ===
call build.bat
if not exist "dist\PriceMatcher\PriceMatcher.exe" (
    echo EXE build failed - aborting.
    pause
    exit /b 1
)

echo.
echo === STEP 2: making the portable ZIP ===
if exist "installer\output\PriceMatcher-Portable.zip" del "installer\output\PriceMatcher-Portable.zip"
if not exist "installer\output" mkdir "installer\output"
powershell -NoProfile -Command ^
  "Compress-Archive -Path 'dist\PriceMatcher\*' -DestinationPath 'installer\output\PriceMatcher-Portable.zip' -Force"

echo.
echo === STEP 3: compiling the installer ===
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 not found.
    echo Install it from https://jrsoftware.org/isdl.php and run this script again.
    echo The portable ZIP in installer\output is ready to use meanwhile.
    pause
    exit /b 1
)
"%ISCC%" "installer\PriceMatcher.iss"
if errorlevel 1 (
    echo Installer compilation failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  installer\output\PriceMatcher-Setup.exe       ^<- installer
echo  installer\output\PriceMatcher-Portable.zip    ^<- portable
echo  Neither one needs Python on the target PC.
echo ============================================================
pause
endlocal
