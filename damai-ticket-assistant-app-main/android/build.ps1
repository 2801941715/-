# =============================================================================
#  build.ps1 —— 离线命令行构建大麦抢票助手 APK
#
#  只用 Android SDK 的 build-tools + JDK 自带工具，不依赖 Gradle / 网络：
#    aapt2 compile/link  ->  javac  ->  d8  ->  打包  ->  zipalign  ->  apksigner
#
#  用法（在 android 目录下执行）：
#      pwsh -File .\build.ps1
#      pwsh -File .\build.ps1 -Clean
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Clean,
    [string]$OutDir,
    [string]$BuildType = "debug",
    # 允许复用同一构建链编译其它 app 目录（例如 mockapp 测试替身）
    [string]$AppDirName = "app",
    [string]$ApkName
)

$ErrorActionPreference = "Stop"

$AndroidDir = $PSScriptRoot
$AppDir     = Join-Path $AndroidDir $AppDirName
$WorkDir    = Join-Path $AndroidDir "build"
$JavaSrc    = Join-Path $AppDir  "java"
$ResDir     = Join-Path $AppDir  "res"
$Manifest   = Join-Path $AppDir  "AndroidManifest.xml"

if (-not $OutDir) { $OutDir = Join-Path $AndroidDir "dist" }

# ---------------------------------------------------------------- 工具定位
function Find-JdkHome {
    $candidates = @(
        $env:JAVA_HOME,
        "C:\Program Files\Android\Android Studio\jbr",
        "C:\Program Files\Java\jdk*",
        "C:\Program Files\Eclipse Adoptium\jdk*"
    )
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        $expanded = Get-ChildItem -Path $c -Directory -ErrorAction SilentlyContinue |
                    Select-Object -First 1 -ExpandProperty FullName
        foreach ($path in @($c, $expanded)) {
            if ($path -and (Test-Path (Join-Path $path "bin\javac.exe"))) { return $path }
        }
    }
    throw "未找到 JDK（需要 javac）。请设置 JAVA_HOME，或安装 Android Studio（自带 jbr）。"
}

function Find-SdkRoot {
    $candidates = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "$env:LOCALAPPDATA\Android\Sdk")
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c "platforms"))) { return $c }
    }
    throw "未找到 Android SDK。请设置 ANDROID_HOME，或安装 Android SDK 命令行工具。"
}

function Find-BuildTools([string]$Sdk) {
    $btRoot = Join-Path $Sdk "build-tools"
    if (-not (Test-Path $btRoot)) { throw "未找到 build-tools 目录: $btRoot" }
    $ver = Get-ChildItem $btRoot -Directory |
           Sort-Object { [version]($_.Name -replace '[^0-9.]','') } -Descending |
           Select-Object -First 1
    if (-not $ver) { throw "build-tools 为空: $btRoot" }
    return $ver.FullName
}

function Find-PlatformJar([string]$Sdk) {
    $platRoot = Join-Path $Sdk "platforms"
    $plat = Get-ChildItem $platRoot -Directory |
            Sort-Object Name -Descending | Select-Object -First 1
    if (-not $plat) { throw "未找到 platforms: $platRoot" }
    $jar = Join-Path $plat.FullName "android.jar"
    if (-not (Test-Path $jar)) { throw "未找到 android.jar: $jar" }
    return $jar
}

$JdkHome   = Find-JdkHome
$SdkRoot   = Find-SdkRoot
$BuildTools = Find-BuildTools $SdkRoot
$AndroidJar = Find-PlatformJar $SdkRoot

$env:JAVA_HOME = $JdkHome
$env:PATH = (Join-Path $JdkHome "bin") + ";" + $env:PATH

$Javac     = Join-Path $JdkHome "bin\javac.exe"
$Jar       = Join-Path $JdkHome "bin\jar.exe"
$Keytool   = Join-Path $JdkHome "bin\keytool.exe"
$Aapt2     = Join-Path $BuildTools "aapt2.exe"
$D8        = Join-Path $BuildTools "d8.bat"
$Zipalign  = Join-Path $BuildTools "zipalign.exe"
$ApkSigner = Join-Path $BuildTools "apksigner.bat"

