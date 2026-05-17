#!/usr/bin/env bash
# ====================================================================
# 洛天依 Agent 服务端 — 一键安装 & 配置向导 (Linux / Bash)
# ====================================================================
# 功能: 仓库拉取 → 环境安装 → 配置向导 → 放行端口 → 启动服务
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/.../setup_server.sh | bash
#   bash setup_server.sh
#   bash setup_server.sh --quick          # 仅装依赖 + 模板配置
#   bash setup_server.sh --config-only    # 仅运行配置向导
# ====================================================================
set -euo pipefail

# ── 仓库信息 ──────────────────────────────────────────────
REPO_URL="https://github.com/jinyiwei2012/Agent-LuoTianyi.git"
UPSTREAM_URL="https://github.com/SheepLiu712/Agent-LuoTianyi.git"
BRANCH="feat/oneclick-deploy-server-config"
MIN_PYTHON="3.10"
DEFAULT_PORT=60030
SERVER_USER="luotianyi"

# ── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}${BOLD}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}${BOLD}[WARN]${NC} $1"; }
error() { echo -e "${RED}${BOLD}[ERROR]${NC} $1"; exit 1; }
header(){ echo -e "\n${CYAN}${BOLD}── $1 ──${NC}\n"; }
input() { read -r -p "$(echo -e "${CYAN}▶${NC} $1")" "${2:-REPLY}"; }

# ══════════════════════════════════════════════════════════
# 1. 前置检测
# ══════════════════════════════════════════════════════════

check_prerequisites() {
    header "前置检测"

    # OS 检测
    if [ "$(uname)" != "Linux" ]; then
        warn "此脚本针对 Linux 优化。Windows 请使用 setup_server.ps1"
    fi

    # Git
    command -v git >/dev/null 2>&1 || error "请先安装 git: apt-get install git / yum install git"
    info "Git: $(git --version)"

    # Python
    if command -v python3 >/dev/null 2>&1; then
        py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if [ "$(printf '%s\n' "$MIN_PYTHON" "$py_ver" | sort -V | head -1)" != "$MIN_PYTHON" ]; then
            error "需要 Python >= $MIN_PYTHON (当前: $py_ver)"
        fi
        PYTHON=$(command -v python3)
        info "Python: $py_ver ($PYTHON)"
    else
        error "未找到 python3，请先安装 Python >= $MIN_PYTHON"
    fi

    # Conda (可选)
    if command -v conda >/dev/null 2>&1; then
        PKG_MGR="conda"
        info "Conda: $(conda --version | head -1)"
    else
        PKG_MGR="venv"
        info "包管理器: venv (未检测到 Conda)"
    fi

    # pip
    $PYTHON -m pip --version >/dev/null 2>&1 || error "pip 不可用"
    info "pip: 可用"

    # OpenSSL (用于自签名证书)
    if command -v openssl >/dev/null 2>&1; then
        HAS_OPENSSL=true
        info "OpenSSL: 可用"
    else
        HAS_OPENSSL=false
        warn "openssl 未安装，HTTPS 证书生成将使用 Python 替代"
    fi
}

# ══════════════════════════════════════════════════════════
# 2. 仓库操作
# ══════════════════════════════════════════════════════════

clone_or_pull_repo() {
    header "仓库操作"

    # 如果当前在 Agent-LuoTianyi 仓库中
    if [ -d ".git" ] && git remote -v 2>/dev/null | grep -q "Agent-LuoTianyi"; then
        info "已在仓库 $(basename "$PWD") 中"
        current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        info "当前分支: $current_branch"
        input "是否拉取最新代码？(Y/n): " ; pull_ans=${REPLY:-Y}
        if [[ "$pull_ans" =~ ^[Yy] ]]; then
            git pull 2>/dev/null || {
                warn "拉取失败，尝试添加镜像 remote..."
                MIRROR_URL="https://kkgithub.com/${REPO_URL#https://github.com/}"
                git remote add mirror "$MIRROR_URL" 2>/dev/null && git pull mirror "$current_branch" 2>/dev/null && warn "已通过镜像更新代码" || warn "拉取失败，将继续使用本地代码"
            }
        fi
        PROJECT_DIR="$PWD"
    else
        # 检查是否在克隆的子目录内
        if [ -d "../.git" ] && git -C .. remote -v 2>/dev/null | grep -q "Agent-LuoTianyi"; then
            info "在仓库子目录中"
            PROJECT_DIR="$(cd .. && pwd)"
        else
            target_dir="Agent-LuoTianyi"
            if [ -d "$target_dir" ]; then
                warn "目录 $target_dir 已存在"
                input "是否删除并重新克隆？(y/N): " ; reclone=${REPLY:-N}
                if [[ "$reclone" =~ ^[Yy] ]]; then
                    rm -rf "$target_dir"
                else
                    info "使用已有目录"
                    PROJECT_DIR="$target_dir"
                    return
                fi
            fi
            info "克隆仓库: $REPO_URL"
            if ! git clone --branch "$BRANCH" "$REPO_URL" "$target_dir" 2>/dev/null; then
                warn "GitHub 直连失败，尝试镜像 kkgithub.com..."
                MIRROR_URL="https://kkgithub.com/${REPO_URL#https://github.com/}"
                if ! git clone --branch "$BRANCH" "$MIRROR_URL" "$target_dir" 2>/dev/null; then
                    warn "镜像也失败，尝试默认分支..."
                    git clone "$REPO_URL" "$target_dir" 2>/dev/null || error "克隆失败，请检查网络连接或手动克隆: $REPO_URL"
                fi
            fi
            PROJECT_DIR="$target_dir"
        fi
    fi

    cd "$PROJECT_DIR" || error "无法进入项目目录"
    SERVER_DIR="$PROJECT_DIR/server"
    info "项目目录: $PROJECT_DIR"
    info "服务端目录: $SERVER_DIR"
}

