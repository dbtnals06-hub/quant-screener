@echo off
chcp 65001 >nul
REM 퀀트 라이브 스크리너 실행 (Windows) — 로컬에서 브라우저까지 자동으로 열기
setlocal
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
cd /d "%~dp0"

echo ============================================
echo   퀀트 라이브 스크리너 시작 (http://localhost:8501)
echo   종료: 새로 열리는 'Quant Screener' 창에서 Ctrl+C
echo ============================================

REM Streamlit 서버를 별도 창에서 실행(config.toml headless=true 라 자동으로 안 열림)
start "Quant Screener" "%PY%" -m streamlit run app.py --server.port 8501

echo 서버 기동 대기 중...
powershell -NoProfile -Command "for($i=0;$i -lt 40;$i++){try{if((Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){break}}catch{};Start-Sleep -Milliseconds 1000}"

REM 기본 브라우저로 앱 열기
start "" http://localhost:8501
echo 브라우저를 열었습니다. (안 열리면 주소창에 localhost:8501 직접 입력)
endlocal
