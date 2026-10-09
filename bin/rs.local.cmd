@echo off
setlocal
set "HERE=%~dp0"
pushd "%HERE%\.." >nul
set "ROOT=%CD%"
popd >nul
set "RT=%ROOT%\.venv\Scripts\rt.exe"
if not exist "%RT%" (
  echo resume-tailor: %RT% is missing.
  echo From the project folder, create .venv and run: python -m pip install -e .
  exit /b 127
)
set "RESUME_TAILOR_ROOT=%ROOT%"
"%RT%" open %*
