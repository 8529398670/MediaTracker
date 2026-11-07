@echo off
rem Print a one-time login link -- by default for user 1, the owner -- for
rem whichever deployment of this checkout is actually live. The Windows twin
rem of scripts/login.sh.
rem
rem   scripts\login.bat               the owner (user 1)
rem   scripts\login.bat 3             user 3
rem   scripts\login.bat --docker      the docker container, even if a local
rem                                   server is running too
rem   scripts\login.bat --local       this checkout's local database
rem
rem Where the link comes from: the local server (scripts\run.bat) when it is
rem running, otherwise the docker container (docker/run.sh) when it is running,
rem otherwise the local database directly, offline -- the link waits there
rem until the server is started. The two keep separate databases, so a link
rem from one does nothing in the other. This says which one it used.
setlocal
cd /d "%~dp0.."


set "USER_ID=1"
set "MODE=auto"
:args
if "%~1"=="" goto args_done
if /i "%~1"=="--docker" (set "MODE=docker" & shift & goto args)
if /i "%~1"=="--local" (set "MODE=local" & shift & goto args)
echo %~1| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo ERROR: expected a numeric user id, --docker or --local; got "%~1".
  exit /b 1
)
set "USER_ID=%~1"
shift
goto args
:args_done

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if exist "%PYTHON%" goto have_venv
echo ERROR: there is no .venv yet. Run scripts\run.bat first: it creates one,
echo        writes config\config.yaml, and the first start prints the owner's link.
exit /b 1
:have_venv

set "config_file="
for /f "usebackq tokens=1,* delims==" %%a in (`"%PYTHON%" -m app config shell --format bat server`) do set "%%a=%%b"
if not defined config_file exit /b 1
for /f "usebackq tokens=1,* delims==" %%a in (`"%PYTHON%" -m app config shell --format bat docker`) do set "%%a=%%b"

if "%config_exists%"=="true" goto have_config
echo ERROR: no config yet -- %config_file% does not exist.
echo        Run scripts\run.bat first: it writes one, and the first start prints
echo        the owner's login link.
exit /b 1
:have_config

rem Is this checkout's server running? This venv's python running -m app --
rem the same test scripts\run.bat stops it by.
set "RUN_EXE=%PYTHON%"
set "LOCAL_PID="
for /f "delims=" %%p in ('powershell -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $env:RUN_EXE -and $_.CommandLine -match '\s-m\s+app\s*$' })[0].ProcessId" 2^>nul') do set "LOCAL_PID=%%p"

set "DOCKER_UP=false"
where docker >nul 2>&1
if errorlevel 1 goto docker_checked
for /f "delims=" %%n in ('docker ps --filter "name=^%docker_container%$" --format "{{.Names}}" 2^>nul') do set "DOCKER_UP=true"
:docker_checked

if not "%MODE%"=="auto" goto mode_chosen
set "MODE=local"
if defined LOCAL_PID goto auto_local
if "%DOCKER_UP%"=="true" set "MODE=docker"
goto mode_chosen
:auto_local
if not "%DOCKER_UP%"=="true" goto mode_chosen
echo Note: the %docker_container% container is running too. It has its own database;
echo       this link is for the local server. Use --docker for the container.
echo.
:mode_chosen

if not "%MODE%"=="docker" goto local
if "%DOCKER_UP%"=="true" goto docker_up
echo ERROR: the %docker_container% container is not running.
echo        Start it with docker/run.sh, or see why it stopped: docker logs %docker_container%
exit /b 1
:docker_up
echo Docker container %docker_container%, served at %docker_url%
echo.
docker exec %docker_container% python -m app manage reissue-login --user-id %USER_ID%
if not errorlevel 1 exit /b 0
echo.
echo Accounts in the container: docker exec %docker_container% python -m app manage list-users
exit /b 1

:local
if exist "%database%" goto have_database
echo ERROR: there is no database yet at %database%.
echo        Start the server with scripts\run.bat -- its first start creates the owner
echo        and prints their login link.
exit /b 1
:have_database
if defined LOCAL_PID echo Local server (pid %LOCAL_PID%), served at %url%
if not defined LOCAL_PID echo No server is running for this checkout, so the link goes straight into
if not defined LOCAL_PID echo the database. It works once you start it: scripts\run.bat
echo   database %database%
echo.
"%PYTHON%" -m app manage reissue-login --user-id %USER_ID%
if not errorlevel 1 exit /b 0
echo.
echo Accounts in this database: scripts\run.bat manage list-users
exit /b 1
