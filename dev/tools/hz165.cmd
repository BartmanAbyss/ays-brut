@echo off
rem All displays back to 165 Hz. 165.08 exactly, which is what
rem QueryDisplayConfig reports as vSyncFreq 165080/1000 - asking for a round
rem 165.000 only works because the OS falls back to a nearest match.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Set-RefreshRate.ps1" 165.08
timeout /t 3 /nobreak >nul
