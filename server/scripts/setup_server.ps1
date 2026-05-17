<#
.SYNOPSIS
    洛天依 Agent 服务端 — 一键安装 & 配置向导 (Windows / PowerShell)
.DESCRIPTION
    功能: 仓库拉取 → 环境安装 → 配置向导 → 放行端口 → 启动服务
    采用最低权限原则，仅防火墙操作用管理员权限。
.PARAMETER Quick
    快速安装（环境 + 模板配置，跳过向导）
.PARAMETER ConfigOnly
    仅运行配置向导
.PARAMETER NoEnv
    跳过环境创建和依赖安装
.EXAMPLE
    .\setup_server.ps1                  # 完整安装
    .\setup_server.ps1 -Quick           # 快速安装
    .\setup_server.ps1 -ConfigOnly      # 仅配置向导
#>
param(
    [switch]$Quick,
    [switch]$ConfigOnly,
    [switch]$NoEnv
)

#Requires -Version 5.1

# ── 仓库信息 ──────────────────────────────────────────────
$REPO_URL     = "https://github.com/jinyiwei2012/Agent-LuoTianyi.git"
$UPSTREAM_URL = "https://github.com/SheepLiu712/Agent-LuoTianyi.git"
$BRANCH       = "feat/oneclick-deploy-server-config"
$MIN_PYTHON   = "3.10"
$DEFAULT_PORT = 60030
$SERVER_USER  = "luotianyi"

# ── 颜色 ──────────────────────────────────────────────────
$Host.UI.RawUI.ForegroundColor = [ConsoleColor]::White

function Write-Info  { Write-Host "[INFO]" -ForegroundColor Green -NoNewline; Write-Host " $args" }
function Write-Warn  { Write-Host "[WARN]" -ForegroundColor Yellow -NoNewline; Write-Host " $args" }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red; exit 1 }
function Write-Header { Write-Host "`n── $args ──" -ForegroundColor Cyan }
function Read-Input {
    param([string]$Prompt, [string]$Default = "")
    $p = "▶ $Prompt"
    if ($Default) { $p += " [$Default]" }
    $p += ": "
    $a = Read-Host $p
    if ([string]::IsNullOrWhiteSpace($a)) { return $Default }
    return $a.Trim()
}

# ═══════════════════════════════════════════════════════════
# 1. 前置检测
# ═══════════════════════════════════════════════════════════

function Check-Privilege {
    Write-Header "权限检查"
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    $script:IsAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($script:IsAdmin) {
        Write-Warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        Write-Warn "  当前以管理员身份运行！"
        Write-Warn "  服务运行不需要管理员权限，仅防火墙操作需要"
        Write-Warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        Write-Warn "建议: 在非管理员 PowerShell 中重新运行此脚本"
    } else {
        Write-Info "✅ 以标准用户运行，符合最小权限原则"
        Write-Info "   防火墙操作将自动弹出 UAC 提权"
    }
}

function Check-Prerequisites {
    Write-Header "前置检测"

    # Git
    try {
        $ver = git --version
        Write-Info "Git: $ver"
    } catch {
        Write-Error "请先安装 Git: https://git-scm.com/download/win"
    }

    # Python
    try {
        $pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        $pyPath = (Get-Command python).Source
        if ([version]$pyVer -lt [version]$MIN_PYTHON) {
            Write-Error "需要 Python >= $MIN_PYTHON (当前: $pyVer)"
        }
        Write-Info "Python: $pyVer ($pyPath)"
        $script:PYTHON = "python"
    } catch {
        # 尝试 python3
        try {
            $pyVer = & python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            $pyPath = (Get-Command python3).Source
            if ([version]$pyVer -lt [version]$MIN_PYTHON) {
                Write-Error "需要 Python >= $MIN_PYTHON (当前: $pyVer)"
            }
            Write-Info "Python: $pyVer ($pyPath)"
            $script:PYTHON = "python3"
        } catch {
            Write-Error "未找到 Python，请安装 Python >= $MIN_PYTHON"
        }
    }

    # Conda (可选)
    try {
        $cv = conda --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            $script:PKG_MGR = "conda"
            Write-Info "Conda: $($cv.Trim())"
        } else {
            throw
        }
    } catch {
        $script:PKG_MGR = "venv"
        Write-Info "包管理器: venv (未检测到 Conda)"
    }

    # pip
    try {
        & $script:PYTHON -m pip --version >$null 2>&1
        Write-Info "pip: 可用"
    } catch {
        Write-Error "pip 不可用"
    }
}

# ═══════════════════════════════════════════════════════════
# 2. 仓库操作
# ═══════════════════════════════════════════════════════════

