@echo off
rem ===========================================================================
rem  IFRS 9 app: get the code, set up Python, start the app.
rem
rem  First time: downloads the two repositories (engine and app), installs
rem  Python if none is found, creates a virtual environment, installs the
rem  requirements, then starts the backend and the interface and opens the
rem  browser. Every later time: fetches the latest code, reinstalls only when
rem  the requirements changed, and restarts the app.
rem
rem  Put this file in the folder that should hold the two repositories (for
rem  example Documents\IFRS9_apps) and double-click it. Run from inside the
rem  ifrs9_app_py folder, it works on the folder above.
rem
rem  Your configuration, runs, config versions, macro store and logs are never
rem  overwritten by an update. Python packages go to a virtual environment in
rem  %LOCALAPPDATA%\ifrs9_app; the output of each step is in launcher_logs.
rem ===========================================================================
setlocal EnableExtensions

rem  Run from a copy in TEMP: the update below may replace this very file, and
rem  Windows reads a batch file as it goes.
if "%~1"=="--from" goto running_copy
copy /y "%~f0" "%TEMP%\ifrs9_launcher.bat" >nul
"%TEMP%\ifrs9_launcher.bat" --from "%~f0"
:running_copy
set "ORIG=%~2"

rem ---- settings -------------------------------------------------------------
set "GH=https://github.com/nsahuqdb"
set "BRANCH=claude/clever-ride-arvjxs"
set "ENGINE=ifrs9qdb_py"
set "APP=ifrs9_app_py"
set "PY_VERSION=3.12.10"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=8501"
rem  behind a proxy that Windows does not hand to the command line, e.g.
rem  set "PROXY=http://proxy.example:8080"
set "PROXY="
rem ---------------------------------------------------------------------------
if defined PROXY set "HTTPS_PROXY=%PROXY%"
if defined PROXY set "HTTP_PROXY=%PROXY%"

for %%I in ("%ORIG%") do set "HERE=%%~dpI"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
set "BASE=%HERE%"
if exist "%HERE%\app.py" if exist "%HERE%\backend\main.py" for %%I in ("%HERE%\..") do set "BASE=%%~fI"
rem  the virtual environment stays out of Documents (which OneDrive may sync)
set "VENV=%LOCALAPPDATA%\ifrs9_app\venv"
set "VPY=%VENV%\Scripts\python.exe"
set "LOGS=%BASE%\launcher_logs"
if not exist "%LOGS%" mkdir "%LOGS%"
set "ZIPBRANCH=%BRANCH:/=-%"

echo.
echo  IFRS 9 app
echo  Folder: %BASE%
echo.

rem ---- 1. the code ----------------------------------------------------------
set "HAVE_GIT=0"
where git >nul 2>&1 && set "HAVE_GIT=1"
call :get_repo "%ENGINE%"
if errorlevel 1 goto failed
call :get_repo "%APP%"
if errorlevel 1 goto failed
rem  a copy of this file kept outside the repository follows the repository's
if /i not "%ORIG%"=="%BASE%\%APP%\start_ifrs9.bat" if exist "%BASE%\%APP%\start_ifrs9.bat" copy /y "%BASE%\%APP%\start_ifrs9.bat" "%ORIG%" >nul

rem ---- 2. Python and the virtual environment --------------------------------
if exist "%VPY%" goto have_venv
call :find_python
if not defined PY call :install_python
if not defined PY goto no_python
echo  Creating the virtual environment with %PY%
"%PY%" -m venv "%VENV%"
if not exist "%VPY%" goto no_venv
:have_venv

