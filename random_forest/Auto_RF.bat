@echo off
REM Random forest segmentation: features -> seller / customer segments -> pairing overlap
REM -> activity cut-off -> active customer segments -> active vs one-time review / spend
REM -> active vs one-time geography
REM Requires DB\olist.duckdb (run ETL_scripts\Auto_ETL.bat first).
setlocal

cd /d "%~dp0scripts"

set "PYTHON=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PYTHON=%~dp0..\.venv\Scripts\python.exe"

for %%S in (
    01_build_features.py
    02_cluster.py
    03_overlap.py
    04_activity_cutoff.py
    05_active_segments.py
    06_active_vs_one_time.py
    07_activity_geography.py
) do (
    echo.
    echo ---- Running %%S ----
    "%PYTHON%" "%%S"
    if errorlevel 1 (
        echo.
        echo [ERROR] %%S failed. Pipeline aborted.
        endlocal
        exit /b 1
    )
)

echo.
echo Random forest segmentation finished.
endlocal
exit /b 0