function Sync-Repo {
    Write-Header "仓库操作"

    # 如果已在仓库中
    if ((Test-Path ".git") -and (git remote -v 2>$null | Select-String "Agent-LuoTianyi")) {
        Write-Info "已在仓库 $(Split-Path -Leaf $PWD) 中"
        $branch = git rev-parse --abbrev-ref HEAD 2>$null
        Write-Info "当前分支: $branch"
        $ans = Read-Input "是否拉取最新代码？" "Y"
        if ($ans -eq "Y") {
            git pull 2>$null | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "拉取失败，尝试添加镜像 remote..."
                $mirrorUrl = $REPO_URL -replace 'https://github.com/', 'https://kkgithub.com/'
                git remote add mirror $mirrorUrl 2>$null
                git pull mirror $branch 2>$null | Out-Host
                if ($LASTEXITCODE -eq 0) { Write-Warn "已通过镜像更新代码" }
                else { Write-Warn "拉取失败，使用本地代码" }
            }
        }
        $script:PROJECT_DIR = $PWD
    } else {
        $target = "Agent-LuoTianyi"
        if (Test-Path $target) {
            Write-Warn "目录 $target 已存在"
            $ans = Read-Input "是否删除并重新克隆？" "N"
            if ($ans -eq "Y") { Remove-Item -Recurse -Force $target }
        }
        if (-not (Test-Path $target)) {
            Write-Info "克隆仓库: $REPO_URL"
            git clone --branch $BRANCH $REPO_URL $target 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "GitHub 直连失败，尝试镜像 kkgithub.com..."
                $mirrorUrl = $REPO_URL -replace 'https://github.com/', 'https://kkgithub.com/'
                Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue
                git clone --branch $BRANCH $mirrorUrl $target 2>$null
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "镜像也失败，尝试默认分支..."
                    Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue
                    git clone $REPO_URL $target 2>$null
                }
            }
        }
        $script:PROJECT_DIR = (Get-Item $target).FullName
    }

    Set-Location $script:PROJECT_DIR
    $script:SERVER_DIR = Join-Path $script:PROJECT_DIR "server"
    Write-Info "项目目录: $script:PROJECT_DIR"
    Write-Info "服务端目录: $script:SERVER_DIR"
}

# ═══════════════════════════════════════════════════════════
# 3. 环境安装
# ═══════════════════════════════════════════════════════════

