#Requires -Version 5.0
# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    MiyoQian 一键部署脚本 (Windows 版)
.DESCRIPTION
    自动完成：打包 → 上传 → 服务器配置 → 启动
.USAGE
    1. 首次使用: 右键 "使用 PowerShell 运行"
    2. 或在 PowerShell 中执行: .\deploy.ps1
    3. 如需跳过交互: 编辑 deploy.config.json 后执行 .\deploy.ps1 -NonInteractive
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [string]$ConfigFile = "deploy.config.json"
)

$ErrorActionPreference = "Stop"

# ========================================
# 配置加载
# ========================================
function Load-Config {
    param([string]$ConfigPath)
    if (Test-Path $ConfigPath) {
        return Get-Content $ConfigPath -Raw | ConvertFrom-Json
    }
    return $null
}

function Save-Config {
    param($Config, [string]$ConfigPath)
    $Config | ConvertTo-Json -Depth 10 | Set-Content $ConfigPath -Encoding UTF8
}

# ========================================
# 交互式输入
# ========================================
function Ask {
    param(
        [string]$Prompt,
        [string]$Default = "",
        [switch]$Required
    )
    $display = if ($Default) { "$Prompt [$Default]: " } else { "$Prompt: " }
    while ($true) {
        $input = Read-Host $display
        if ($input) { return $input }
        if (-not $Required) { return $Default }
        Write-Host "此项不能为空，请重新输入。" -ForegroundColor Red
    }
}

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    $hint = if ($Default) { "Y/n" } else { "y/N" }
    while ($true) {
        $input = Read-Host "$Prompt [$hint]"
        if (-not $input) { return $Default }
        switch ($input.ToLower()) {
            "y" { return $true }
            "yes" { return $true }
            "n" { return $false }
            "no" { return $false }
        }
    }
}

# ========================================
# 步骤 1: 打包
# ========================================
function Build-Package {
    $projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location $projectRoot
    
    Write-Host "`n📦 [1/4] 打包项目..." -ForegroundColor Cyan
    
    # 检查 git 仓库
    if (-not (Test-Path ".git")) {
        Write-Host "❌ 当前目录不是 git 仓库，请先在项目根目录执行 git init" -ForegroundColor Red
        exit 1
    }
    
    $outputZip = "MiyoQian-deploy.zip"
    if (Test-Path $outputZip) { Remove-Item $outputZip }
    
    # 使用 git archive 打包（自动遵守 .gitignore）
    git archive --format=zip --output=$outputZip HEAD
    
    if (-not (Test-Path $outputZip)) {
        Write-Host "❌ 打包失败" -ForegroundColor Red
        exit 1
    }
    
    $sizeMB = [math]::Round((Get-Item $outputZip).Length / 1MB, 2)
    Write-Host "✅ 打包完成: $outputZip ($sizeMB MB)" -ForegroundColor Green
    return (Resolve-Path $outputZip).Path
}

# ========================================
# 步骤 2: 收集服务器信息
# ========================================
function Get-ServerConfig {
    $config = Load-Config $ConfigFile
    
    if ($NonInteractive -and $config) {
        Write-Host "`n⚙️  使用配置文件: $ConfigFile" -ForegroundColor Cyan
        return $config
    }
    
    Write-Host "`n🔧 [2/4] 配置服务器信息" -ForegroundColor Cyan
    
    $existing = $config
    $server = @{
        host      = Ask "服务器 IP 地址" ($existing.host)
        port      = [int](Ask "SSH 端口" ($existing.port -as [string]) "22")
        user      = Ask "SSH 用户名" ($existing.user)
        password  = (Ask "SSH 密码（留空则使用密钥登录）" "" $false)
        deployDir = Ask "服务器部署目录" ($existing.deployDir) "/opt/MiyoQian"
        pythonBin = Ask "服务器 Python 路径" ($existing.pythonBin) "python3"
    }
    
    # 测试连接
    Write-Host "`n🔍 测试 SSH 连接..." -ForegroundColor Yellow
    $sshTestCmd = "ssh -o ConnectTimeout=10 -o BatchMode=yes -p $($server.port) $($server.user)@$($server.host) 'echo OK'"
    try {
        $testResult = Invoke-Expression $sshTestCmd 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️  SSH 连接失败，可能需要配置密钥或密码。将在上传时提示。" -ForegroundColor Yellow
        } else {
            Write-Host "✅ SSH 连接成功" -ForegroundColor Green
        }
    } catch {
        Write-Host "⚠️  SSH 连接测试异常：$($_.Exception.Message)" -ForegroundColor Yellow
    }
    
    # 保存配置
    $config = [pscustomobject]$server
    $config | ConvertTo-Json -Depth 10 | Set-Content $ConfigFile -Encoding UTF8
    Write-Host "💾 配置已保存到 $ConfigFile（下次可直接使用 -NonInteractive）" -ForegroundColor Gray
    
    return $config
}

