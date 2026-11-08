@echo off
rem Set up the venv and run the server from this checkout, outside Docker. The
rem Windows twin of run.sh: same commands, same behavior, except where noted.
rem
rem   scripts\run.bat                    create/update .venv if needed, stop the copy
rem                              this checkout started last, start a fresh one
rem   scripts\run.bat stop               stop the copy this checkout started (in
rem                              this window, another, or the hidden one
rem                              scripts\login.bat --background starts)
rem   scripts\run.bat manage <command>   run an admin command against it (see below)
rem   scripts\run.bat <anything else>    same: passed straight to `python -m app`
rem
rem The server runs in the foreground: its log streams here and Ctrl-C stops it.
rem Running scripts\run.bat again from another window stops this one and takes over,
rem so "edit, scripts\run.bat, reload the page" is the whole loop.
rem
rem With arguments it is a one-off instead -- the same venv, then `python -m
rem app` with those arguments -- and the running server is left alone. `manage`
rem opens the database directly, which SQLite's WAL mode makes safe alongside
rem the live server.
rem
rem   scripts\run.bat manage list-users
rem   scripts\login.bat                           the owner's login link
rem   scripts\run.bat manage create-login --name "Grace" --role user
rem   scripts\run.bat manage create-invite --user-id 1 --label "Book club"
rem   scripts\run.bat manage create-key --user-id 1 --name "CI"
rem   scripts\run.bat manage paths                        where the state lives
rem   scripts\run.bat config check
rem   scripts\run.bat version
rem
rem Where it differs from run.sh, Windows forces it:
rem
rem   - There is no pid file. The old server is whatever process is running
rem     this checkout's .venv\Scripts\python.exe with exactly "-m app", which a
rem     full path pins down, so a stale pid can never point at something else.
rem   - Windows cannot send SIGTERM to another console's process, so the old
rem     server is killed rather than drained. SQLite's WAL survives that.
rem   - app\requirements.txt is reinstalled when its contents differ from the copy
rem     saved after the last install, rather than when it is newer: batch has
rem     no way to compare file times.
rem
rem This is for development and internal boxes. It is a plain process with your
rem permissions -- none of docker\run.sh's read-only filesystem, dropped
rem capabilities, or pid and memory limits apply -- so use Docker for anything
rem long-lived or internet-facing.
setlocal
cd /d "%~dp0.."


set "VENV=%CD%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
rem The app\requirements.txt that was last installed successfully. Any edit to the
rem real one makes them differ, which is the signal to install again.
set "STAMP=%VENV%\.requirements.stamp"

if /i not "%~1"=="stop" goto not_stop
if not "%~2"=="" goto not_stop
rem The same stop as :stop_old below, when there is nothing to start after it.
set "RUN_PYTHON=%PYTHON%"
powershell -NoProfile -Command "$all = @(Get-CimInstance Win32_Process); $old = @($all | Where-Object { $_.ExecutablePath -eq $env:RUN_PYTHON -and $_.CommandLine -match '\s-m\s+app\s*$' }); if (-not $old) { Write-Host 'No server started by this checkout is running.'; exit }; $ids = @($old.ProcessId) + @($all | Where-Object { $old.ProcessId -contains $_.ParentProcessId } | ForEach-Object { $_.ProcessId }); foreach ($p in $old) { Write-Host ('Stopping the server this checkout started (pid ' + $p.ProcessId + ', running since ' + $p.CreationDate + ')...'); taskkill.exe /T /F /PID $p.ProcessId | Out-Null }; foreach ($id in $ids) { Wait-Process -Id $id -Timeout 15 -ErrorAction SilentlyContinue }; Write-Host 'Stopped.'"
exit /b 0
:not_stop

rem The venv's own python is called by path rather than activating the venv:
rem it finds its packages either way, and nothing here depends on PATH.
rem
rem All of this happens before anything is stopped, so a failed install leaves
rem the server that was already running untouched.
rem
rem A venv whose creation was interrupted has a python but no pip, and would
rem fail every install from then on; --clear rebuilds it from scratch.
set "CREATE="
if not exist "%PYTHON%" set "CREATE=1"
if not defined CREATE if not exist "%STAMP%" "%PYTHON%" -m pip --version >nul 2>&1 || set "CREATE=1"
if not defined CREATE goto venv_ready

