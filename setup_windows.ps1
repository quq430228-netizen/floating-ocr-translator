$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[1/3] 正在创建 Python 虚拟环境 (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

Write-Host "[2/3] 正在安装依赖包..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "[3/3] 正在创建桌面快捷方式并启动翻译悬浮窗..." -ForegroundColor Cyan
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "翻译悬浮窗.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($lnkPath)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = "`"$PSScriptRoot\启动翻译悬浮窗.vbs`""
$sc.WorkingDirectory = $PSScriptRoot
$iconPath = Join-Path $PSScriptRoot "app_icon.ico"
if (Test-Path $iconPath) {
    $sc.IconLocation = "$iconPath,0"
}
$sc.Save()

Start-Process -FilePath "wscript.exe" -ArgumentList "`"$PSScriptRoot\启动翻译悬浮窗.vbs`""
Write-Host "安装完成！桌面已生成「翻译悬浮窗」快捷方式，悬浮窗已启动。" -ForegroundColor Green
