@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ========================================
echo   ChatWithLuotianyi 文件校验工具
echo ========================================
echo.

:: 设置要校验的文件名
set "FILENAME=ChatWithLuotianyi_Portable_126.zip"

:: 检查文件是否存在
if not exist "%FILENAME%" (
    echo [错误] 找不到文件: %FILENAME%
    echo 请将此脚本放在与 %FILENAME% 相同的目录下运行。
    echo.
    pause
    exit /b 1
)

echo 正在计算文件哈希值，请稍候...
echo.

:: 使用 certutil 计算 MD5
certutil -hashfile "%FILENAME%" MD5 > temp_md5.txt 2>nul

if %ERRORLEVEL% NEQ 0 (
    echo [错误] 无法计算文件哈希值
    del temp_md5.txt 2>nul
    pause
    exit /b 1
)

:: 从 certutil 输出中提取 MD5 值（第二行）
set /p line1=<temp_md5.txt
set "line2="
for /f "skip=1 tokens=*" %%a in (temp_md5.txt) do (
    if not defined line2 set "line2=%%a"
)

:: 移除空格
set "CALCULATED_MD5=!line2: =!"

:: 删除临时文件
del temp_md5.txt

:: 显示计算结果
echo 文件名: %FILENAME%
echo MD5:    !CALCULATED_MD5!
echo.

set "EXPECTED_MD5=e86c6f652a0bf709a8b482a50309f795"

if "!EXPECTED_MD5!"=="YOUR_MD5_HERE" (
    echo [提示] 这是首次运行，请将上面显示的MD5值复制到脚本中
    echo        的 EXPECTED_MD5 变量处，然后分发给用户使用。
    echo.
) else (
    echo 正在验证...
    echo 预期MD5: !EXPECTED_MD5!
    echo.
    
    if /i "!CALCULATED_MD5!"=="!EXPECTED_MD5!" (
        echo [✓] 校验成功！文件完整无误。
    ) else (
        echo [✗] 校验失败！文件可能已损坏或被篡改。
        echo     请重新下载文件。
    )
    echo.
)

pause
endlocal
