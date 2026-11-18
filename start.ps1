# 由 一键启动.bat 调用。不要直接依赖终端里的激活状态。
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Resolve-Python {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 14) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ File = $py.Source; UseLauncher = $true }
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 14) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ File = $python.Source; UseLauncher = $false }
        }
    }
    throw "需要 Python 3.9 到 3.13，并加入 PATH。安装时勾选 Add python.exe to PATH。"
}

function Test-PlaceholderGroup {
    param([string]$Path)
    $text = [System.IO.File]::ReadAllText($Path)
    return $text.Contains("示例项目群")
}

try {
    $python = Resolve-Python
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "第一次运行，正在创建虚拟环境..."
        if ($python.UseLauncher) {
            & $python.File -3 -m venv .venv
        }
        else {
            & $python.File -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) {
            throw "创建虚拟环境失败。"
        }
    }

    $stamp = Join-Path $PSScriptRoot ".venv\.requirements.stamp"
    $requirements = Join-Path $PSScriptRoot "requirements.txt"
    $needInstall = -not (Test-Path -LiteralPath $stamp)
    if (-not $needInstall) {
        $needInstall = (Get-Item -LiteralPath $stamp).LastWriteTimeUtc -lt (Get-Item -LiteralPath $requirements).LastWriteTimeUtc
    }
    if ($needInstall) {
        Write-Host "正在安装依赖。微信 3.9 的 wxauto 要从 GitHub 下载，请保持联网。"
        & $venvPython -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) {
            throw "安装依赖失败。"
        }
        New-Item -ItemType File -Path $stamp -Force | Out-Null
    }

    $config = Join-Path $PSScriptRoot "config.yaml"
    $example = Join-Path $PSScriptRoot "config.example.yaml"
    if (-not (Test-Path -LiteralPath $config)) {
        Copy-Item -LiteralPath $example -Destination $config
        Write-Host "还没有 config.yaml，已用示例生成。"
    }
    if (Test-PlaceholderGroup $config) {
        Write-Host "请把群名改成微信左侧会话列表里的名字，保存并关闭记事本。"
        Start-Process -FilePath notepad.exe -ArgumentList $config -Wait
    }
    if (Test-PlaceholderGroup $config) {
        throw "还没有填写真实群名，已停止。改好 config.yaml 后再双击一次。"
    }

    Write-Host "开始读取群消息。请保持微信已登录，主窗口不要关掉。按 Ctrl+C 结束。"
    & $venvPython -m wxgroup watch
    if ($LASTEXITCODE -ne 0) {
        throw "读取结束，退出码 $LASTEXITCODE。详情看 logs\wxgroup.log"
    }
}
catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ""
    Read-Host "按回车关闭窗口"
}
