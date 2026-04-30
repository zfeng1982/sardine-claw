@echo off
:: 强制停止残留的 daemon 进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8766" ^| findstr "LISTENING"') do (
    echo Stopping residual daemon PID: %%a
    taskkill /PID %%a /F 2>nul
)

:: 等待端口释放
timeout /t 2 >nul

:: 启动 qqbrowser-skill
qqbrowser-skill %*