foreach ($tool in @($Javac,$Jar,$Keytool,$Aapt2,$D8,$Zipalign,$ApkSigner)) {
    if (-not (Test-Path $tool)) { throw "缺少构建工具: $tool" }
}

Write-Host "== 构建环境 ==" -ForegroundColor Cyan
Write-Host "  JDK        : $JdkHome"
Write-Host "  Android SDK: $SdkRoot"
Write-Host "  build-tools: $BuildTools"
Write-Host "  android.jar: $AndroidJar"
Write-Host "  输出目录   : $OutDir"

# ---------------------------------------------------------------- 清理
if ($Clean -and (Test-Path $WorkDir)) {
    Write-Host "清理 $WorkDir" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $WorkDir
}
foreach ($d in @("classes","dex","res_compiled","gen","stage")) {
    $p = Join-Path $WorkDir $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$MinSdk = 24
$TargetSdk = 34

# ---------------------------------------------------------- 1) 资源编译
Write-Host "`n[1/7] aapt2 compile 资源..." -ForegroundColor Cyan
$compiledRes = Join-Path $WorkDir "res_compiled\res.zip"
& $Aapt2 compile --dir $ResDir -o $compiledRes
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile 失败" }

# ---------------------------------------------------------- 2) 资源链接
Write-Host "[2/7] aapt2 link（生成基础 APK 与 R.java）..." -ForegroundColor Cyan
$baseApk = Join-Path $WorkDir "base.apk"
$genDir  = Join-Path $WorkDir "gen"
$aapt2Extra = @()
if ($BuildType -eq "debug") {
    # 调试构建：写入 android:debuggable="true"，便于 adb 调试
    $aapt2Extra += "--debug-mode"
}

& $Aapt2 link `
    -o $baseApk `
    -I $AndroidJar `
    --manifest $Manifest `
    -R $compiledRes `
    --java $genDir `
    --min-sdk-version $MinSdk `
    --target-sdk-version $TargetSdk `
    --auto-add-overlay `
    @aapt2Extra
if ($LASTEXITCODE -ne 0) { throw "aapt2 link 失败" }

# ---------------------------------------------------------- 3) 编译 Java
Write-Host "[3/7] javac 编译 Java 源码..." -ForegroundColor Cyan
$javaFiles = @(Get-ChildItem -Path $JavaSrc -Recurse -Filter *.java | Select-Object -ExpandProperty FullName)
$javaFiles += @(Get-ChildItem -Path $genDir -Recurse -Filter *.java | Select-Object -ExpandProperty FullName)
if ($javaFiles.Count -eq 0) { throw "未找到 Java 源文件" }

$classDir = Join-Path $WorkDir "classes"
$argFile  = Join-Path $WorkDir "javac.args"
$javaFiles | ForEach-Object { '"' + ($_ -replace '\\','/') + '"' } | Set-Content -Path $argFile -Encoding ASCII

& $Javac -nowarn -encoding UTF-8 -source 11 -target 11 `
    -classpath $AndroidJar -d $classDir "@$argFile"
if ($LASTEXITCODE -ne 0) { throw "javac 编译失败" }

# ---------------------------------------------------------- 4) dex
Write-Host "[4/7] d8 生成 classes.dex..." -ForegroundColor Cyan
$classFiles = @(Get-ChildItem -Path $classDir -Recurse -Filter *.class | Select-Object -ExpandProperty FullName)
$dexDir = Join-Path $WorkDir "dex"
& $D8 --min-api $MinSdk --lib $AndroidJar --output $dexDir @classFiles
if ($LASTEXITCODE -ne 0) { throw "d8 转换失败" }

# ---------------------------------------------------------- 5) 组装 APK
Write-Host "[5/7] 组装 APK（写入 classes.dex）..." -ForegroundColor Cyan
$unsignedApk = Join-Path $WorkDir "app-unsigned.apk"
if (Test-Path $unsignedApk) { Remove-Item $unsignedApk -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 注意：targetSdk >= 30 时，resources.arsc 必须以「不压缩」方式存储，
# 否则安装时会报 「requires the resources.arsc of installed APKs to be stored
# uncompressed and aligned on a 4-byte boundary」。
# 因此这里不能整包重新压缩，而要逐条复制并保留 arsc 的存储方式。
$baseStream = [System.IO.File]::OpenRead($baseApk)
$baseZip = New-Object System.IO.Compression.ZipArchive($baseStream, [System.IO.Compression.ZipArchiveMode]::Read)
$outStream = [System.IO.File]::Create($unsignedApk)
$outZip = New-Object System.IO.Compression.ZipArchive($outStream, [System.IO.Compression.ZipArchiveMode]::Create)

try {
    foreach ($entry in $baseZip.Entries) {
        $level = [System.IO.Compression.CompressionLevel]::Optimal
        if ($entry.FullName -eq "resources.arsc") {
            $level = [System.IO.Compression.CompressionLevel]::NoCompression
        }
        $newEntry = $outZip.CreateEntry($entry.FullName, $level)
        $in = $entry.Open()
        $out = $newEntry.Open()
        try { $in.CopyTo($out) } finally { $out.Dispose(); $in.Dispose() }
    }

    $dexPath = Join-Path $dexDir "classes.dex"
    $dexEntry = $outZip.CreateEntry("classes.dex", [System.IO.Compression.CompressionLevel]::Optimal)
    $dexIn = [System.IO.File]::OpenRead($dexPath)
    $dexOut = $dexEntry.Open()
    try { $dexIn.CopyTo($dexOut) } finally { $dexOut.Dispose(); $dexIn.Dispose() }
} finally {
    $outZip.Dispose()
    $outStream.Dispose()
    $baseZip.Dispose()
    $baseStream.Dispose()
}

if (-not (Test-Path $unsignedApk)) { throw "打包 APK 失败" }

# ---------------------------------------------------------- 6) 对齐
Write-Host "[6/7] zipalign 对齐..." -ForegroundColor Cyan
$alignedApk = Join-Path $WorkDir "app-aligned.apk"
& $Zipalign -f 4 $unsignedApk $alignedApk
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败" }

# ---------------------------------------------------------- 7) 签名
Write-Host "[7/7] apksigner 签名..." -ForegroundColor Cyan
$keystore = Join-Path $AndroidDir "debug.keystore"
if (-not (Test-Path $keystore)) {
    Write-Host "  生成调试密钥库: $keystore" -ForegroundColor Yellow
    & $Keytool -genkeypair -keystore $keystore -storepass android -keypass android `
        -alias androiddebugkey -dname "CN=Android Debug,O=Android,C=US" `
        -keyalg RSA -keysize 2048 -validity 10000
    if ($LASTEXITCODE -ne 0) { throw "生成密钥库失败" }
}

if (-not $ApkName) { $ApkName = "damai-assistant-$BuildType" }
$finalApk = Join-Path $OutDir "$ApkName.apk"
& $ApkSigner sign --ks $keystore --ks-pass pass:android --key-pass pass:android `
    --ks-key-alias androiddebugkey --out $finalApk $alignedApk
if ($LASTEXITCODE -ne 0) { throw "签名失败" }

& $ApkSigner verify --print-certs $finalApk | Select-Object -First 3

$size = (Get-Item $finalApk).Length
Write-Host "`n构建成功: $finalApk ($([math]::Round($size/1KB,1)) KB)" -ForegroundColor Green
Write-Host ""
Write-Host "安装到手机：" -ForegroundColor Cyan
Write-Host "  adb install -r `"$finalApk`""
Write-Host ""
Write-Host "开启远程调试（Windows 侧）：" -ForegroundColor Cyan
Write-Host "  adb forward tcp:8710 tcp:8710"
Write-Host "  python tools/damai_remote.py --status"
