@echo off
rem All displays to a REAL 60 Hz: 59.951, the panel's native non-doubled mode.
rem
rem Not 60.000 - that mode is carried on a 119.9976 Hz signal (frame doubling),
rem so apps get 120 Hz vsync and the intro renders at 120. 59.951 is the only
rem entry whose signal is actually ~60. The rational is exact: it is what
rem QueryDisplayConfig reports as vSyncFreq 59951/1000.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Set-RefreshRate.ps1" 59.951
timeout /t 3 /nobreak >nul
