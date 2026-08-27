# 千牛工作台助手 - 一键环境准备脚本
# 作用：检测/安装 Python 3.11 或 3.12 -> 创建虚拟环境 -> 安装依赖 -> 下载 Playwright 浏览器
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Root

function Find-Python {
    foreach ($v in 3.12, 3.11) {
        try { $out = & py -$v -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() } } catch {}
    }
    try { $out = & python -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() } } catch {}
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python312\python.exe", "C:\Python311\python.exe"
    )) { if (Test-Path $p) { return $p } }
    return $null
}

function Install-Python {
    Write-Host "未找到可用的 Python，尝试自动安装 Python 3.12 ..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $p = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
            if (Test-Path $p) { return $p }
        }
    }
    $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    Write-Host "下载 $url ..."
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    Write-Host "静默安装中（用户目录，不加入系统 PATH）..."
    $instArgs = "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0"
    Start-Process -FilePath $installer -ArgumentList $instArgs -Wait -WindowStyle Hidden
    $p = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $p)) { throw "Python 安装失败：$p 不存在" }
    return $p
}

Write-Host "=== 千牛工作台助手 环境准备 ==="
$py = Find-Python
if (-not $py) { $py = Install-Python }
Write-Host "使用 Python: $py"
& $py --version

$venv = Join-Path $Root ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "创建虚拟环境 .venv ..."
    & $py -m venv $venv
}
$pip = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $pip)) { throw "虚拟环境创建失败" }

Write-Host "升级 pip ..."
& $pip -m pip install --upgrade pip
Write-Host "安装依赖（PySide6 / uiautomation / rapidocr / playwright 等，首次约需几分钟）..."
& $pip -m pip install -r (Join-Path $Root "requirements.txt")

Write-Host "下载 Playwright 浏览器（Chromium）..."
& $pip -m playwright install chromium

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Green
Write-Host "运行方式："
Write-Host "  cd `"$Root`""
Write-Host "  .\.venv\Scripts\python.exe -m app"
Write-Host "首次使用：点面板上「打开/登录闲鱼」扫码登录一次即可。"