# ══════════════════════════════════════════════════════════
# 3. 环境安装
# ══════════════════════════════════════════════════════════

setup_environment() {
    header "虚拟环境 & 依赖安装"

    cd "$SERVER_DIR"

    if [ "$PKG_MGR" = "conda" ]; then
        ENV_NAME="lty"
        if conda env list | grep -q "^$ENV_NAME "; then
            info "Conda 环境 '$ENV_NAME' 已存在"
            input "是否重建？(y/N): " ; rebuild=${REPLY:-N}
            if [[ "$rebuild" =~ ^[Yy] ]]; then
                conda env remove -n "$ENV_NAME" -y
                conda create -n "$ENV_NAME" python=3.10 -y
            fi
        else
            info "创建 Conda 环境: $ENV_NAME (Python 3.10)"
            conda create -n "$ENV_NAME" python=3.10 -y
        fi

        # CUDA 选项
        header "GPU 加速 (可选)"
        info "是否安装 CUDA 版 PyTorch？(用于 GPU 加速 TTS)"
        info "  1) CUDA 12.6"
        info "  2) CUDA 12.4"
        info "  3) 不安装 (CPU 模式，默认)"
        input "请选择 [1/2/3] (默认 3): " ; cuda_choice=${REPLY:-3}

        info "安装 Python 依赖..."
        conda run -n "$ENV_NAME" pip install -r docs/requirements.txt -q || warn "部分依赖安装失败"

        case "$cuda_choice" in
            1) info "安装 PyTorch CUDA 12.6..."
               conda run -n "$ENV_NAME" pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 -q ;;
            2) info "安装 PyTorch CUDA 12.4..."
               conda run -n "$ENV_NAME" pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 -q ;;
        esac

        info "安装 ffmpeg..."
        conda install -n "$ENV_NAME" ffmpeg -y -q
        ACTIVATE_CMD="conda activate $ENV_NAME"
        PYTHON_BIN="conda run -n $ENV_NAME python"
    else
        VENV_DIR="$SERVER_DIR/.venv"
        if [ -f "$VENV_DIR/bin/python" ]; then
            info "虚拟环境已存在: $VENV_DIR"
            input "是否重建？(y/N): " ; rebuild=${REPLY:-N}
            if [[ "$rebuild" =~ ^[Yy] ]]; then
                rm -rf "$VENV_DIR"
                $PYTHON -m venv "$VENV_DIR"
            fi
        else
            info "创建虚拟环境: $VENV_DIR"
            $PYTHON -m venv "$VENV_DIR"
        fi

        info "安装 Python 依赖..."
        "$VENV_DIR/bin/pip" install -r docs/requirements.txt -q || warn "部分依赖安装失败"
        ACTIVATE_CMD="source $VENV_DIR/bin/activate"
        PYTHON_BIN="$VENV_DIR/bin/python"
    fi

    info "✅ 环境安装完成"
    info "激活环境: $ACTIVATE_CMD"
}

# ══════════════════════════════════════════════════════════
# 4. 配置向导
# ══════════════════════════════════════════════════════════

