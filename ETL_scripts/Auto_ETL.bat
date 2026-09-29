@echo off
REM Olist ETL: Raw_data CSV -> DB\olist.duckdb
REM Runs every step in order and stops at the first failure.
REM The production DB is only replaced after all quality checks pass.
setlocal

cd /d "%~dp0"

REM Prefer the project virtual environment when present
set "PYTHON=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PYTHON=%~dp0..\.venv\Scripts\python.exe"

echo ============================================================
echo  Olist ETL started %date% %time%
echo  Python: %PYTHON%
echo ============================================================

for %%S in (
    01_validate_raw.py
    02_load_raw.py
    03_build_derived.py
    04_quality_check.py
    05_publish.py
) do (
    echo.
    echo ---- Running %%S ----
    "%PYTHON%" "%%S"
    if errorlevel 1 (
        echo.
        echo [ERROR] %%S failed. Pipeline aborted; production DB left unchanged.
        echo         See ETL_scripts\logs\etl.log for details.
        endlocal
        exit /b 1
    )
)

echo.
echo ============================================================
echo  Olist ETL finished successfully %date% %time%
echo ============================================================
endlocal
exit /b 0
