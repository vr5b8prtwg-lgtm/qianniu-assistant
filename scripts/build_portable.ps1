# 千牛工作台助手 - 便携版打包脚本
# 作用：把 Python 运行时 + 依赖 + 程序代码打包到 dist\千牛工作台助手，并压缩成 zip
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Root
$PyDir = "C:\Users\24620\AppData\Local\Programs\Python\Python312"
$VenvSp = Join-Path $Root ".venv\Lib\site-packages"
$Dist = Join-Path $Root "dist\千牛工作台助手"

if (-not (Test-Path (Join-Path $PyDir "python.exe"))) { throw "未找到 Python 安装目录：$PyDir" }
if (-not (Test-Path $VenvSp)) { throw "未找到虚拟环境依赖：$VenvSp" }

Write-Host "=== 清理旧打包目录 ==="
if (Test-Path $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force }

Write-Host "1/6 复制 Python 运行时 ..."
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "runtime\python") | Out-Null
robocopy $PyDir (Join-Path $Dist "runtime\python") /E /NFL /NDL /NJH /NJS /NP /XD Doc include libs Scripts test site-packages __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 Python 失败，退出码 $LASTEXITCODE" }

Write-Host "2/6 复制依赖库（裁剪 PySide6 用不到的模块）..."
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "runtime\python\Lib\site-packages") | Out-Null
robocopy $VenvSp (Join-Path $Dist "runtime\python\Lib\site-packages") /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ pip _pytest pytest pygments | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制依赖失败，退出码 $LASTEXITCODE" }

Write-Host "3/6 裁剪 PySide6 不需要的模块（WebEngine/Quick/QML/3D/多媒体等）..."
$Pyside = Join-Path $Dist "runtime\python\Lib\site-packages\PySide6"
foreach ($d in @("qml","metatypes","typesystems","include","glue","doc","scripts","examples")) {
    $p = Join-Path $Pyside $d
    if (Test-Path $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}
$tr = Join-Path $Pyside "translations"
if (Test-Path $tr) {
    Get-ChildItem $tr -File | Where-Object { $_.Name -notmatch "zh_CN" } | Remove-Item -Force
}
$delPatterns = @(
    "Qt6WebEngine*","Qt6Quick*","Qt6Qml*","Qt6Designer*","Qt6Multimedia*",
    "Qt6Charts*","Qt6DataVisualization*","Qt6Pdf*","Qt6Quick3D*","Qt6WebView*",
    "avcodec*","avformat*","avutil*","swresample*","swscale*","Qt6VirtualKeyboard*",
    "Qt6RemoteObjects*","Qt6Scxml*","Qt6Sensors*","Qt6SerialPort*","Qt6StateMachine*",
    "Qt6TextToSpeech*","Qt6WebChannel*","Qt6WebSockets*","Qt6Bluetooth*","Qt6Nfc*",
    "Qt6Positioning*","Qt6Location*","Qt6MultimediaWidgets*","Qt6Sql*","Qt6Test*",
    "Qt6Concurrent*","Qt6Xml*","Qt6DBus*","Qt6OpenGLWidgets*","Qt6PrintSupport*",
    "QtWebEngine*","QtQuick*","QtQml*","QtMultimedia*","QtPdf*","QtDesigner*",
    "Qt3D*","QtCharts*","QtDataVisualization*"
)
foreach ($pat in $delPatterns) {
    Get-ChildItem $Pyside -File -Filter $pat -ErrorAction SilentlyContinue | Remove-Item -Force
}
$res = Join-Path $Pyside "resources"
if (Test-Path $res) {
    Get-ChildItem $res -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "webengine|qtwebengine" } | Remove-Item -Force
}

Write-Host "4/6 复制程序代码 ..."
foreach ($item in @("app","config.json","README.md")) {
    Copy-Item -Path (Join-Path $Root $item) -Destination $Dist -Recurse -Force
}
Copy-Item -Path (Join-Path $Root "packaging\使用说明.txt") -Destination $Dist -Force

Write-Host "5/6 生成启动脚本 ..."
$batLines = @(
    '@echo off',
    'cd /d "%~dp0"',
    '"runtime\python\python.exe" -m app',
    'if errorlevel 1 pause'
)
$bat = $batLines -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $Dist "启动助手.bat"), $bat, (New-Object System.Text.ASCIIEncoding))

Write-Host "6/6 压缩为 zip ..."
$zipPath = Join-Path $Root "dist\千牛工作台助手-便携版.zip"
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -Path $Dist -DestinationPath $zipPath -CompressionLevel Optimal

$size = (Get-Item $zipPath).Length / 1MB
Write-Host ("完成！zip 大小：{0:N1} MB" -f $size)
Write-Host ("解压目录：{0}" -f $Dist)