rem The py launcher first: on a fresh Windows, `python` on PATH is often the
rem Microsoft Store stub, which opens the Store instead of running anything.
set "BASE_PYTHON="
where py >nul 2>&1 && set "BASE_PYTHON=py -3"
if not defined BASE_PYTHON where python >nul 2>&1 && set "BASE_PYTHON=python"
if defined BASE_PYTHON goto create_venv
echo No Python found. Install Python 3 from https://www.python.org/downloads/
echo (it comes with the py launcher) and run scripts\run.bat again.
exit /b 1

:create_venv
echo Creating .venv...
%BASE_PYTHON% -m venv --clear "%VENV%"
if errorlevel 1 exit /b 1

:venv_ready
fc /b app\requirements.txt "%STAMP%" >nul 2>&1
if not errorlevel 1 goto requirements_ready
echo Installing app\requirements.txt into .venv...
"%PYTHON%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto install_failed
"%PYTHON%" -m pip install --quiet -r app\requirements.txt
if errorlevel 1 goto install_failed
copy /y app\requirements.txt "%STAMP%" >nul

:requirements_ready
if "%~1"=="" goto server
"%PYTHON%" -m app %*
exit /b %errorlevel%

:server
call :read_config
if not defined config_file exit /b 1

rem First run on this checkout: config\config.yaml is gitignored, so a fresh
rem clone has none. Without one here the app would quietly create
rem %USERPROFILE%\.config\media-tracker\config.yaml instead, which is not the
rem file this checkout's docker\run.sh reads. Write it here and stop, like
rem docker\run.sh, so it gets looked at before the first start.
if "%config_exists%"=="true" goto migrate
"%PYTHON%" -m app config init --file .\config\config.yaml >nul
if errorlevel 1 exit /b 1
call :read_config
echo First run: wrote %config_file%
echo   and %secret_file%
echo   (secret.key holds a new key -- back it up with the database; it is the
echo   only thing that can read it).
echo.
echo It will serve %url%
echo   (from %url_source%).
if not "%secure_cookies%"=="true" goto first_done
if not "%url:~0,7%"=="http://" goto first_done
call :config_line secure_cookies
echo.
echo server.secure_cookies is true. That is right behind HTTPS, but at %url%
echo the browser drops a Secure cookie and signing in silently does nothing.
echo For local use, change line %LINE% of %config_file%:
echo.
echo     secure_cookies: true   -^>   secure_cookies: false
:first_done
echo.
echo Most settings can be changed later while the server runs, from the owner's
echo Settings screen or by editing config.yaml. Then run scripts\run.bat again.
exit /b 0

:migrate
rem A config.yaml from before secret.key existed has the key inside it. Move it
rem out now, before anything starts, so the window says so. Silent otherwise.
"%PYTHON%" -m app config migrate --file .\config\config.yaml
if errorlevel 1 exit /b 1
call :read_config
if "%secret_exists%"=="true" goto stop_old
if not "%database_exists%"=="true" goto stop_old
echo ERROR: %secret_file% is missing, and %database% exists.
echo        Restore secret.key from your backup: a new key cannot read the database.
exit /b 1

:stop_old
rem Stop the copy this checkout started last. .venv\Scripts\python.exe is a
rem small launcher that starts the real interpreter as its child, so the whole
rem tree goes (taskkill /T), and both are waited for before the port is reused.
rem The path goes to PowerShell through the environment rather than inside the
rem command, so no character in it (a quote in a user name, say) can break the
rem quoting.
set "RUN_PYTHON=%PYTHON%"
powershell -NoProfile -Command "$all = @(Get-CimInstance Win32_Process); $old = @($all | Where-Object { $_.ExecutablePath -eq $env:RUN_PYTHON -and $_.CommandLine -match '\s-m\s+app\s*$' }); $ids = @($old.ProcessId) + @($all | Where-Object { $old.ProcessId -contains $_.ParentProcessId } | ForEach-Object { $_.ProcessId }); foreach ($p in $old) { Write-Host ('Stopping the server this checkout started (pid ' + $p.ProcessId + ', running since ' + $p.CreationDate + ')...'); taskkill.exe /T /F /PID $p.ProcessId | Out-Null }; foreach ($id in $ids) { Wait-Process -Id $id -Timeout 15 -ErrorAction SilentlyContinue }"

