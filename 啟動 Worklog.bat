@echo off
rem 雙擊啟動 Worklog。用 pythonw 執行，不會留下終端機視窗。
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "launch.pyw"
