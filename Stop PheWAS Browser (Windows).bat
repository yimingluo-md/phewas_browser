@echo off
rem Stop only the IEI PheWAS Browser process recorded by the launcher.
setlocal
set STATE_DIR=%LOCALAPPDATA%\IEI PheWAS Browser
set IEI_PID_FILE=%STATE_DIR%\server.pid
set IEI_PYTHON=%~dp0windows\python\python.exe

if not exist "%IEI_PID_FILE%" goto not_running
set /p IEI_SERVER_PID=<"%IEI_PID_FILE%"

powershell -NoProfile -Command ^
    "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:IEI_SERVER_PID) -ErrorAction SilentlyContinue; if ($p -and $p.ExecutablePath -eq $env:IEI_PYTHON -and $p.CommandLine -like '*uvicorn app:app*') { Stop-Process -Id $p.ProcessId; exit 0 } else { exit 1 }"
if %errorlevel% neq 0 goto not_running

del /q "%IEI_PID_FILE%" >NUL 2>&1
echo IEI PheWAS Browser stopped.
timeout /t 1 >NUL
exit /b 0

:not_running
del /q "%IEI_PID_FILE%" >NUL 2>&1
echo IEI PheWAS Browser is not running.
timeout /t 1 >NUL