config_wizard() {
    header "配置向导 (输入留空则使用默认值)"

    # 加载已有配置
    CONFIG_FILE="$SERVER_DIR/config/config.json"
    if [ -f "$CONFIG_FILE" ]; then
        info "已有配置文件: $CONFIG_FILE"
        input "是否重新配置？(y/N): " ; reconf=${REPLY:-N}
        [[ ! "$reconf" =~ ^[Yy] ]] && return
    fi

    echo -e "${YELLOW}进入交互式配置，所有选项可按 Enter 跳过使用默认值${NC}"

    # ── 运行模式 ──
    header "[1/8] 运行模式"
    input "调试模式？(y/n, 调试=HTTP+127.0.0.1) [Y]: " ; is_debug=${REPLY:-Y}
    input "服务端口 [$DEFAULT_PORT]: " ; port=${REPLY:-$DEFAULT_PORT}
    if [[ ! "$is_debug" =~ ^[Yy] ]]; then
        input "启用 HTTPS？(y/n, 需要 SSL 证书) [n]: " ; use_https=${REPLY:-n}
    else
        use_https="n"
    fi

    # ── API 密钥 ──
    header "[2/8] API 密钥"
    echo -e "${YELLOW}密钥可以填入明文，也可以使用 \$环境变量名 引用${NC}"
    input "SiliconFlow API 密钥 (用于嵌入向量) [$SILICONFLOW_API_KEY]: " ; siliconflow_key=${REPLY:-$SILICONFLOW_API_KEY}
    input "Qwen/DashScope API 密钥 (主 LLM/视觉) [$QWEN_API_KEY]: " ; qwen_key=${REPLY:-$QWEN_API_KEY}
    input "DeepSeek API 密钥 (记忆搜索/摘要) [$DEEPSEEK_API_KEY]: " ; deepseek_key=${REPLY:-$DEEPSEEK_API_KEY}
    input "高德地图 API 密钥 (Citywalk 插件, 可跳过) [$AMAP_KEY]: " ; amap_key=${REPLY:-$AMAP_KEY}

    # ── TTS ──
    header "[3/8] TTS (语音合成)"
    input "TTS 模型目录 [res/tts/lty_custom_onnx_model]: " ; tts_model=${REPLY:-res/tts/lty_custom_onnx_model}
    input "参考音频目录 [res/tts/reference_audio]: " ; ref_audio=${REPLY:-res/tts/reference_audio}

    # ── LLM 模型 ──
    header "[4/8] LLM 模型"
    input "主聊天模型 [qwen3.5-plus]: " ; main_model=${REPLY:-qwen3.5-plus}
    input "对话摘要模型 [deepseek-chat]: " ; summary_model=${REPLY:-deepseek-chat}

    # ── SSL 证书 ──
    header "[5/8] SSL 证书"
    if [[ "$use_https" =~ ^[Yy] ]]; then
        input "自动生成自签名证书？(Y/n): " ; gen_cert=${REPLY:-Y}
        if [[ "$gen_cert" =~ ^[Yy] ]]; then
            "$PYTHON_BIN" -c "
import sys; sys.path.insert(0, '$SERVER_DIR')
from scripts.generate_cert import generate_self_signed_cert
generate_self_signed_cert()
" || warn "证书生成失败，将使用 HTTP"
        fi
    fi

    # ── 防火墙 ──
    header "[6/8] 防火墙"
    input "是否自动放行端口 $port？(需要 root/sudo) [Y]: " ; do_firewall=${REPLY:-Y}

    # ── 网络检测 & 域名绑定 ──
    header "[7/8] 域名绑定"
    # 检测是否有公网 IP
    local public_ip
    public_ip=$("$PYTHON_BIN" -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('https://api.ipify.org?format=json', timeout=5)
    data = json.loads(r.read())
    print(data.get('ip', ''))
except: print('')
" 2>/dev/null)
    HAS_PUBLIC_IP=false
    if [ -n "$public_ip" ]; then
        for ip in $(ip -4 addr show 2>/dev/null | grep -oP 'inet \K[\d.]+' || hostname -I 2>/dev/null); do
            if [ "$public_ip" = "$ip" ]; then HAS_PUBLIC_IP=true; break; fi
        done
        if $HAS_PUBLIC_IP; then
            info "检测到公网 IP: $public_ip (本机)"
        else
            warn "公网 IP: $public_ip (非本机直连，可能经过 NAT)"
        fi
    else
        warn "未检测到公网 IP (服务器可能在 NAT 内，需要内网穿透)"
    fi

    input "是否有域名要绑定到本服务？(y/N): " ; has_domain=${REPLY:-N}
    if [[ "$has_domain" =~ ^[Yy] ]]; then
        input "输入域名 (例如 chat.example.com): " ; server_domain=${REPLY}
        input "自动配置 HTTPS 证书？(需要 Caddy) [Y]: " ; auto_https=${REPLY:-Y}
    fi

    # ── SakuraFrp 内网穿透（按需显示）──
    if $HAS_PUBLIC_IP && [[ "$has_domain" =~ ^[Yy] ]] && [ -n "${server_domain:-}" ]; then
        # 有公网 IP + 有域名 → 完全不需要内网穿透
        do_sakura="N"
        info "✅ 已有公网 IP + 域名，无需内网穿透"
    elif $HAS_PUBLIC_IP && [[ ! "$has_domain" =~ ^[Yy] ]]; then
        # 有公网 IP 但无域名 → 可选：直连 IP 或 SakuraFrp（隐藏 IP）
        header "[8/8] 公网访问方式"
        info "本机有公网 IP，可以直接用 IP 地址访问"
        info "使用 SakuraFrp 隧道可隐藏真实 IP（推荐生产环境）"
        input "选择方式 (1=公网 IP 直连  2=SakuraFrp 隧道) [1]: " ; access_mode=${REPLY:-1}
        if [ "$access_mode" = "2" ]; then
            do_sakura="Y"
            input "SakuraFrp API Token: " ; sakura_token=${REPLY}
            input "隧道名称 [AgentLuo]: " ; sakura_name=${REPLY:-AgentLuo}
            input "节点ID (留空自动): " ; sakura_node=${REPLY:-}
        fi
    elif ! $HAS_PUBLIC_IP && [[ "$has_domain" =~ ^[Yy] ]]; then
        # 无公网 IP 但有域名 → SakuraFrp + 域名指向 frp 地址
        header "[8/8] SakuraFrp 内网穿透"
        info "无公网 IP，需要内网穿透才能将域名 $server_domain 指向本机"
        input "是否配置 SakuraFrp 隧道？(Y/n): " ; do_sakura=${REPLY:-Y}
        if [[ "$do_sakura" =~ ^[Yy] ]]; then
            input "SakuraFrp API Token: " ; sakura_token=${REPLY}
            input "隧道名称 [AgentLuo]: " ; sakura_name=${REPLY:-AgentLuo}
            input "节点ID (留空自动): " ; sakura_node=${REPLY:-}
        fi
    else
        # 无公网 IP + 无域名
        header "[8/8] SakuraFrp 内网穿透"
        info "未检测到公网 IP，需要内网穿透才能从外网访问"
        input "是否配置 SakuraFrp 隧道？(Y/n): " ; do_sakura=${REPLY:-Y}
        if [[ "$do_sakura" =~ ^[Yy] ]]; then
            input "SakuraFrp API Token: " ; sakura_token=${REPLY}
            input "隧道名称 [AgentLuo]: " ; sakura_name=${REPLY:-AgentLuo}
            input "节点ID (留空自动): " ; sakura_node=${REPLY:-}
        fi
    fi

    # ── 生成配置 ──
    header "生成配置文件"

    if [[ "$is_debug" =~ ^[Yy] ]]; then
        scheme="http"
        host="127.0.0.1"
    else
        # 优先级: 域名 > 公网 IP 直连 > 0.0.0.0
        if [[ "$has_domain" =~ ^[Yy] ]] && [ -n "${server_domain:-}" ]; then
            scheme="https"
            host="0.0.0.0"
            base_url_host="$server_domain"
        elif $HAS_PUBLIC_IP && [ "$access_mode" = "1" ]; then
            scheme="http"
            host="0.0.0.0"
            base_url_host="$public_ip"
        else
            [[ "$use_https" =~ ^[Yy] ]] && scheme="https" || scheme="http"
            host="0.0.0.0"
            base_url_host="$host"
        fi
    fi

    # 复制模板作为基础
    if [ -f "$SERVER_DIR/config/config.json.template" ] && [ ! -f "$CONFIG_FILE" ]; then
        cp "$SERVER_DIR/config/config.json.template" "$CONFIG_FILE"
    fi

    # 使用 Python 写入 JSON (比 sed/jq 更安全)
    "$PYTHON_BIN" -c "
import json, os

# 读取或创建配置
try:
    with open('$CONFIG_FILE', 'r') as f:
        c = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    c = {}

def s(d, keys, val):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val

c['is_debug'] = ${is_debug,,true}
s(c, ['debug_config' if ${is_debug,,true} else 'release_config'], {
    'base_url': '${scheme}://${base_url_host:-${host}}:${port}',
    'verify_ssl': ${use_https,,false}
})

# API 密钥 / 模型配置
s(c, ['database', 'embedding_model'], {
    'api_type': 'openai', 'model': 'BAAI/bge-large-zh-v1.5',
    'api_key': '${siliconflow_key}', 'base_url': 'https://api.siliconflow.cn/v1'
})
s(c, ['knowledge', 'llm'], {
    'api_type': 'openai', 'model': '${main_model}',
    'api_key': '${qwen_key}', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'enable_thinking': False
})
s(c, ['main_chat', 'llm_module', 'llm'], {
    'api_type': 'openai', 'model': '${main_model}',
    'api_key': '${qwen_key}', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'enable_thinking': False
})
s(c, ['main_chat', 'llm_module', 'prompt_name'], 'topic_reply_prompt')
s(c, ['conversation_manager', 'llm_module', 'llm'], {
    'api_type': 'openai', 'model': '${summary_model}',
    'api_key': '${deepseek_key}', 'base_url': 'https://api.deepseek.com/v1',
    'temperature': 0.7, 'max_tokens': 8192, 'top_p': 0.9
})
s(c, ['conversation_manager', 'llm_module', 'prompt_name'], 'summary_prompt')
s(c, ['tts', 'onnx_model_dir'], '${tts_model}')
s(c, ['tts', 'reference_audio_dir'], '${ref_audio}')
s(c, ['vision_module', 'vlm_module', 'vlm', 'api_key'], '${qwen_key}')
s(c, ['vision_module', 'vlm_module', 'vlm', 'model'], 'qwen3-vl-plus')
s(c, ['memory_manager', 'memory_searcher', 'llm_module', 'llm', 'api_key'], '${deepseek_key}')
s(c, ['memory_manager', 'memory_writer', 'llm_module', 'llm', 'api_key'], '${qwen_key}')
s(c, ['memory_manager', 'memory_writer', 'llm_module', 'llm', 'model'], '${main_model}')
s(c, ['topic_extractor', 'llm_module', 'llm', 'api_key'], '${qwen_key}')
s(c, ['topic_extractor', 'llm_module', 'llm', 'model'], '${main_model}')
s(c, ['activity_maker', 'llm', 'api_key'], '${qwen_key}')
s(c, ['activity_maker', 'llm', 'model'], '${main_model}')
s(c, ['schedule', 'llm', 'api_key'], '${qwen_key}')
s(c, ['schedule', 'llm', 'model'], '${main_model}')
s(c, ['crawler', 'llm_module', 'llm', 'api_key'], '${siliconflow_key}')

if '${amap_key}' and '${amap_key}' != '\$AMAP_KEY':
    s(c, ['citywalk', 'amap', 'api_key'], '${amap_key}')

with open('$CONFIG_FILE', 'w') as f:
    json.dump(c, f, ensure_ascii=False, indent=4)
print('✅ 配置已保存: $CONFIG_FILE')
" || error "配置写入失败"

    info "✅ 配置完成"
}

# ══════════════════════════════════════════════════════════
# 5. 防火墙配置 (最低权限: 仅在需要时提权)
# ══════════════════════════════════════════════════════════

configure_firewall() {
    local port="$1"
    [[ -z "$port" ]] && port="$DEFAULT_PORT"

    header "防火墙配置"

    # 检查是否已放行
    if command -v ufw >/dev/null 2>&1; then
        if sudo -n ufw status 2>/dev/null | grep -q "$port"; then
            info "端口 $port 已在 ufw 中放行"
            return
        fi
        info "使用 ufw 放行 TCP/$port ..."
        sudo ufw allow "$port/tcp" comment "AgentLuo Server" || warn "ufw 放行失败，请手动执行: sudo ufw allow $port/tcp"
        sudo ufw reload 2>/dev/null || true
        info "✅ ufw 已放行端口 $port"

    elif command -v firewall-cmd >/dev/null 2>&1; then
        if sudo -n firewall-cmd --list-ports 2>/dev/null | grep -q "$port"; then
            info "端口 $port 已在 firewalld 中放行"
            return
        fi
        info "使用 firewalld 放行 TCP/$port ..."
        sudo firewall-cmd --permanent --add-port="$port/tcp" || warn "firewall-cmd 失败"
        sudo firewall-cmd --reload || true
        info "✅ firewalld 已放行端口 $port"

    elif command -v iptables >/dev/null 2>&1; then
        if sudo -n iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
            info "端口 $port 已在 iptables 中放行"
            return
        fi
        info "使用 iptables 放行 TCP/$port ..."
        sudo iptables -A INPUT -p tcp --dport "$port" -j ACCEPT || warn "iptables 放行失败"
        # 尝试持久化
        if command -v iptables-save >/dev/null 2>&1; then
            if [ -d "/etc/iptables" ]; then
                sudo sh -c "iptables-save > /etc/iptables/rules.v4" 2>/dev/null || true
            fi
        fi
        info "✅ iptables 已放行端口 $port"

    else
        warn "未检测到防火墙工具 (ufw/firewalld/iptables)"
        warn "请手动放行端口 $port，或使用云服务商的安全组策略"
    fi
}

# ══════════════════════════════════════════════════════════
# 5b. SakuraFrp 内网穿透隧道配置
# ══════════════════════════════════════════════════════════

configure_sakurafrp() {
    [[ -z "${sakura_token:-}" ]] && return
    header "SakuraFrp 内网穿透"

    local port="${1:-$DEFAULT_PORT}"
    local tunnel_name="${sakura_name:-AgentLuo}"
    local node_param=""
    [[ -n "${sakura_node:-}" ]] && node_param=", \"node\": $sakura_node"

    info "正在通过 SakuraFrp API 创建 TCP 隧道..."

    # 调用 SakuraFrp API 创建隧道
    local resp
    resp=$(curl -s -X POST "https://api.natfrp.com/v1/tunnel/create" \
        -H "Authorization: $sakura_token" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$tunnel_name\", \"type\": \"tcp\", \"local_ip\": \"127.0.0.1\", \"local_port\": $port, \"proxy_protocol\": false $node_param}") || {
        warn "SakuraFrp API 调用失败"
        warn "请手动在 https://www.natfrp.com/ 创建隧道"
        return
    }

    # 解析响应
    local tunnel_id remote_port remote_addr
    tunnel_id=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    remote_port=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('remote_port',''))" 2>/dev/null || echo "")
    remote_addr=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('remote_addr',''))" 2>/dev/null || echo "")

    if [ -z "$tunnel_id" ] || [ "$tunnel_id" = "0" ]; then
        local err_msg=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error','未知错误'))" 2>/dev/null)
        warn "SakuraFrp 隧道创建失败: $err_msg"
        warn "响应: $(echo "$resp" | head -c 200)"
        return
    fi

    info "✅ 隧道创建成功！"
    info "  隧道 ID: $tunnel_id"
    info "  远程地址: ${remote_addr}"

    # 保存隧道信息到配置文件
    "$PYTHON_BIN" -c "
