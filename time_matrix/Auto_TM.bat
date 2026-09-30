@echo off
REM Weekday x hour analysis: matrices -> k selection -> time segments -> correlation and stability -> golden hours
REM Requires DB\olist.duckdb (run ETL_scripts\Auto_ETL.bat first).
setlocal

cd /d "%~dp0scripts"

set "PYTHON=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PYTHON=%~dp0..\.venv\Scripts\python.exe"

for %%S in (
    01_time_matrix.py
    02_k_selection.py
    03_time_clusters.py
    04_time_correlation_stability.py
    05_golden_hours.py
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
echo Time matrix analysis finished.
endlocal
exit /b 0
