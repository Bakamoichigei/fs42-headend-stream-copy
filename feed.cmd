@echo off
rem feed.cmd - run prevue_feed.py on Windows without fighting PATH.
rem   feed --demo --port 1234 --once
rem   feed --listings confs\examples\prevue_listings.json --port 1234 --once
rem Finds the real Python (the 3.14+ install managers copy first, then py, then python)
rem and passes -E so a stray PYTHONPATH from another program (e.g. SVP 4) is ignored.
setlocal
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY for %%P in (py.exe) do if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"
if not defined PY set "PY=python"
"%PY%" -E "%~dp0prevue_feed.py" %*
exit /b %ERRORLEVEL%