import json
try:
    with open('$CONFIG_FILE', 'r') as f:
        c = json.load(f)
except: c = {}
c['sakurafrp'] = {'tunnel_id': $tunnel_id, 'remote_addr': '$remote_addr', 'remote_port': '$remote_port', 'local_port': $port}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(c, f, ensure_ascii=False, indent=4)
print('✅ 隧道信息已保存到配置文件')
" 2>/dev/null || warn "无法保存隧道信息到配置文件"

    # 下载 frpc
    local frpc_dir="$SERVER_DIR/frpc"
    mkdir -p "$frpc_dir"
    local frpc_bin="$frpc_dir/frpc"

    if [ ! -f "$frpc_bin" ]; then
        info "下载 frpc 客户端..."
        local os arch download_url
        os="linux"
        arch=$(uname -m)
        case "$arch" in
            x86_64|amd64) arch="amd64" ;;
            aarch64|arm64) arch="arm64" ;;
            armv7l|armv8l) arch="arm" ;;
        esac
        download_url="https://cdn.natfrp.com/frpc_${os}_${arch}.tar.gz"

        curl -fsSL -o "$frpc_dir/frpc.tar.gz" "$download_url" || {
            warn "frpc 下载失败，请手动下载: $download_url"
            warn "隧道 ID: $tunnel_id 可在 https://www.natfrp.com/ 查看"
            return
        }
        tar -xzf "$frpc_dir/frpc.tar.gz" -C "$frpc_dir" 2>/dev/null || {
            warn "frpc 解压失败"
            return
        }
        chmod +x "$frpc_bin" 2>/dev/null || true
        rm -f "$frpc_dir/frpc.tar.gz"
        info "✅ frpc 已下载: $frpc_bin"
    else
        info "frpc 已存在: $frpc_bin"
    fi

    # 生成 frpc 配置
    local frpc_ini="$frpc_dir/frpc.ini"
    cat > "$frpc_ini" << FRPC_INI
