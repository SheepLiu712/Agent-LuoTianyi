"""
洛天依 Agent 服务端 — 一键安装 & 配置向导
=============================================
跨平台启动器。自动检测操作系统并委托给平台原生脚本：
  - Linux   → setup_server.sh  (bash)
  - Windows → setup_server.ps1 (PowerShell)

如果原生脚本不可用，回退到内置的 Python 实现。

用法:
  python setup_server.py              # 交互式完整安装
  python setup_server.py --quick      # 快速安装
  python setup_server.py --config     # 仅配置向导
  python setup_server.py --no-env     # 跳过环境安装
"""

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
SH_SCRIPT = SCRIPT_DIR / "setup_server.sh"
PS1_SCRIPT = SCRIPT_DIR / "setup_server.ps1"


def launch_native(args: list) -> bool:
    """尝试调用平台原生脚本，成功返回 True"""
    if sys.platform.startswith("linux"):
        if SH_SCRIPT.exists():
            cmd = ["bash", str(SH_SCRIPT)] + args
            print(f"启动 Linux 原生安装脚本...\n")
            return subprocess.run(cmd).returncode == 0

    elif sys.platform == "win32":
        if PS1_SCRIPT.exists():
            ps_args = " ".join(args)
            ps_code = f"Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; & '{PS1_SCRIPT}' {ps_args}"
            cmd = ["powershell", "-NoProfile", "-Command", ps_code]
            print("启动 Windows 原生安装脚本...\n")
            return subprocess.run(cmd).returncode == 0

    return False


# ══════════════════════════════════════════════════════════
#  回退: 内置 Python 安装器 (精简版)
# ══════════════════════════════════════════════════════════

def fallback_install(args):
    """当原生脚本不可用时使用内置 Python 实现"""
    print("⚠️  未找到平台原生脚本，使用 Python 回退模式")
    print("  建议安装原生脚本以获得更好的体验(防火墙、systemd 服务等)\n")

    from importlib import util as import_util
    spec = import_util.spec_from_file_location("setup_server_fallback", str(SH_SCRIPT))
    if spec is None:
        print("❌ 无法加载安装模块")
        sys.exit(1)

    # ── 简化的回退实现 ──
    banner = """
    ╔══════════════════════════════════════════════════╗
    ║  洛天依 Agent 服务端 — 安装向导 (Python 回退)   ║
    ╚══════════════════════════════════════════════════╝
    """
    print(banner)

    # 1. 环境检测
    import platform
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"❌ 需要 Python >= 3.10，当前: {v.major}.{v.minor}.{v.micro}")
        sys.exit(1)
    print(f"✅ Python {v.major}.{v.minor}.{v.micro} ({platform.system()} {platform.machine()})")

    # 2. Conda 检测
    pkg_manager = None
    try:
        r = subprocess.run(["conda", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            pkg_manager = "conda"
            print(f"✅ Conda: {r.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if not pkg_manager:
        print("ℹ️  使用 venv (未检测到 Conda)")

    # 3. 仓库拉取
    if not (SERVER_DIR / "server_main.py").exists():
        repo = "https://github.com/jinyiwei2012/Agent-LuoTianyi.git"
        print(f"\n克隆仓库: {repo}")
        subprocess.run(["git", "clone", repo, str(SERVER_DIR.parent)], check=True)
    else:
        print(f"✅ 服务端目录: {SERVER_DIR}")
        if input("\n是否拉取最新代码？(y/N): ").lower() == "y":
            subprocess.run(["git", "pull"], cwd=SERVER_DIR.parent)

    # 4. 环境安装
    if not args.no_env:
        req_file = SERVER_DIR / "docs" / "requirements.txt"
        if pkg_manager == "conda":
            env_name = "lty"
            subprocess.run(["conda", "create", "-n", env_name, "python=3.10", "-y"],
                           capture_output=True)
            subprocess.run(f"conda run -n {env_name} pip install -r \"{req_file}\" -q",
                           shell=True)
            print("\n激活环境: conda activate", env_name)
        else:
            venv_dir = SERVER_DIR / ".venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)])
            pip_cmd = str(venv_dir / "bin" / "pip") if sys.platform != "win32" else str(venv_dir / "Scripts" / "pip.exe")
            subprocess.run([pip_cmd, "install", "-r", str(req_file), "-q"])
            activate = f"source {venv_dir}/bin/activate" if sys.platform != "win32" else f"{venv_dir}\\Scripts\\activate"
            print(f"\n激活环境: {activate}")

    # 5. 配置向导
    if args.config or input("\n是否运行配置向导？(y/N): ").lower() == "y":
        run_fallback_config(args)

    print("\n💡 启动服务: python server_main.py")
    print("   注意: 防火墙需手动放行端口 60030\n")


def run_fallback_config(args):
    """回退模式的交互式配置"""
    import json

    config_file = SERVER_DIR / "config" / "config.json"
    template_file = SERVER_DIR / "config" / "config.json.template"

    config = {}
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
    elif template_file.exists():
        with open(template_file) as f:
            config = json.load(f)

    print("\n── 配置向导 ──")

    is_debug = input("调试模式？(y/n, 默认 y): ").lower() != "n"
    port = input(f"服务端口 (默认 {60030}): ").strip() or "60030"
    use_https = input("启用 HTTPS？(y/n, 默认 n): ").lower() == "y" if not is_debug else False

    scheme = "https" if use_https else "http"
    host = "127.0.0.1" if is_debug else "0.0.0.0"
    mode_key = "debug_config" if is_debug else "release_config"

    config["is_debug"] = is_debug
    config[mode_key] = {
        "base_url": f"{scheme}://{host}:{port}",
        "verify_ssl": use_https
    }

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    print(f"\n✅ 配置已保存: {config_file}")
    print(f"   地址: {scheme}://{host}:{port}")

    # 连接信息
    try:
        import socket
        hostname = socket.gethostname()
        seen = set()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if not ip.startswith("127.") and "." in ip and ip not in seen:
                seen.add(ip)
                print(f"   局域网: {scheme}://{ip}:{port}")
    except Exception:
        pass

    print("\n⚠️  请手动放行防火墙端口")
    if sys.platform.startswith("linux"):
        print(f"   sudo ufw allow {port}/tcp")
    elif sys.platform == "win32":
        print(f"   netsh advfirewall firewall add rule name='AgentLuo' dir=in action=allow protocol=TCP localport={port}")


# ══════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="洛天依 Agent 服务端 — 一键安装 & 配置向导",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python setup_server.py              # 交互式安装
              python setup_server.py --quick      # 快速安装
              python setup_server.py --config     # 仅配置向导
        """)
    )
    parser.add_argument("--quick", action="store_true", help="快速安装（跳过向导）")
    parser.add_argument("--config", action="store_true", help="仅运行配置向导")
    parser.add_argument("--no-env", action="store_true", help="跳过环境安装")
    args = parser.parse_args()

    # 构建参数列表
    native_args = []
    if args.quick:
        native_args.append("--quick")
    if args.config:
        native_args.append("--config-only" if sys.platform.startswith("linux") else "-ConfigOnly")
    if args.no_env:
        native_args.append("--no-env" if sys.platform.startswith("linux") else "-NoEnv")

    # 尝试启动原生脚本
    launched = launch_native(native_args)

    if not launched:
        fallback_install(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
