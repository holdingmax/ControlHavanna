@echo off
cd /d "%~dp0"
set "APP_URL=http://localhost:8501"
set "CHROME_EXE="
set "PYTHON_CMD="

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

echo Iniciando ControlHavanna en modo local...
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=.venv\Scripts\python.exe"
)

if not defined PYTHON_CMD (
    py --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py"
)

if not defined PYTHON_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo No se encontro una instalacion valida de Python en esta maquina.
    echo.
    echo Instale Python y luego ejecute:
    echo   python -m pip install -r requirements.txt
    echo.
    pause
    exit /b
)

%PYTHON_CMD% -c "import streamlit, pandas, numpy, altair, openpyxl, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo Python fue encontrado, pero faltan dependencias de la aplicacion.
    echo.
    echo Ejecute este comando una sola vez:
    echo   %PYTHON_CMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b
)

start "ControlHavanna" cmd /k "%PYTHON_CMD% -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501"

timeout /t 4 /nobreak >nul

if defined CHROME_EXE (
    start "" "%CHROME_EXE%" "%APP_URL%"
) else (
    start "" "%APP_URL%"
)