function Install-Environment {
    Write-Header "虚拟环境 & 依赖安装"

    Set-Location $script:SERVER_DIR
    $reqFile = Join-Path $script:SERVER_DIR "docs\requirements.txt"
    if (-not (Test-Path $reqFile)) {
        Write-Error "未找到 requirements.txt: $reqFile"
    }

    if ($script:PKG_MGR -eq "conda") {
        $envName = "lty"
        $envs = conda env list 2>$null | Out-String
        if ($envs -match "\b$envName\b") {
            Write-Info "Conda 环境 '$envName' 已存在"
            $ans = Read-Input "是否重建？" "N"
            if ($ans -eq "Y") {
                conda env remove -n $envName -y 2>$null | Out-Null
                conda create -n $envName python=3.10 -y
            }
        } else {
            Write-Info "创建 Conda 环境: $envName (Python 3.10)"
            conda create -n $envName python=3.10 -y
        }

        # CUDA
        Write-Header "GPU 加速 (可选)"
        Write-Host "  1) CUDA 12.6"
        Write-Host "  2) CUDA 12.4"
        Write-Host "  3) 不安装 (CPU 模式)"
        $cuda = Read-Input "请选择" "3"

        Write-Info "安装 Python 依赖..."
        conda run -n $envName pip install -r "$reqFile" -q 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Warn "部分依赖安装失败" }

        switch ($cuda) {
            "1" { Write-Info "安装 PyTorch CUDA 12.6..."
                  conda run -n $envName pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 -q }
            "2" { Write-Info "安装 PyTorch CUDA 12.4..."
                  conda run -n $envName pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 -q }
        }

        Write-Info "安装 ffmpeg..."
        conda install -n $envName ffmpeg -y -q 2>$null
        $script:PYTHON_BIN = "conda run -n $envName python"
        $script:ACTIVATE_CMD = "conda activate $envName"
    } else {
        $venvDir = Join-Path $script:SERVER_DIR ".venv"
        $pythonExe = Join-Path $venvDir "Scripts\python.exe"

        if (Test-Path $pythonExe) {
            Write-Info "虚拟环境已存在: $venvDir"
            $ans = Read-Input "是否重建？" "N"
            if ($ans -eq "Y") {
                Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
                & $script:PYTHON -m venv $venvDir
            }
        } else {
            Write-Info "创建虚拟环境: $venvDir"
            & $script:PYTHON -m venv $venvDir
        }

        Write-Info "安装 Python 依赖..."
        & $pythonExe -m pip install -r "$reqFile" -q 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Warn "部分依赖安装失败" }

        $script:PYTHON_BIN = "& `"$pythonExe`""
        $script:ACTIVATE_CMD = "$venvDir\Scripts\Activate.ps1"
    }

    Write-Info "✅ 环境安装完成"
    Write-Info "激活环境: $script:ACTIVATE_CMD"
}

# ═══════════════════════════════════════════════════════════
# 4. 配置向导
# ═══════════════════════════════════════════════════════════

function Invoke-ConfigWizard {
    Write-Header "配置向导 (输入留空则使用默认值)"

    $configFile = Join-Path $script:SERVER_DIR "config\config.json"
    if (Test-Path $configFile) {
        Write-Info "已有配置文件: $configFile"
        $ans = Read-Input "是否重新配置？" "N"
        if ($ans -ne "Y") { return }
    }

    # 运行模式
    Write-Header "[1/8] 运行模式"
    $isDebug = Read-Input "调试模式？(y/n, 调试=HTTP+127.0.0.1)" "Y"
    $script:port = Read-Input "服务端口" $DEFAULT_PORT
    if ($isDebug -ne "Y") {
        $useHttps = Read-Input "启用 HTTPS？(y/n, 需要 SSL 证书)" "n"
    } else {
        $useHttps = "n"
    }

    # API 密钥
    Write-Header "[2/8] API 密钥"
    Write-Warn "密钥支持环境变量引用 (如 `$env:SILICONFLOW_API_KEY)"
    $siliconflowKey = Read-Input "SiliconFlow API 密钥" "`$SILICONFLOW_API_KEY"
    $qwenKey = Read-Input "Qwen/DashScope API 密钥" "`$QWEN_API_KEY"
    $deepseekKey = Read-Input "DeepSeek API 密钥" "`$DEEPSEEK_API_KEY"
    $amapKey = Read-Input "高德地图 API 密钥 (可跳过)" "`$AMAP_KEY"

    # TTS
    Write-Header "[3/8] TTS (语音合成)"
    $ttsModel = Read-Input "TTS 模型目录" "res/tts/lty_custom_onnx_model"
    $refAudio = Read-Input "参考音频目录" "res/tts/reference_audio"

    # LLM 模型
    Write-Header "[4/8] LLM 模型"
    $mainModel = Read-Input "主聊天模型" "qwen3.5-plus"
    $summaryModel = Read-Input "对话摘要模型" "deepseek-chat"

    # SSL 证书
    Write-Header "[5/8] SSL 证书"
    if ($useHttps -eq "Y") {
        $genCert = Read-Input "自动生成自签名证书？" "Y"
        if ($genCert -eq "Y") {
            Write-Info "生成 SSL 证书..."
            & $script:PYTHON_BIN -c @"
import sys; sys.path.insert(0, '$($script:SERVER_DIR)')
from scripts.generate_cert import generate_self_signed_cert
generate_self_signed_cert()
"@
            if ($LASTEXITCODE -ne 0) { Write-Warn "证书生成失败，将使用 HTTP" }
        }
    }

    # 防火墙
    Write-Header "[6/8] 防火墙"
    $script:doFirewall = Read-Input "是否自动放行端口 $($script:port)？(需要管理员权限)" "Y"

    # ── 公网 IP 检测 & 域名绑定 ──
    $script:HAS_PUBLIC_IP = $false
    $script:PublicIP = ""
    try {
        $resp = Invoke-RestMethod -Uri "https://api.ipify.org?format=json" -TimeoutSec 5
        if ($resp -and $resp.ip) {
            $publicIp = $resp.ip
            $localIps = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
                ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
                Where-Object { $_.Address.AddressFamily -eq 'InterNetwork' } |
                ForEach-Object { $_.Address.IPAddressToString }
            if ($localIps -contains $publicIp) {
                $script:HAS_PUBLIC_IP = $true
                $script:PublicIP = $publicIp
                Write-Info "检测到公网 IP: $publicIp (本机)"
            } else {
                Write-Warn "公网 IP: $publicIp (非本机直连，可能经过 NAT)"
            }
        }
    } catch {
        Write-Warn "未检测到公网 IP (服务器可能在 NAT 内，需要内网穿透)"
    }

    Write-Header "[7/8] 域名绑定"
    $script:hasDomain = Read-Input "是否有域名要绑定到本服务？" "N"
    if ($script:hasDomain -eq "Y") {
        $script:ServerDomain = Read-Input "输入域名 (例如 chat.example.com)"
        $script:AutoHttps = Read-Input "自动配置 HTTPS 证书？(需要 Caddy 反向代理)" "Y"
    }

    # ── SakuraFrp 内网穿透（按需显示）──
    if ($script:HAS_PUBLIC_IP -and $script:hasDomain -eq "Y" -and $script:ServerDomain) {
        # 有公网 IP + 有域名 → 完全不需要内网穿透
        $script:doSakura = "N"
        Write-Info "✅ 已有公网 IP + 域名，无需内网穿透"
    } elseif ($script:HAS_PUBLIC_IP -and $script:hasDomain -ne "Y") {
        # 有公网 IP 但无域名 → 可选：直连 IP 或 SakuraFrp
        Write-Header "[8/8] 公网访问方式"
        Write-Info "本机有公网 IP，可以直接用 IP 地址访问"
        Write-Info "使用 SakuraFrp 隧道可隐藏真实 IP（推荐生产环境）"
        $accessMode = Read-Input "选择方式 (1=公网 IP 直连  2=SakuraFrp 隧道)" "1"
        if ($accessMode -eq "2") {
            $script:doSakura = "Y"
            $script:SakuraToken = Read-Input "SakuraFrp API Token (从 https://www.natfrp.com/user/ 获取)"
            $script:SakuraName = Read-Input "隧道名称" "AgentLuo"
            $script:SakuraNode = Read-Input "节点ID (留空自动选择)" ""
        }
    } elseif (-not $script:HAS_PUBLIC_IP -and $script:hasDomain -eq "Y") {
        # 无公网 IP 但有域名 → SakuraFrp + 域名指向 frp 地址
        Write-Header "[8/8] SakuraFrp 内网穿透"
        Write-Info "无公网 IP，需要内网穿透才能将域名 $($script:ServerDomain) 指向本机"
        $script:doSakura = Read-Input "是否配置 SakuraFrp 隧道？" "Y"
        if ($script:doSakura -eq "Y") {
            $script:SakuraToken = Read-Input "SakuraFrp API Token (从 https://www.natfrp.com/user/ 获取)"
            $script:SakuraName = Read-Input "隧道名称" "AgentLuo"
            $script:SakuraNode = Read-Input "节点ID (留空自动选择)" ""
        }
    } else {
        # 无公网 IP + 无域名
        Write-Header "[8/8] SakuraFrp 内网穿透"
        Write-Info "未检测到公网 IP，需要内网穿透才能从外网访问"
        $script:doSakura = Read-Input "是否配置 SakuraFrp 隧道？" "Y"
        if ($script:doSakura -eq "Y") {
            $script:SakuraToken = Read-Input "SakuraFrp API Token (从 https://www.natfrp.com/user/ 获取)"
            $script:SakuraName = Read-Input "隧道名称" "AgentLuo"
            $script:SakuraNode = Read-Input "节点ID (留空自动选择)" ""
        }
    }

    # ── 写入配置 ──
    Write-Header "生成配置文件"

    $scheme = "http"
    $hostAddr = "127.0.0.1"
    $baseUrlHost = $hostAddr
    if ($isDebug -ne "Y") {
        # 优先级: 域名 > 公网 IP 直连 > 0.0.0.0
        if ($script:hasDomain -eq "Y" -and $script:ServerDomain) {
            $scheme = "https"
            $hostAddr = "0.0.0.0"
            $baseUrlHost = $script:ServerDomain
        } elseif ($script:HAS_PUBLIC_IP -and $accessMode -eq "1") {
            $scheme = "http"
            $hostAddr = "0.0.0.0"
            $baseUrlHost = $script:PublicIP
        } elseif ($useHttps -eq "Y") {
            $scheme = "https"
            $hostAddr = "0.0.0.0"
            $baseUrlHost = "0.0.0.0"
        } else {
            $scheme = "http"
            $hostAddr = "0.0.0.0"
            $baseUrlHost = "0.0.0.0"
        }
    }

    # 复制模板
    $templateFile = Join-Path $script:SERVER_DIR "config\config.json.template"
    if ((Test-Path $templateFile) -and -not (Test-Path $configFile)) {
        Copy-Item $templateFile $configFile
    }

    # 用 Python 生成 JSON
    $scriptBlock = @"
