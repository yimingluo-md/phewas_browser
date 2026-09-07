@echo off
rem IEI PheWAS Browser - Windows launcher (self-contained, no installation needed)
setlocal
cd /d "%~dp0"
set URL=http://localhost:8555
set HEALTH_URL=%URL%/api/health
set STATE_DIR=%LOCALAPPDATA%\IEI PheWAS Browser
set IEI_PYTHON=%~dp0windows\python\python.exe
set IEI_ROOT=%~dp0
set IEI_PID_FILE=%STATE_DIR%\server.pid

rem Already running? Verify that it is this application, not another service.
curl -s --fail --max-time 2 %HEALTH_URL% 2>NUL | findstr /C:"IEI PheWAS Browser" >NUL
if %errorlevel%==0 goto open

curl -s -o NUL --max-time 2 %URL% >NUL 2>&1
if %errorlevel%==0 (
    echo Another application is already using network port 8555.
    echo Close that application, then try again.
    pause
    exit /b 1
)

if not exist "windows\python\python.exe" (
    echo The bundled Windows Python runtime is missing ^(windows\python\^).
    echo Please re-extract the full folder from the zip and try again.
    pause
    exit /b 1
)

echo Starting the IEI PheWAS Browser server...
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
powershell -NoProfile -Command ^
    "$p = Start-Process -FilePath $env:IEI_PYTHON -ArgumentList '-I','-m','uvicorn','app:app','--host','127.0.0.1','--port','8555' -WorkingDirectory $env:IEI_ROOT -WindowStyle Minimized -PassThru; Set-Content -LiteralPath $env:IEI_PID_FILE -Value $p.Id"
if %errorlevel% neq 0 (
    echo The local browser process could not be started.
    pause
    exit /b 1
)

set /a tries=0
:wait
curl -s --fail --max-time 2 %HEALTH_URL% 2>NUL | findstr /C:"IEI PheWAS Browser" >NUL
if %errorlevel%==0 goto open
set /a tries+=1
if %tries% geq 30 goto failed
timeout /t 1 /nobreak >NUL
goto wait

:open
start "" %URL%
exit /b 0

:failed
echo.
echo The server did not start. Check the minimized "IEI PheWAS Browser server"
echo window for the error message.
pause
exit /b 1