[common]
token = $sakura_token
server_addr = $remote_addr
admin_addr = 127.0.0.1
admin_port = 7400

[$tunnel_name]
type = tcp
local_ip = 127.0.0.1
local_port = $port
remote_port = $remote_port
FRPC_INI
    info "✅ frpc 配置已生成: $frpc_ini"

    # 创建 frpc systemd 服务
    if [ -d "/etc/systemd/system" ]; then
        local frpc_service="/etc/systemd/system/agent-frpc.service"
        if [ ! -f "$frpc_service" ]; then
            cat > /tmp/agent-frpc.service << FRPC_SERVICE
[Unit]
Description=SakuraFrp Tunnel for AgentLuoTianyi
After=network.target

[Service]
Type=simple
ExecStart=$frpc_bin -c $frpc_ini
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
FRPC_SERVICE
            sudo mv /tmp/agent-frpc.service "$frpc_service" 2>/dev/null && {
                sudo systemctl daemon-reload
                info "✅ frpc systemd 服务已创建: agent-frpc.service"
            } || warn "无法创建 frpc systemd 服务"
        else
            info "frpc systemd 服务已存在"
        fi
    fi

    info ""
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "  SakuraFrp 隧道配置完成！"
    info "  远程地址: ${remote_addr}"
    info "  本地端口映射: 127.0.0.1:$port → ${remote_addr}"
    info ""
    info "  客户端访问地址: $(echo "$remote_addr" | sed 's/:.*//'):$remote_port"
    info "  管理面板: https://www.natfrp.com/"
    if [ -f "/etc/systemd/system/agent-frpc.service" ]; then
        info "  启动隧道: sudo systemctl start agent-frpc"
        info "  查看状态: sudo systemctl status agent-frpc"
    else
        info "  启动隧道: $frpc_bin -c $frpc_ini"
    fi
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ══════════════════════════════════════════════════════════
# 5c. 域名绑定 & Caddy 自动 HTTPS
# ══════════════════════════════════════════════════════════