import json, os
c = {}
try:
    with open('$configFile'.replace('\\', '\\\\')) as f:
        c = json.load(f)
except: pass

def s(d, keys, val):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val

is_debug = ${is_debug} -eq 'Y'
s(c, 'debug_config' if is_debug else 'release_config', {
    'base_url': '${scheme}://${baseUrlHost}:${port}',
    'verify_ssl': ${useHttps} -eq 'Y'
})
c['is_debug'] = is_debug

s(c, ['database', 'embedding_model'], {'api_type': 'openai', 'model': 'BAAI/bge-large-zh-v1.5', 'api_key': '${siliconflowKey}', 'base_url': 'https://api.siliconflow.cn/v1'})
s(c, ['knowledge', 'llm'], {'api_type': 'openai', 'model': '${mainModel}', 'api_key': '${qwenKey}', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'enable_thinking': False})
s(c, ['main_chat', 'llm_module', 'llm'], {'api_type': 'openai', 'model': '${mainModel}', 'api_key': '${qwenKey}', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'enable_thinking': False})
s(c, ['main_chat', 'llm_module', 'prompt_name'], 'topic_reply_prompt')
s(c, ['conversation_manager', 'llm_module', 'llm'], {'api_type': 'openai', 'model': '${summaryModel}', 'api_key': '${deepseekKey}', 'base_url': 'https://api.deepseek.com/v1', 'temperature': 0.7, 'max_tokens': 8192, 'top_p': 0.9})
s(c, ['conversation_manager', 'llm_module', 'prompt_name'], 'summary_prompt')
s(c, ['tts', 'onnx_model_dir'], '${ttsModel}')
s(c, ['tts', 'reference_audio_dir'], '${refAudio}')
s(c, ['vision_module', 'vlm_module', 'vlm', 'api_key'], '${qwenKey}')
s(c, ['vision_module', 'vlm_module', 'vlm', 'model'], 'qwen3-vl-plus')
s(c, ['memory_manager', 'memory_searcher', 'llm_module', 'llm', 'api_key'], '${deepseekKey}')
s(c, ['memory_manager', 'memory_writer', 'llm_module', 'llm', 'api_key'], '${qwenKey}')
s(c, ['memory_manager', 'memory_writer', 'llm_module', 'llm', 'model'], '${mainModel}')
s(c, ['topic_extractor', 'llm_module', 'llm', 'api_key'], '${qwenKey}')
s(c, ['topic_extractor', 'llm_module', 'llm', 'model'], '${mainModel}')
s(c, ['activity_maker', 'llm', 'api_key'], '${qwenKey}')
s(c, ['activity_maker', 'llm', 'model'], '${mainModel}')
s(c, ['schedule', 'llm', 'api_key'], '${qwenKey}')
s(c, ['schedule', 'llm', 'model'], '${mainModel}')
s(c, ['crawler', 'llm_module', 'llm', 'api_key'], '${siliconflowKey}')