rem ---- 3. the requirements (only when they changed) -------------------------
set "NEED=0"
set "STAMP=%VENV%\ifrs9_requirements"
if not exist "%STAMP%" mkdir "%STAMP%"
> "%STAMP%\folder_now.txt" echo %BASE%
fc /b "%STAMP%\folder_now.txt" "%STAMP%\folder.txt" >nul 2>&1 || set "NEED=1"
fc /b "%BASE%\%ENGINE%\pyproject.toml" "%STAMP%\engine.toml" >nul 2>&1 || set "NEED=1"
fc /b "%BASE%\%APP%\pyproject.toml" "%STAMP%\app.toml" >nul 2>&1 || set "NEED=1"
"%VPY%" -c "import ifrs9qdb, streamlit, fastapi, uvicorn, openpyxl, scipy, st_aggrid" >nul 2>&1 || set "NEED=1"
if "%NEED%"=="0" goto requirements_ok
echo  Installing the requirements (a few minutes the first time)...
"%VPY%" -m pip install --upgrade pip > "%LOGS%\install.log" 2>&1
"%VPY%" -m pip install -e "%BASE%\%ENGINE%[excel]" -e "%BASE%\%APP%" >> "%LOGS%\install.log" 2>&1
if errorlevel 1 goto install_failed
copy /y "%BASE%\%ENGINE%\pyproject.toml" "%STAMP%\engine.toml" >nul
copy /y "%BASE%\%APP%\pyproject.toml" "%STAMP%\app.toml" >nul
copy /y "%STAMP%\folder_now.txt" "%STAMP%\folder.txt" >nul
:requirements_ok
echo  Requirements: up to date

rem ---- 4. restart the app ---------------------------------------------------
call :stop_port %BACKEND_PORT%
call :stop_port %FRONTEND_PORT%
echo  Starting the backend on port %BACKEND_PORT% and the interface on port %FRONTEND_PORT%
start "IFRS9 backend" /min /D "%BASE%\%APP%" cmd /c ""%VPY%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% > "%LOGS%\backend.log" 2>&1"
start "IFRS9 interface" /min /D "%BASE%\%APP%" cmd /c ""%VPY%" -m streamlit run app.py --server.port %FRONTEND_PORT% --server.headless true --browser.gatherUsageStats false > "%LOGS%\interface.log" 2>&1"

set /a TRIES=0
:wait_backend
set /a TRIES+=1
curl.exe -sf "http://127.0.0.1:%BACKEND_PORT%/api/health" >nul 2>&1 && goto wait_interface
if %TRIES% GEQ 90 goto start_failed
timeout /t 2 /nobreak >nul
goto wait_backend
:wait_interface
curl.exe -sf "http://127.0.0.1:%FRONTEND_PORT%/_stcore/health" >nul 2>&1 && goto started
set /a TRIES+=1
if %TRIES% GEQ 120 goto start_failed
timeout /t 2 /nobreak >nul
goto wait_interface

:started
start "" "http://localhost:%FRONTEND_PORT%"
echo.
echo  The app is running: http://localhost:%FRONTEND_PORT%
echo  It runs in two minimized windows (IFRS9 backend, IFRS9 interface).
echo  To stop it, close those windows. To update and restart, run this file again.
echo  Logs: %LOGS%
echo.
timeout /t 10 >nul
exit /b 0

rem ===========================================================================
rem  subroutines
rem ===========================================================================

:get_repo
rem  %1 = repository folder name. A git clone is pulled; a folder without git
rem  is refreshed from the branch's zip, keeping the user's data.
set "REPO=%~1"
set "DEST=%BASE%\%REPO%"
if exist "%DEST%\.git" goto get_repo_pull
if not exist "%DEST%" if "%HAVE_GIT%"=="1" goto get_repo_clone
goto get_repo_zip

:get_repo_clone
echo  Downloading %REPO% (git clone)
git clone --branch "%BRANCH%" "%GH%/%REPO%.git" "%DEST%"
if errorlevel 1 goto get_repo_zip
exit /b 0

:get_repo_pull
if "%HAVE_GIT%"=="0" goto get_repo_zip
echo  Updating %REPO% (git)
git -C "%DEST%" fetch origin "%BRANCH%" >nul 2>&1
if errorlevel 1 goto get_repo_offline
git -C "%DEST%" checkout "%BRANCH%" >nul 2>&1
git -C "%DEST%" merge --ff-only "origin/%BRANCH%" >nul 2>&1
if errorlevel 1 goto get_repo_blocked
exit /b 0

:get_repo_blocked
echo  ! %REPO% was not updated: files changed on this computer are also changed
echo    in the new code. The app starts with the current code. Files changed here:
git -C "%DEST%" status --short
exit /b 0

:get_repo_offline
echo  ! %REPO%: GitHub could not be reached. The app starts with the current code.
exit /b 0