# ========================================
# 步骤 3: 上传文件
# ========================================
function Upload-ToServer {
    param(
        [string]$ZipPath,
        $Server
    )
    
    Write-Host "`n🚀 [3/4] 上传到服务器 $($Server.host):$($Server.port) ..." -ForegroundColor Cyan
    
    $remoteZip = "/tmp/$(Split-Path $ZipPath -Leaf)"
    
    # 上传部署脚本（作为远程执行用）
    $localDeployScript = Join-Path (Split-Path $ZipPath) "remote_deploy.sh"
    if (-not (Test-Path $localDeployScript)) {
        Write-Host "❌ 找不到 remote_deploy.sh" -ForegroundColor Red
        exit 1
    }
    
    $remoteDeployScript = "/tmp/remote_deploy.sh"
    
    if ($Server.password) {
        # 使用密码认证
        Write-Host "🔐 使用密码认证上传..." -ForegroundColor Yellow
        scp -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -P $Server.port $ZipPath "$($Server.user)@$($Server.host):$remoteZip"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ 上传失败" -ForegroundColor Red
            exit 1
        }
        scp -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -P $Server.port $localDeployScript "$($Server.user)@$($Server.host):$remoteDeployScript"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ 脚本上传失败" -ForegroundColor Red
            exit 1
        }
    } else {
        # 使用密钥认证
        Write-Host "🔑 使用密钥认证上传..." -ForegroundColor Yellow
        scp -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -P $Server.port $ZipPath "$($Server.user)@$($Server.host):$remoteZip"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ 上传失败，请检查 SSH 密钥" -ForegroundColor Red
            exit 1
        }
        scp -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -P $Server.port $localDeployScript "$($Server.user)@$($Server.host):$remoteDeployScript"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ 脚本上传失败" -ForegroundColor Red
            exit 1
        }
    }
    
    Write-Host "✅ 上传完成" -ForegroundColor Green
    return @{ remoteZip = $remoteZip; remoteScript = $remoteDeployScript }
}

# ========================================
# 步骤 4: 远程部署
# ========================================
function Deploy-Remote {
    param(
        $Server,
        [string]$RemoteZip,
        [string]$RemoteScript
    )
    
    Write-Host "`n⚙️  [4/4] 在服务器上执行部署..." -ForegroundColor Cyan
    Write-Host "（这可能需要几分钟，请耐心等待）" -ForegroundColor Gray
    
    $sshCmd = @"
ssh -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -p $($Server.port) $($Server.user)@$($Server.host) `"
export DEPLOY_DIR='$($Server.deployDir)'
export PYTHON_BIN='$($Server.pythonBin)'
export ZIP_FILE='$RemoteZip'
export DEPLOY_SCRIPT='$RemoteScript'
export NON_INTERACTIVE='$($NonInteractive.IsPresent)'
bash $RemoteScript
`"
"@
    
    # 使用 Invoke-Expression 执行
    $sshArgs = @(
        "-o", "ConnectTimeout=30",
        "-o", "StrictHostKeyChecking=accept-new",
        "-p", $Server.port,
        "$($Server.user)@$($Server.host)"
    )
    
    $remoteCommand = @"
export DEPLOY_DIR='$($Server.deployDir)' && export PYTHON_BIN='$($Server.pythonBin)' && export ZIP_FILE='$RemoteZip' && export NON_INTERACTIVE='$($NonInteractive.IsPresent)' && bash $RemoteScript
"@
    
    & ssh @sshArgs $remoteCommand
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 远程部署执行失败" -ForegroundColor Red
        exit 1
    }
}

# ========================================
# 主流程
# ========================================
function Show-Start {
    Clear-Host
    Write-Host @"

╔══════════════════════════════════════════════╗
║           MiyoQian 一键部署脚本             ║
║   NoneBot2 米游社签到机器人                 ║
╚══════════════════════════════════════════════╝

"@ -ForegroundColor Magenta
}

function Show-Complete {
    param($Server, $DeployDir)
    Write-Host @"

╔══════════════════════════════════════════════╗
║               🎉 部署完成！                 ║
╚══════════════════════════════════════════════╝

"@ -ForegroundColor Green
    
    Write-Host "📋 后续手动步骤：" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1️⃣  配置 QQ 客户端（NapCat / Lagrange / go-cqhttp）"
    Write-Host "      反向 WebSocket 地址: ws://127.0.0.1:8080/onebot/v11/ws"
    Write-Host ""
    Write-Host "  2️⃣  QQ 私聊机器人发送: /myq login"
    Write-Host "      扫描二维码完成米游社账号登录"
    Write-Host ""
    Write-Host "  3️⃣  首次测试: /myq run"
    Write-Host "      确认签到功能正常工作"
    Write-Host ""
    Write-Host "  4️⃣  开启定时签到"
    Write-Host "      编辑 $DeployDir/nonebot_plugin_mysdaily/config.yaml"
    Write-Host "      设置 schedule.enable: true"
    Write-Host ""
    Write-Host "  5️⃣  查看机器人日志"
    Write-Host "      ssh $($Server.user)@$($Server.host) → screen -r myq"
    Write-Host ""
    Write-Host "  6️⃣  服务器上常用命令"
    Write-Host "      # 查看状态"
    Write-Host "      screen -r myq"
    Write-Host ""
    Write-Host "      # 重新登录"
    Write-Host "      cd $DeployDir && source .venv/bin/activate && python bot.py"
    Write-Host ""
    Write-Host "      # 查看 systemd 状态（如果使用了 systemd）"
    Write-Host "      systemctl status miyouqian"
    Write-Host "      journalctl -u miyouqian -f"
    Write-Host ""
}

# 主函数
Show-Start

# 步骤 1: 打包
$zipPath = Build-Package

# 步骤 2: 获取服务器配置
$server = Get-ServerConfig

# 步骤 3: 上传
$uploadResult = Upload-ToServer -ZipPath $zipPath -Server $server

# 步骤 4: 远程部署
Deploy-Remote -Server $server -RemoteZip $uploadResult.remoteZip -RemoteScript $uploadResult.remoteScript

# 完成
Show-Complete -Server $server -DeployDir $server.deployDir
