@echo off
rem 切到 UTF-8 代码页，否则中文与 emoji 输出会变成乱码
chcp 65001 >nul
setlocal

cd /d "%~dp0"

:menu
cls
echo ========================================
echo  Product Tracker - 产品发现平台追踪器
echo ========================================
echo.
echo  1. 采集数据并生成报告
echo  2. 采集数据、生成报告并打开
echo  3. 启动定时任务
echo  4. 用已有数据重新生成报告
echo  5. 查看状态
echo  6. 清理过期数据
echo  7. 安装/更新依赖
echo  0. 退出
echo.

set "choice="
set /p choice="请输入选择 (0-7): "

if "%choice%"=="1" (
    python main.py run --format html json markdown
) else if "%choice%"=="2" (
    python main.py run --format html json markdown --open
) else if "%choice%"=="3" (
    echo 定时任务已启动，按 Ctrl+C 停止。
    python main.py schedule
) else if "%choice%"=="4" (
    python main.py report --format html markdown --open
) else if "%choice%"=="5" (
    python main.py status
) else if "%choice%"=="6" (
    python main.py clean
) else if "%choice%"=="7" (
    python -m pip install -r requirements.txt
) else if "%choice%"=="0" (
    goto :eof
) else (
    echo 无效选择！
)

echo.
pause
goto menu