:get_repo_zip
echo  Downloading %REPO% (zip)
set "TMPD=%TEMP%\ifrs9_%REPO%_%RANDOM%"
mkdir "%TMPD%" >nul 2>&1
curl.exe -sSfL -o "%TMPD%\code.zip" "%GH%/%REPO%/archive/refs/heads/%BRANCH%.zip"
if errorlevel 1 goto get_repo_zip_failed
tar -xf "%TMPD%\code.zip" -C "%TMPD%"
if errorlevel 1 goto get_repo_zip_failed
set "SRC=%TMPD%\%REPO%-%ZIPBRANCH%"
if not exist "%SRC%" goto get_repo_zip_failed
if exist "%DEST%" goto get_repo_zip_update
robocopy "%SRC%" "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
goto get_repo_zip_done
:get_repo_zip_update
rem  the code only: the configuration and everything a run writes stay as they are
robocopy "%SRC%" "%DEST%" /E /NFL /NDL /NJH /NJS /NP /XF config.yml /XD "%SRC%\config" "%SRC%\data-raw" "%SRC%\runs" "%SRC%\config_snapshots" "%SRC%\macro_store" "%SRC%\logs" "%SRC%\calculator_versions" "%SRC%\scenarios" "%SRC%\input" "%SRC%\output" "%SRC%\uploads" "%SRC%\drops" "%SRC%\data" >nul
rem  new default files only: a configuration file edited here is kept
if exist "%SRC%\config" robocopy "%SRC%\config" "%DEST%\config" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if exist "%SRC%\data-raw" robocopy "%SRC%\data-raw" "%DEST%\data-raw" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if exist "%SRC%\config.yml" if not exist "%DEST%\config.yml" copy /y "%SRC%\config.yml" "%DEST%\config.yml" >nul
:get_repo_zip_done
rmdir /s /q "%TMPD%" >nul 2>&1
exit /b 0

:get_repo_zip_failed
rmdir /s /q "%TMPD%" >nul 2>&1
if not exist "%DEST%" goto get_repo_missing
echo  ! %REPO%: the download failed. The app starts with the current code.
exit /b 0
:get_repo_missing
echo  ! %REPO%: the download failed and there is no copy on this computer.
exit /b 1

:find_python
rem  A Python 3.10 or later: the py launcher, Python on the PATH, the usual
rem  install folders, Anaconda.
set "PY="
for %%V in (3.12 3.13 3.11 3.10 3) do for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%P"
if defined PY exit /b 0
for /f "delims=" %%P in ('where python 2^>nul') do call :try_python "%%P"
if defined PY exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try_python "%%D\python.exe"
if defined PY exit /b 0
for %%P in ("%USERPROFILE%\anaconda3\python.exe" "%USERPROFILE%\miniconda3\python.exe" "%LOCALAPPDATA%\anaconda3\python.exe" "C:\ProgramData\anaconda3\python.exe" "C:\ProgramData\miniconda3\python.exe") do call :try_python "%%~P"
exit /b 0

:try_python
if defined PY exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0

:install_python
echo  No Python 3.10 or later found: installing Python %PY_VERSION% for this user
set "PYEXE=%TEMP%\python-%PY_VERSION%-amd64.exe"
curl.exe -sSfL -o "%PYEXE%" "https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
if errorlevel 1 exit /b 0
set "PYDIR=%LOCALAPPDATA%\Programs\Python\Python%PY_VERSION:~0,1%%PY_VERSION:~2,2%"
start "" /wait "%PYEXE%" /quiet InstallAllUsers=0 PrependPath=0 Include_test=0 Include_launcher=0 TargetDir="%PYDIR%"
del "%PYEXE%" >nul 2>&1
call :try_python "%PYDIR%\python.exe"
exit /b 0

:stop_port
rem  %1 = port. Stops whatever is listening on it (the previous run of the app).
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%1 .*LISTENING"') do taskkill /f /pid %%P >nul 2>&1
exit /b 0

rem ---- failures ---------------------------------------------------------------
:no_python
echo  ! Python could not be found or installed. Install Python 3.12 from
echo    https://www.python.org/downloads/ and run this file again.
goto failed
:no_venv
echo  ! The virtual environment could not be created in %VENV%.
goto failed
:install_failed
echo  ! Installing the requirements failed. The details are in %LOGS%\install.log
echo    Behind a proxy, set PROXY at the top of this file and run it again.
goto failed
:start_failed
echo  ! The app did not start. The details are in %LOGS%\backend.log and
echo    %LOGS%\interface.log
goto failed
:failed
echo.
pause
exit /b 1