configure_domain() {
    [[ -z "${server_domain:-}" ]] && return
    header "域名绑定 & HTTPS 自动配置"

    local domain="$server_domain"
    local port="${1:-$DEFAULT_PORT}"

    info "域名: $domain"
    info "目标端口: $port"

    # DNS 验证（可选）
    if command -v dig >/dev/null 2>&1; then
        local resolved_ip
        resolved_ip=$(dig +short "$domain" 2>/dev/null | head -1)
        if [ -n "$resolved_ip" ]; then
            info "DNS 解析: $domain → $resolved_ip"
            # 尝试匹配本机 IP
            local match=false
            for ip in $(ip -4 addr show 2>/dev/null | grep -oP 'inet \K[\d.]+' 2>/dev/null || hostname -I 2>/dev/null); do
                if [ "$resolved_ip" = "$ip" ]; then
                    match=true; break
                fi
            done
            if ! $match; then
                warn "域名 $domain 解析到 $resolved_ip，与本机 IP 不匹配"
                warn "请确保 DNS 已指向本机后再继续"
                input "是否继续？(Y/n): " ; dns_confirm=${REPLY:-Y}
                [[ ! "$dns_confirm" =~ ^[Yy] ]] && return
            fi
        else
            warn "无法解析域名 $domain，请确认 DNS 已配置"
            input "是否继续？(y/N): " ; dns_skip=${REPLY:-N}
            [[ ! "$dns_skip" =~ ^[Yy] ]] && return
        fi
    elif command -v nslookup >/dev/null 2>&1; then
        nslookup "$domain" 2>/dev/null | head -5
    else
        warn "未安装 dig/nslookup，跳过 DNS 验证"
    fi

    # ── Caddy 安装 ──
    if [[ ! "$auto_https" =~ ^[Yy] ]]; then
        info "跳过 Caddy 自动 HTTPS 配置"
        info "请自行配置反向代理将 https://$domain 指向 127.0.0.1:$port"
        return
    fi

    if command -v caddy >/dev/null 2>&1; then
        info "Caddy 已安装: $(caddy version 2>/dev/null || echo '版本未知')"
    else
        info "正在安装 Caddy (自动 HTTPS 反向代理)..."
        # 官方安装方式
        if command -v apt-get >/dev/null 2>&1; then
            # Debian/Ubuntu
            sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https 2>/dev/null
            curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
            curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null 2>/dev/null || true
            sudo apt-get update -q 2>/dev/null && sudo apt-get install -y caddy 2>/dev/null || {
                warn "apt 安装失败，尝试直接下载..."
                install_caddy_direct
            }
        elif command -v yum >/dev/null 2>&1; then
            # RHEL/CentOS/Fedora
            sudo dnf install 'dnf-command(copr)' -y 2>/dev/null
            sudo dnf copr enable @caddy/caddy -y 2>/dev/null
            sudo dnf install caddy -y 2>/dev/null || {
                warn "yum 安装失败，尝试直接下载..."
                install_caddy_direct
            }
        else
            install_caddy_direct
        fi
    fi

    if ! command -v caddy >/dev/null 2>&1; then
        warn "Caddy 安装失败，请手动配置反向代理"
        info "将域名 $domain 指向 http://127.0.0.1:$port"
        return
    fi

    # 生成 Caddyfile
    local caddyfile="/etc/caddy/Caddyfile"
    local caddyfile_content="# AgentLuoTianyi - 由 setup_server.sh 自动配置
$domain {
    reverse_proxy 127.0.0.1:$port
    encode gzip
    header {
        -Server
    }
}
"
    if [ -d "/etc/caddy" ]; then
        echo "$caddyfile_content" | sudo tee "$caddyfile" >/dev/null
        info "✅ Caddyfile 已生成: $caddyfile"
    else
        # 备用路径
        caddyfile="$SERVER_DIR/Caddyfile"
        echo "$caddyfile_content" > "$caddyfile"
        info "✅ Caddyfile 已生成: $caddyfile"
    fi

    # 启动/重载 Caddy
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl enable caddy 2>/dev/null || true
        if sudo systemctl is-active --quiet caddy 2>/dev/null; then
            sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy 2>/dev/null
            info "✅ Caddy 已重载"
        else
            sudo systemctl start caddy 2>/dev/null || {
                warn "systemctl 启动失败，尝试直接运行..."
                sudo caddy run --config "$caddyfile" &
            }
            info "✅ Caddy 已启动"
        fi
    else
        # 直接运行
        sudo caddy run --config "$caddyfile" --adapter caddyfile &
        info "✅ Caddy 已启动（后台）"
    fi

    # 保存 Caddy 信息到配置文件
    "$PYTHON_BIN" -c "
import json
try:
    with open('$CONFIG_FILE', 'r') as f:
        c = json.load(f)
except: c = {}
c['domain'] = {'domain': '$domain', 'https_auto': True, 'proxy': 'caddy'}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(c, f, ensure_ascii=False, indent=4)
print('✅ 域名信息已保存到配置文件')
" 2>/dev/null || true

    info ""
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "  域名配置完成！"
    info "  访问地址: https://$domain"
    info "  Caddy 自动管理 Let's Encrypt 证书"
    info "  （首次访问可能需要等待几秒钟证书签发）"
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

install_caddy_direct() {
    info "通过官方脚本安装 Caddy..."
    sudo apt-get install -y caddy 2>/dev/null && return 0
    curl -fsSL https://getcaddy.com | sudo bash -s personal 2>/dev/null || {
        warn "Caddy 直接安装失败"
        info "请手动安装: https://caddyserver.com/docs/install"
        return 1
    }
}