if '${amapKey}' and '${amapKey}' != '\${AMAP_KEY}':
    s(c, ['citywalk', 'amap', 'api_key'], '${amapKey}')

with open('$configFile'.replace('\\', '\\\\'), 'w') as f:
    json.dump(c, f, ensure_ascii=False, indent=4)
print('✅ 配置已保存')
"@

    # 修复 Python 脚本中的引号问题 — 写入临时文件执行
    $tmpScript = Join-Path $env:TEMP "agent_setup_config.py"
    $scriptBlock | Out-File -FilePath $tmpScript -Encoding utf8
    & $script:PYTHON_BIN $tmpScript 2>&1 | Out-Host
    Remove-Item $tmpScript -Force -ErrorAction SilentlyContinue

    Write-Info "✅ 配置完成: $configFile"
}

# ═══════════════════════════════════════════════════════════
# 5. 防火墙配置 (最低权限: UAC 提权)
# ═══════════════════════════════════════════════════════════

function Set-FirewallRule {
    param([int]$Port)
    Write-Header "防火墙配置"

    # 检查是否已存在规则
    $existing = netsh advfirewall firewall show rule name="AgentLuo Server TCP $Port" 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing -match "Rule Name") {
        Write-Info "端口 $Port 已在 Windows 防火墙中放行"
        return
    }

    if (-not $script:IsAdmin) {
        Write-Warn "需要管理员权限来修改防火墙规则"
        Write-Warn "正在请求管理员权限..."
        Write-Warn "请在弹出的 UAC 对话框中点击「是」"

        # 重新以管理员身份运行
        $scriptPath = $MyInvocation.MyCommand.Path
        if (-not $scriptPath) { $scriptPath = Join-Post $PWD "setup_server.ps1" }

        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command & {
            Write-Host '配置防火墙...' -ForegroundColor Cyan
            netsh advfirewall firewall add rule name='AgentLuo Server TCP $Port' dir=in action=allow protocol=TCP localport=$Port
            Write-Host '✅ 防火墙规则已添加' -ForegroundColor Green
            pause
        }" -Wait
    } else {
        Write-Info "添加防火墙规则: AgentLuo Server TCP $Port"
        netsh advfirewall firewall add rule name="AgentLuo Server TCP $Port" dir=in action=allow protocol=TCP localport=$Port
        if ($LASTEXITCODE -eq 0) {
            Write-Info "✅ Windows 防火墙已放行端口 $Port"
        } else {
            Write-Warn "防火墙规则添加失败，请手动放行端口 $Port"
        }
    }
}

