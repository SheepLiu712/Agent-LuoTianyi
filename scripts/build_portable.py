import os
import shutil
import sys
from pathlib import Path

def ignore_patterns(path, names):
    # 忽略不需要的文件和文件夹
    ignore_list = [
        '__pycache__', 
        '.git', 
        '.vscode', 
        'bin', 
        'build', 
        'dist', 
        'logs', 
        'data', # data 通常包含用户数据，视情况是否包含初始数据
        'scripts',
        'tests',
        '*.spec',
        'build_script.sh',
        'log.txt',
        'ChatWithLuotianyi_Portable' # 防止递归复制自己
    ]
    return set(ignore_list)

def build_portable():
    # 1. 配置路径
    project_root = Path(os.getcwd())
    dist_dir = project_root / "ChatWithLuotianyi_Portable"
    
    # 你的 Conda 环境路径 (根据之前的 log 推断)
    conda_env_path = Path("D:/Anaconda/envs/lty") 
    
    print(f"=== 开始构建便携版 ===")
    print(f"项目根目录: {project_root}")
    print(f"发布目录: {dist_dir}")
    print(f"Conda环境路径: {conda_env_path}")

    # 2. 清理旧的发布目录
    if dist_dir.exists():
        print("清理旧的发布目录...")
        # 注意：如果 python 目录很大，删除可能需要一点时间
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            print(f"清理失败，请手动删除 {dist_dir} 后重试。错误: {e}")
            return

    dist_dir.mkdir(parents=True, exist_ok=True)

    # 3. 复制项目文件
    print("正在复制项目文件...")
    
    # 需要复制的顶层文件/文件夹
    items_to_copy = ['src', 'config', 'res', 'start.py', 'README.md', 'LICENSE']
    
    # 特殊处理 data 目录：只复制必要的结构，不复制大量缓存
    # 如果你需要 data 里的某些初始文件，请手动调整
    data_dir = dist_dir / "data"
    data_dir.mkdir()
    
    for item in items_to_copy:
        src_path = project_root / item
        dst_path = dist_dir / item
        
        if not src_path.exists():
            print(f"警告: {item} 不存在，跳过。")
            continue
            
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(src_path, dst_path)

    # # 4. 复制 Conda 环境
    # print("正在复制 Python 环境 (这可能需要几分钟，请耐心等待)...")
    # dest_env_path = dist_dir / "python"
    
    # try:
    #     # 使用 shutil.copytree 复制整个环境
    #     # 忽略一些不必要的缓存目录以减小体积
    #     shutil.copytree(conda_env_path, dest_env_path, ignore=shutil.ignore_patterns(
    #         'pkgs', # conda 的包缓存，运行时不需要
    #         'conda-meta', # conda 的元数据
    #         '__pycache__',
    #         'pip-cache'
    #     ))
    #     print("Python 环境复制完成。")
    # except Exception as e:
    #     print(f"复制环境失败: {e}")
    #     print("请检查路径是否正确，或者手动将 conda 环境复制到 ChatWithLuotianyi_Portable/python")
    #     return

    # 5. 创建启动脚本 (run.bat)
    print("正在生成启动脚本...")
    bat_content = r"""@echo off
setlocal

:: Get current directory
set "CURRENT_DIR=%~dp0"

:: Set Python environment path
set "PYTHON_HOME=%CURRENT_DIR%python"

:: Set PATH to include Python interpreter and Library\bin (for DLLs)
set "PATH=%PYTHON_HOME%;%PYTHON_HOME%\Library\bin;%PYTHON_HOME%\Scripts;%PATH%"

:: Set PYTHONPATH to ensure src is found
set "PYTHONPATH=%CURRENT_DIR%"

:: Set HF_HOME and other cache paths to local data directory
set "HF_HOME=%CURRENT_DIR%data\huggingface"
set "MPLCONFIGDIR=%CURRENT_DIR%data\matplotlib"

:: Check for SILICONFLOW_API_KEY
if not defined SILICONFLOW_API_KEY (
    echo SILICONFLOW_API_KEY not found. Setting default value.
    set "SILICONFLOW_API_KEY=sk-qpsxidlqseetddysshftebprvehmbffwiabregsoqcayqgux"
)

echo ==========================================
echo      Chat with Luotianyi - Portable
echo ==========================================
echo.

:: Start the application
"%PYTHON_HOME%\python.exe" "start.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Program exited with error code: %ERRORLEVEL%
    pause
)

endlocal
"""
    
    with open(dist_dir / "run.bat", "w", encoding="utf-8") as f:
        f.write(bat_content)

    print(f"=== 构建完成！ ===")
    print(f"请将文件夹 '{dist_dir}' 发送给用户。")
    print(f"用户只需双击 'run.bat' 即可运行。")

if __name__ == "__main__":
    build_portable()