# ══════════════════════════════════════════════════════════

check_privilege_mode() {
    header "权限检查"

    if [ "$(id -u)" -eq 0 ]; then
        warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        warn "  当前以 ROOT 身份运行！"
        warn "  建议创建专用系统用户来运行服务"
        warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        input "是否创建系统用户 '$SERVER_USER' 来运行服务？(Y/n): " ; create_user=${REPLY:-Y}
        if [[ "$create_user" =~ ^[Yy] ]]; then
            if id "$SERVER_USER" >/dev/null 2>&1; then
                info "用户 $SERVER_USER 已存在"
            else
                useradd -r -s /usr/sbin/nologin -m -d "/var/lib/$SERVER_USER" "$SERVER_USER" 2>/dev/null || {
                    warn "无法创建系统用户，请手动创建或使用非 root 用户运行"
                }
                info "✅ 已创建系统用户: $SERVER_USER"
            fi
            # 设置目录所有权
            chown -R "$SERVER_USER:$SERVER_USER" "$SERVER_DIR" 2>/dev/null || true
            RUN_AS_USER="$SERVER_USER"
            info "服务将以用户 '$SERVER_USER' 运行"
        else
            warn "⚠️  将以 root 运行，安全风险较高"
            echo -e "${YELLOW}建议: 创建普通用户 → su - 普通用户 → 重新运行此脚本${NC}"
        fi
    else
        info "✅ 以普通用户 $(whoami) 运行，符合最小权限原则"
        RUN_AS_USER=$(whoami)
    fi
}

# ══════════════════════════════════════════════════════════
# 7. 连接信息
# ══════════════════════════════════════════════════════════

show_connection_info() {
    header "服务器连接信息"

    local config_file="$SERVER_DIR/config/config.json"
    if [ ! -f "$config_file" ]; then
        warn "配置不存在，跳过连接信息"
        return
    fi

    # 用 Python 解析配置并展示
    "$PYTHON_BIN" -c "
import json, socket, re
try:
    with open('$config_file') as f:
        c = json.load(f)
except Exception:
    exit(0)

is_debug = c.get('is_debug', True)
mode_key = 'debug_config' if is_debug else 'release_config'
cfg = c.get(mode_key, {})
base_url = cfg.get('base_url', 'http://127.0.0.1:60030')
verify_ssl = cfg.get('verify_ssl', not is_debug)
m = re.search(r':(\d+)$', base_url)
port = m.group(1) if m else '$DEFAULT_PORT'
scheme = 'https' if 'https' in base_url else 'http'

print(f'\\n  本地地址:    {base_url}')
# LAN IPs
try:
    hostname = socket.gethostname()
    seen = set()
    for addr in socket.getaddrinfo(hostname, None):
        ip = addr[4][0]
        if not ip.startswith('127.') and '.' in ip and ip not in seen:
            seen.add(ip)
            print(f'  局域网地址:  {scheme}://{ip}:{port}')
except Exception:
    pass

print(f'  防火墙:      端口 {port} 已放行')
print(f'  SSL:         {\"开启\" if verify_ssl else \"关闭\"}')
print(f'  调试模式:    {\"是\" if is_debug else \"否\"}')
print(f'\\n  启动命令:    cd $SERVER_DIR && $PYTHON_BIN server_main.py')
" 2>/dev/null || warn "无法读取配置"
}

# ══════════════════════════════════════════════════════════
# 8. 创建 systemd 服务 (可选)
# ══════════════════════════════════════════════════════════