# ═══════════════════════════════════════════════════════════
# 5b. SakuraFrp 内网穿透隧道配置
# ═══════════════════════════════════════════════════════════

function Set-SakuraFrpTunnel {
    param([int]$Port)
    Write-Header "SakuraFrp 内网穿透"

    $token = $script:SakuraToken
    $name = $script:SakuraName
    if ([string]::IsNullOrEmpty($token)) { Write-Warn "未提供 API Token，跳过"; return }

    # 构造请求体
    $body = @{
        name       = $name
        type       = "tcp"
        local_ip   = "127.0.0.1"
        local_port = $Port
        proxy_protocol = $false
    } | ConvertTo-Json
    if (-not [string]::IsNullOrEmpty($script:SakuraNode)) {
        $body = @{
            name       = $name
            type       = "tcp"
            local_ip   = "127.0.0.1"
            local_port = $Port
            node       = [int]$script:SakuraNode
            proxy_protocol = $false
        } | ConvertTo-Json
    }

    Write-Info "正在通过 SakuraFrp API 创建 TCP 隧道..."

    try {
        $resp = Invoke-RestMethod -Uri "https://api.natfrp.com/v1/tunnel/create" `
            -Method Post `
            -Headers @{ Authorization = $token } `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 15
    } catch {
        Write-Warn "SakuraFrp API 调用失败: $_"
        Write-Warn "请手动在 https://www.natfrp.com/ 创建隧道"
        return
    }

    $tunnelId = $resp.id
    $remotePort = $resp.remote_port
    $remoteAddr = $resp.remote_addr

    if (-not $tunnelId -or $tunnelId -eq 0) {
        $errMsg = if ($resp.error) { $resp.error } else { "未知错误" }
        Write-Warn "SakuraFrp 隧道创建失败: $errMsg"
        return
    }

    Write-Info "✅ 隧道创建成功！"
    Write-Info "  隧道 ID: $tunnelId"
    Write-Info "  远程地址: $remoteAddr"

    # 保存隧道信息到配置文件
    & $script:PYTHON_BIN -c @"
import json
try:
    with open(r'$($script:SERVER_DIR)\config\config.json') as f:
        c = json.load(f)
except: c = {}
c['sakurafrp'] = {'tunnel_id': $tunnelId, 'remote_addr': '$remoteAddr', 'remote_port': '$remotePort', 'local_port': $Port}
with open(r'$($script:SERVER_DIR)\config\config.json', 'w') as f:
    json.dump(c, f, ensure_ascii=False, indent=4)
print('✅ 隧道信息已保存')
"@ 2>$null

    # 下载 frpc
    $frpcDir = Join-Path $script:SERVER_DIR "frpc"
    New-Item -ItemType Directory -Force -Path $frpcDir | Out-Null
    $frpcExe = Join-Path $frpcDir "frpc.exe"

    if (-not (Test-Path $frpcExe)) {
        Write-Info "下载 frpc 客户端..."
        $downloadUrl = "https://cdn.natfrp.com/frpc_windows_amd64.zip"
        $zipPath = Join-Path $frpcDir "frpc.zip"

        try {
            Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -TimeoutSec 30
            Expand-Archive -Path $zipPath -DestinationPath $frpcDir -Force
            Remove-Item $zipPath -Force
            Write-Info "✅ frpc 已下载: $frpcExe"
        } catch {
            Write-Warn "frpc 下载失败: $_"
            Write-Warn "请手动下载: $downloadUrl"
            Write-Warn "隧道 ID: $tunnelId 可在 https://www.natfrp.com/ 查看"
        }
    } else {
        Write-Info "frpc 已存在: $frpcExe"
    }

    # 生成 frpc 配置
    $frpcIni = Join-Path $frpcDir "frpc.ini"
    @"
[common]
token = $token
server_addr = $remoteAddr
admin_addr = 127.0.0.1
admin_port = 7400

[$name]
type = tcp
local_ip = 127.0.0.1
local_port = $Port
remote_port = $remotePort
"@ | Out-File -FilePath $frpcIni -Encoding ascii
    Write-Info "✅ frpc 配置已生成: $frpcIni"

    # 创建启动脚本
    $startScript = Join-Path $frpcDir "start_frpc.ps1"
    @"
`$frpcExe = Join-Path `$PSScriptRoot "frpc.exe"
`$frpcIni = Join-Path `$PSScriptRoot "frpc.ini"
Start-Process -NoNewWindow -FilePath `$frpcExe -ArgumentList "-c `$frpcIni"
"@ | Out-File -FilePath $startScript -Encoding ascii
    Write-Info "✅ frpc 启动脚本已生成: $startScript"

    Write-Info ""
    Write-Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Info "  SakuraFrp 隧道配置完成！"
    Write-Info "  远程地址: $remoteAddr"
    Write-Info "  本地端口映射: 127.0.0.1:$Port → $remoteAddr"
    Write-Info "  客户端访问地址: $($remoteAddr -replace ':\d+$'):$remotePort"
    Write-Info "  管理面板: https://www.natfrp.com/"
    Write-Info "  启动隧道: $frpcExe -c $frpcIni"
    Write-Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ═══════════════════════════════════════════════════════════
# 5c. 域名绑定 & Caddy 自动 HTTPS
# ═══════════════════════════════════════════════════════════

function Set-DomainBinding {
    param([int]$Port)
    $domain = $script:ServerDomain
    if ([string]::IsNullOrEmpty($domain)) { return }
    Write-Header "域名绑定 & HTTPS 自动配置"

    Write-Info "域名: $domain"
    Write-Info "目标端口: $Port"

    # DNS 验证
    try {
        $resolved = [System.Net.Dns]::GetHostAddresses($domain) | Select-Object -First 1
        if ($resolved) {
            Write-Info "DNS 解析: $domain → $($resolved.IPAddressToString)"
            $localIps = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
                ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
                Where-Object { $_.Address.AddressFamily -eq 'InterNetwork' } |
                ForEach-Object { $_.Address.IPAddressToString }
            if ($localIps -notcontains $resolved.IPAddressToString) {
                Write-Warn "域名解析到 $($resolved.IPAddressToString)，与本机 IP 不匹配"
                Write-Warn "请确保 DNS 已指向本机"
                $confirm = Read-Input "是否继续？" "Y"
                if ($confirm -ne "Y") { return }
            }
        }
    } catch {
        Write-Warn "DNS 解析失败，请确认域名 $domain 已正确配置"
        $skip = Read-Input "是否继续？" "N"
        if ($skip -ne "Y") { return }
    }

    # Caddy 安装（Windows 上提示手动配置）
    if ($script:AutoHttps -ne "Y") {
        Write-Info "跳过 HTTPS 自动配置"
        Write-Info "请自行配置反向代理将 https://$domain 指向 127.0.0.1:$Port"
        return
    }

    Write-Warn "Windows 上 Caddy 自动安装未实现，请手动安装:"
    Write-Warn "  1. 下载: https://caddyserver.com/download"
    Write-Warn "  2. 创建 Caddyfile:"
    Write-Warn "  ─────────────────────────────"
    Write-Warn "  $domain {"
    Write-Warn "      reverse_proxy 127.0.0.1:$Port"
    Write-Warn "      encode gzip"
    Write-Warn "  }"
    Write-Warn "  ─────────────────────────────"
    Write-Warn "  3. 运行: caddy run"
    Write-Info "   访问地址: https://$domain"

    # 生成 Caddyfile 示例
    $caddyDir = Join-Path $script:SERVER_DIR "caddy"
    New-Item -ItemType Directory -Force -Path $caddyDir | Out-Null
    $caddyFile = Join-Path $caddyDir "Caddyfile.example"
    @"
$domain {
    reverse_proxy 127.0.0.1:$Port
    encode gzip
    header {
        -Server
    }
}
"@ | Out-File -FilePath $caddyFile -Encoding ascii
    Write-Info "Caddyfile 示例已生成: $caddyFile"
}

# ═══════════════════════════════════════════════════════════
# 6. 连接信息
# ═══════════════════════════════════════════════════════════

function Show-ConnectionInfo {
    Write-Header "服务器连接信息"

    $configFile = Join-Path $script:SERVER_DIR "config\config.json"
    if (-not (Test-Path $configFile)) { Write-Warn "配置不存在"; return }

    # 解析配置并显示
    $tmpScript = Join-Path $env:TEMP "agent_show_info.py"
    @"
import json, socket, re
try:
    with open(r'$configFile') as f:
        c = json.load(f)
except: exit(0)

is_debug = c.get('is_debug', True)
mode_key = 'debug_config' if is_debug else 'release_config'
cfg = c.get(mode_key, {})
base_url = cfg.get('base_url', 'http://127.0.0.1:$DEFAULT_PORT')
m = re.search(r':(\d+)$', base_url)
port = m.group(1) if m else '$DEFAULT_PORT'
scheme = 'https' if 'https' in base_url else 'http'

print(f'\n  本地地址:    {base_url}')
try:
    hostname = socket.gethostname()
    seen = set()
    for info in socket.getaddrinfo(hostname, None):
        ip = info[4][0]
        if not ip.startswith('127.') and '.' in ip and ip not in seen:
            seen.add(ip)
            print(f'  局域网地址:  {scheme}://{ip}:{port}')
except: pass

print(f'  端口:        {port} (防火墙已放行)')
print(f'  调试模式:    {"是" if is_debug else "否"}')
print(f'  启动命令:    cd $($script:SERVER_DIR) && $($script:PYTHON_BIN) server_main.py')
"@ | Out-File -FilePath $tmpScript -Encoding utf8

    & $script:PYTHON_BIN $tmpScript 2>$null
    Remove-Item $tmpScript -Force -ErrorAction SilentlyContinue
}

# ═══════════════════════════════════════════════════════════
# 7. 启动服务
# ═══════════════════════════════════════════════════════════

function Start-Server {
    Write-Header "启动服务器"

    $ans = Read-Input "是否现在启动服务器？" "N"
    if ($ans -ne "Y") {
        Write-Info "手动启动命令:"
        Write-Info "  cd $script:SERVER_DIR"
        Write-Info "  $script:ACTIVATE_CMD"
        Write-Info "  python server_main.py"
        return
    }

    Write-Info "启动服务器..."
    if ($script:ServerDomain) {
        Write-Info "域名: https://$($script:ServerDomain)"
    }

    # 先启动 frpc 隧道（如果已配置）
    $frpcExe = Join-Path $script:SERVER_DIR "frpc\frpc.exe"
    $frpcIni = Join-Path $script:SERVER_DIR "frpc\frpc.ini"
    if (Test-Path $frpcExe -and (Test-Path $frpcIni)) {
        Write-Info "启动 SakuraFrp 隧道..."
        Start-Process -NoNewWindow -FilePath $frpcExe -ArgumentList "-c `"$frpcIni`""
        Write-Info "frpc 已启动（后台运行）"
    }

    Set-Location $script:SERVER_DIR
    Invoke-Expression "$script:PYTHON_BIN server_main.py"
}

# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

function Main {
    Write-Host @"
${CYAN}============================================================
  洛天依 Agent 服务端 — 一键安装 & 配置向导 (Windows)
============================================================
"@ -ForegroundColor Cyan

    if ($Quick) {
        Check-Prerequisites
        Sync-Repo
        Install-Environment
        # 复制模板配置
        $cfg = Join-Path $script:SERVER_DIR "config\config.json"
        $tpl = Join-Path $script:SERVER_DIR "config\config.json.template"
        if (-not (Test-Path $cfg)) {
            if (Test-Path $tpl) { Copy-Item $tpl $cfg; Write-Info "已从模板创建配置文件" }
        }
        Show-ConnectionInfo
        Write-Info "✅ 快速安装完成"
        return
    }

    Check-Privilege
    Check-Prerequisites
    Sync-Repo

    if (-not $NoEnv) { Install-Environment }

    if ($ConfigOnly) {
        Invoke-ConfigWizard
        Show-ConnectionInfo
        return
    }

    Invoke-ConfigWizard

    if ($script:doFirewall -eq "Y") {
        try { Set-FirewallRule -Port ([int]$script:port) } catch { Write-Warn "防火墙配置失败: $_" }
    }

    if ($script:doSakura -eq "Y") {
        try { Set-SakuraFrpTunnel -Port ([int]$script:port) } catch { Write-Warn "SakuraFrp 配置失败: $_" }
    }

    if ($script:hasDomain -eq "Y" -and $script:ServerDomain) {
        try { Set-DomainBinding -Port ([int]$script:port) } catch { Write-Warn "域名配置失败: $_" }
    }

    Show-ConnectionInfo
    Start-Server
}

# 入口
Main
