@echo off
REM 퀀트 라이브 스크리너 실행 스크립트 (Windows)
setlocal
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

cd /d "%~dp0"
echo ============================================
echo   퀀트 라이브 스크리너 시작
echo   브라우저가 자동으로 열립니다 (http://localhost:8501)
echo   종료하려면 이 창에서 Ctrl+C
echo ============================================
"%PY%" -m streamlit run app.py
endlocal
