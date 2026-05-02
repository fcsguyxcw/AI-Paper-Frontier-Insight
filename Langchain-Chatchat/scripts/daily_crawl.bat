@echo off
REM arXiv Paper Daily Crawl - scheduled via Windows Task Scheduler
REM 配置方法：taskschd.msc → 创建任务 → 触发器每日 → 操作=运行此bat

set CHATCHAT_ROOT=D:\MyProject\chatchat_data
set PATH=D:\MyProject\Langchain-Chatchat\libs\chatchat-server\.venv\Scripts;%PATH%
set LOG_DIR=D:\MyProject\Langchain-Chatchat\logs
set LOG_FILE=%LOG_DIR%\crawl.log

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d D:\MyProject\Langchain-Chatchat\libs\chatchat-server

echo [%date% %time%] Crawl started >> "%LOG_FILE%"
python -c "from chatchat.crawlers.pipeline import ArxivPipeline; ArxivPipeline().run()" >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%date% %time%] Crawl FAILED with exit code %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)
echo [%date% %time%] Crawl completed >> "%LOG_FILE%"
exit /b 0
