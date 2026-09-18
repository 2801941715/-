# =============================================================================
#  install.ps1 —— 构建（可选）+ 安装 + 一键体检
#
#  用法：
#      pwsh -File .\android\install.ps1              # 安装已构建的 APK 并体检
#      pwsh -File .\android\install.ps1 -Build       # 先构建再安装
#      pwsh -File .\android\install.ps1 -Serial XXX  # 指定设备
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Build,
    [string]$Serial,
    [int]$Port = 8710
)

$ErrorActionPreference = "Stop"
$AndroidDir = $PSScriptRoot
$ProjectRoot = Split-Path $AndroidDir -Parent
$Apk = Join-Path $AndroidDir "dist\damai-assistant-debug.apk"

function Get-Adb {
    $found = Get-Command adb -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($envName in @("ANDROID_HOME", "ANDROID_SDK_ROOT")) {
        $r = [Environment]::GetEnvironmentVariable($envName)
        if ($r) {
            $p = Join-Path $r "platform-tools\adb.exe"
            if (Test-Path $p) { return $p }
        }
    }
    $p = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    if (Test-Path $p) { return $p }
    throw "未找到 adb，请安装 Android Platform Tools 并加入 PATH。"
}

$adb = Get-Adb

if ($Build -or -not (Test-Path $Apk)) {
    Write-Host "== 构建 APK ==" -ForegroundColor Cyan
    & pwsh -NoProfile -File (Join-Path $AndroidDir "build.ps1")
    if ($LASTEXITCODE -ne 0) { throw "构建失败" }
}

if (-not (Test-Path $Apk)) { throw "未找到 APK: $Apk" }

$adbArgs = @()
if ($Serial) { $adbArgs = @("-s", $Serial) }

Write-Host "`n== 设备 ==" -ForegroundColor Cyan
& $adb @adbArgs devices -l

Write-Host "`n== 安装 ==" -ForegroundColor Cyan
& $adb @adbArgs install -r $Apk
if ($LASTEXITCODE -ne 0) { throw "安装失败（可尝试 adb uninstall com.damai.assistant 后重装）" }

Write-Host "`n== 启动应用 ==" -ForegroundColor Cyan
& $adb @adbArgs shell am start -n "com.damai.assistant/.MainActivity"

Write-Host "`n== 建立调试端口转发 ==" -ForegroundColor Cyan
& $adb @adbArgs forward "tcp:$Port" "tcp:$Port"

Write-Host @"

安装完成。接下来请在手机上：
  1. 打开「大麦抢票助手」
  2. 点击「开启无障碍权限」并在系统列表中启用
  3. 返回 App，确认状态为「已开启」

然后在电脑上运行远程调试体检：
  python tools/damai_remote.py doctor --port $Port

"@ -ForegroundColor Green
