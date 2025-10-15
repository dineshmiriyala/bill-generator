@echo off
echo =====================================================
echo   Building Bill Generator V 3_1_2  —  Dinesh Miriyala
echo =====================================================

:: Activate virtual environment
echo.
echo Activating virtual environment...
call ..\venv\Scripts\activate

if errorlevel 1 (
    echo Failed to activate virtual environment. Make sure "venv" exists one level above.
    pause
    exit /b
)

::call cd bill-generator
:: Confirm dependencies are up to date
echo.
echo Installing/Updating required packages...
pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo Failed to install dependencies. Please check requirements.txt
    pause
    exit /b
)

:: Clean old build artifacts
echo.
echo Cleaning old build folders...
rmdir /s /q build
rmdir /s /q dist

:: Run PyInstaller
echo.
echo Running PyInstaller build...
pyinstaller --noconsole --onefile ^
--name "BillGenerator_V3.1.2" ^
--icon "static\img\slo_bill_icon.ico" ^
--add-data "templates;templates" ^
--add-data "static;static" ^
--add-data "db;db" ^
--hidden-import jinja2.ext ^
--version-file version.txt ^
desktop_launcher.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b
)

echo =====================================================
echo Build complete! Check the 'dist' folder:
echo     → BillGenerator_V3.1.2.exe
echo =====================================================
pause