@echo off
chcp 65001 > nul
setlocal

cls
echo.
echo ========================================================
echo             正在检测 NVIDIA 显卡...
echo ========================================================
echo.

:: 检查 nvidia-smi 命令是否存在
where nvidia-smi >nul 2>nul

if %errorlevel% equ 0 (
    :: 成功检测到显卡
    echo.
    echo [检测结果]: 发现 NVIDIA 显卡！
    echo.
    echo --------------------------------------------------------
    echo 显卡型号及显存信息：
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    echo --------------------------------------------------------
    echo.
    echo ********************************************************
    echo *                                                      *
    echo *      恭喜！您的电脑支持 CUDA 加速！                  *
    echo *      这意味着 TTS 生成速度将会有显著提升。           *
    echo *                                                      *
    echo ********************************************************
    echo.
    :: 设置控制台颜色为绿色
    color 0A
) else (
    :: 未检测到显卡
    echo.
    echo [检测结果]: 未找到 NVIDIA 显卡或驱动程序。
    echo.
    echo ********************************************************
    echo *                                                      *
    echo *      注意：未检测到可用显卡。                        *
    echo *      TTS 进程将使用 CPU 运行，速度可能会较慢。       *
    echo *                                                      *
    echo ********************************************************
    echo.
    :: 设置控制台颜色为红色
    color 0C
)

pause
endlocal
