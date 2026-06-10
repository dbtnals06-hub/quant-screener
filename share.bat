@echo off
chcp 65001 >nul
REM ── 퀀트 스크리너 외부 공유 (Cloudflare 임시 터널) ──
setlocal
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
set CF=%LOCALAPPDATA%\cloudflared\cloudflared.exe
cd /d "%~dp0"

REM cloudflared 없으면 다운로드 (설치/관리자 권한 불필요)
if not exist "%CF%" (
  echo [준비] cloudflared 다운로드 중...
  if not exist "%LOCALAPPDATA%\cloudflared" mkdir "%LOCALAPPDATA%\cloudflared"
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF%' -UseBasicParsing"
)

echo [1/2] Streamlit 서버 시작 (포트 8501)...
start "Quant Screener Server" "%PY%" -m streamlit run app.py --server.port 8501

echo      서버 기동 대기...
powershell -NoProfile -Command "for($i=0;$i -lt 40;$i++){try{if((Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){break}}catch{};Start-Sleep -Milliseconds 1000}"

echo.
echo [2/2] Cloudflare 공개 터널 시작...
echo      ↓↓↓ 아래에 나오는 https://....trycloudflare.com 주소를 다른 사람에게 보내세요 ↓↓↓
echo      (이 창을 닫으면 링크가 끊깁니다. 종료: Ctrl+C)
echo      ※ 이 네트워크는 UDP가 막혀 있어 http2(TCP)로 연결합니다.
echo.
"%CF%" tunnel --url http://localhost:8501 --protocol http2
endlocal