rem Anything still on the port is not ours, and uvicorn would only die on
rem "address already in use" after printing a banner that says it started.
set "PORT_OWNER="
for /f "delims=" %%o in ('powershell -NoProfile -Command "$c = Get-NetTCPConnection -State Listen -LocalPort %port% -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; $name = if ($p.Path) { $p.Path } else { $p.ProcessName }; $name + ' (pid ' + $c.OwningProcess + ')' }" 2^>nul') do set "PORT_OWNER=%%o"
if not defined PORT_OWNER goto port_free
call :config_line port
echo ERROR: port %port% (server.port) is already in use by %PORT_OWNER%.
echo.
echo        It is not the server this checkout started. Stop it, or change line
echo        %LINE% of %config_file% to a free port, then re-run.
exit /b 1
:port_free

if not "%secure_cookies%"=="true" goto cookies_ok
if not "%url:~0,7%"=="http://" goto cookies_ok
call :config_line secure_cookies
echo WARNING: server.secure_cookies is true but the URL is %url%.
echo          The browser will drop the session cookie and signing in will silently
echo          do nothing. Set it to false on line %LINE% of %config_file%
echo          for local use, or set server.public_url to the https:// address in front.
echo.
:cookies_ok

set "DB_NOTE=existing"
if not "%database_exists%"=="true" set "DB_NOTE=new -- the owner's first login link is printed below"
set "STATIC_NOTE=%static_dir%  (from disk: frontend edits need only a reload)"
if not "%static_on_disk%"=="true" set "STATIC_NOTE=the bundled copy  (no directory at %static_dir%)"
set "LANGUAGE_NOTE=%language_file%  (from disk)"
if not "%language_on_disk%"=="true" set "LANGUAGE_NOTE=the bundled copy  (no file at %language_file%)"

echo Starting media-tracker from .venv
echo   url       %url%
echo             from %url_source%
echo   config    %config_file%
echo   app dir   %app_dir%
echo   database  %database%  (%DB_NOTE%)
echo   static    %STATIC_NOTE%
echo   language  %LANGUAGE_NOTE%
echo   code      Python changes need scripts\run.bat again; static\ edits only a reload
echo.
echo A login link for the owner any time: scripts\login.bat (from another window).
echo.

rem Say when it is actually answering, not just launched. This runs beside the
rem server in the same window and gives up after 20 seconds.
set "READY_URL=%url%"
start "" /b powershell -NoProfile -Command "for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; & $env:RUN_PYTHON -m app health *> $null; if ($LASTEXITCODE -eq 0) { Write-Host ''; Write-Host ('Ready: ' + $env:READY_URL); Write-Host ''; exit } }; Write-Host ''; Write-Host ('Not answering on port ' + $env:port + ' after 20 seconds -- see the log above.')"

"%PYTHON%" -m app
exit /b %errorlevel%

:install_failed
echo.
echo ERROR: installing app\requirements.txt failed (above). Nothing was stopped or started.
exit /b 1

rem ---------------------------------------------------------------------------
rem read_config sets every value `config shell server` prints (config_file,
rem app_dir, database, url, port, ...), resolved by the app exactly the way
rem the server resolves them -- nothing here parses YAML.
:read_config
set "config_file="
for /f "usebackq tokens=1,* delims==" %%a in (`"%PYTHON%" -m app config shell --format bat server`) do set "%%a=%%b"
if defined config_file exit /b 0
echo.
echo ERROR: the config above does not validate. Fix it and re-run.
exit /b 1

rem config_line KEY sets LINE to that key's line number in config.yaml.
:config_line
set "LINE=?"
for /f "tokens=1 delims=:" %%n in ('findstr /n /r /c:"^ *%1:" "%config_file%"') do (
  set "LINE=%%n"
  exit /b 0
)
exit /b 0