create_systemd_service() {
    header "Systemd 服务 (可选)"

    if [ ! -d "/etc/systemd/system" ]; then
        warn "未检测到 systemd，跳过服务创建"
        return
    fi

    if [ -f "/etc/systemd/system/agent-luotianyi.service" ]; then
        info "服务已存在: agent-luotianyi.service"
        return
    fi

    input "是否创建 systemd 服务以实现开机自启？(Y/n): " ; svc=${REPLY:-Y}
    if [[ ! "$svc" =~ ^[Yy] ]]; then
        return
    fi

    local run_user="${RUN_AS_USER:-root}"
    local service_file="/tmp/agent-luotianyi.service"

    cat > "$service_file" << EOF
[Unit]
Description=AgentLuoTianyi - AI Chat Service
After=network.target redis.target

[Service]
Type=simple
User=$run_user
WorkingDirectory=$SERVER_DIR
ExecStart=$PYTHON_BIN $SERVER_DIR/server_main.py
Restart=on-failure
RestartSec=10
EnvironmentFile=-$SERVER_DIR/.env

# 安全配置
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$SERVER_DIR/data $SERVER_DIR/config
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    sudo mv "$service_file" /etc/systemd/system/agent-luotianyi.service || {
        warn "无法写入 /etc/systemd/system，请手动创建"
        return
    }
    sudo systemctl daemon-reload
    sudo systemctl enable agent-luotianyi.service
    info "✅ Systemd 服务已创建: agent-luotianyi.service"
    info "  启动: sudo systemctl start agent-luotianyi"
    info "  状态: sudo systemctl status agent-luotianyi"
    info "  日志: sudo journalctl -u agent-luotianyi -f"
}

# ══════════════════════════════════════════════════════════
# 9. 启动服务
# ══════════════════════════════════════════════════════════

start_server() {
    header "启动服务器"

    input "是否现在启动服务器？(y/N): " ; start_ans=${REPLY:-N}
    if [[ ! "$start_ans" =~ ^[Yy] ]]; then
        info "你可以在后续手动启动:"
        echo "  cd $SERVER_DIR"
        echo "  $ACTIVATE_CMD && python server_main.py"
        return
    fi

    info "启动服务器 (端口: ${port:-$DEFAULT_PORT})..."
    if [ -n "${server_domain:-}" ]; then
        info "域名: https://$server_domain"
    fi

    # 先启动 frpc 隧道（如果已配置）
    if [ -f "/etc/systemd/system/agent-frpc.service" ]; then
        info "启动 SakuraFrp 隧道..."
        sudo systemctl start agent-frpc 2>/dev/null || warn "frpc 启动失败"
    elif [ -f "$SERVER_DIR/frpc/frpc.ini" ]; then
        info "启动 frpc（后台）..."
        nohup "$SERVER_DIR/frpc/frpc" -c "$SERVER_DIR/frpc/frpc.ini" > "$SERVER_DIR/frpc/frpc.log" 2>&1 &
        info "frpc PID: $!"
    fi

    cd "$SERVER_DIR"

    if command -v systemctl >/dev/null 2>&1 && [ -f "/etc/systemd/system/agent-luotianyi.service" ]; then
        sudo systemctl start agent-luotianyi
        sudo systemctl status agent-luotianyi --no-pager
    else
        # 以普通用户启动（非 root）
        if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ] && [ "$RUN_AS_USER" != "root" ]; then
            info "以用户 $RUN_AS_USER 启动..."
            sudo -u "$RUN_AS_USER" "$PYTHON_BIN" server_main.py
        else
            "$PYTHON_BIN" server_main.py
        fi
    fi
}

# ══════════════════════════════════════════════════════════
# 10. 主流程
# ══════════════════════════════════════════════════════════

usage() {
    cat << EOF
用法: bash setup_server.sh [选项]

选项:
  --quick        快速安装（环境 + 模板配置，跳过向导）
  --config-only  仅运行配置向导
  --no-env       跳过环境创建和依赖安装
  --help         显示此帮助

示例:
  bash setup_server.sh              # 完整安装
  bash setup_server.sh --quick      # 仅环境 + 模板
  bash setup_server.sh --config     # 仅配置
EOF
    exit 0
}

main() {
    # 解析参数
    QUICK_MODE=false
    CONFIG_ONLY=false
    NO_ENV=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --quick) QUICK_MODE=true; shift ;;
            --config-only|--config) CONFIG_ONLY=true; shift ;;
            --no-env) NO_ENV=true; shift ;;
            --help|-h) usage ;;
            *) warn "未知参数: $1"; shift ;;
        esac
    done

    # Banner
    echo -e "${CYAN}${BOLD}"
    echo "============================================================"
    echo "  洛天依 Agent 服务端 — 一键安装 & 配置向导 (Linux)"
    echo "============================================================"
    echo -e "${NC}"

    if $QUICK_MODE; then
        check_prerequisites
        clone_or_pull_repo
        setup_environment
        # 从模板复制配置
        if [ ! -f "$SERVER_DIR/config/config.json" ] && [ -f "$SERVER_DIR/config/config.json.template" ]; then
            cp "$SERVER_DIR/config/config.json.template" "$SERVER_DIR/config/config.json"
            info "已从模板创建配置文件，请编辑填入 API 密钥"
        fi
        show_connection_info
        info "✅ 快速安装完成"
        return
    fi

    check_prerequisites
    clone_or_pull_repo

    $NO_ENV || setup_environment

    if $CONFIG_ONLY; then
        config_wizard
        configure_firewall "$DEFAULT_PORT"
        show_connection_info
        return
    fi

    config_wizard
    check_privilege_mode

    # 防火墙
    if [[ "${do_firewall:-Y}" =~ ^[Yy] ]]; then
        configure_firewall "${port:-$DEFAULT_PORT}"
    fi

    # SakuraFrp 隧道
    if [[ "${do_sakura:-N}" =~ ^[Yy] ]]; then
        configure_sakurafrp "${port:-$DEFAULT_PORT}"
    fi

    # 域名绑定 & Caddy 自动 HTTPS
    if [[ "${has_domain:-N}" =~ ^[Yy] ]] && [ -n "${server_domain:-}" ]; then
        configure_domain "${port:-$DEFAULT_PORT}"
    fi

    # 连接信息
    show_connection_info

    # Systemd 服务
    create_systemd_service

    # 启动
    start_server
}

main "$@"
