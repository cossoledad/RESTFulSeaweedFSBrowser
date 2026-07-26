param(
    [ValidateSet("standalone", "onefile")]
    [string]$Mode = "standalone"
)

$ErrorActionPreference = "Stop"

$AppName = "SeaweedFSBrowser"
$MainPy = "main.py"
$VersionFile = "seaweed_browser/core.py"
$VersionMatch = Select-String -Path $VersionFile -Pattern '^APP_VERSION = "([^"]+)"$'
if (-not $VersionMatch) {
    throw "未能从 $VersionFile 解析 APP_VERSION"
}
$Version = $VersionMatch.Matches[0].Groups[1].Value
$PackageBaseName = "$AppName-v$Version-windows-x64-$Mode"
$BuildRoot = "build"
$NuitkaOut = Join-Path $BuildRoot "nuitka"
$ReleaseRoot = "release"
$ReleaseDir = Join-Path $ReleaseRoot $PackageBaseName
$PngIcon = Join-Path "resource" "seaweedfs.png"
$IcoIcon = Join-Path "resource" "seaweedfs.ico"
$F3dPackageDir = ""
$ReleaseExe = ""

Write-Host "构建模式: $Mode"
Write-Host "程序版本: $Version"
Write-Host "准备目录..."

if (Test-Path $NuitkaOut) { Remove-Item -Recurse -Force $NuitkaOut }
if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
New-Item -ItemType Directory -Path $NuitkaOut | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

if (Test-Path $PngIcon) {
    Write-Host "生成 Windows 图标文件..."
    python .\scripts\make_ico_from_png.py $PngIcon $IcoIcon
}

$F3dProbeOutput = python -c "import f3d, pathlib; print(pathlib.Path(f3d.__file__).resolve().parent)"
if ($LASTEXITCODE -ne 0) {
    throw "无法导入 f3d，拒绝生成缺少模型预览环境的发布包"
}
$F3dPackageDir = ($F3dProbeOutput | Select-Object -Last 1).Trim()
$F3dBinDir = Join-Path $F3dPackageDir "bin"
$F3dShareDir = Join-Path $F3dPackageDir "share"
$F3dBinding = Get-ChildItem -Path $F3dPackageDir -Filter "pyf3d*.pyd" -File | Select-Object -First 1

if (-not (Test-Path $F3dPackageDir -PathType Container)) {
    throw "f3d 包目录不存在: $F3dPackageDir"
}
if (-not $F3dBinding) {
    throw "f3d Python 扩展不存在: $F3dPackageDir\pyf3d*.pyd"
}
if (-not (Test-Path (Join-Path $F3dBinDir "f3d.dll") -PathType Leaf)) {
    throw "f3d 运行库不存在: $F3dBinDir\f3d.dll"
}
if (-not (Test-Path $F3dShareDir -PathType Container)) {
    throw "f3d 资源目录不存在: $F3dShareDir"
}

$args = @(
    "-m", "nuitka",
    "--enable-plugin=pyside6",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=$IcoIcon",
    "--include-package=f3d",
    "--include-data-dir=resource=resource",
    "--output-dir=$NuitkaOut",
    "--output-filename=$AppName.exe",
    "--remove-output",
    "main.py"
)

$f3dBinFiles = Get-ChildItem -Path $F3dBinDir -File
foreach ($f3dBinFile in $f3dBinFiles) {
    $args += "--include-data-files=$($f3dBinFile.FullName)=f3d/bin/$($f3dBinFile.Name)"
}
$args += "--include-data-dir=$F3dShareDir=f3d/share"

if ($f3dBinFiles.Count -eq 0) {
    throw "f3d/bin 中没有可打包的运行库"
}

if ($Mode -eq "onefile") {
    $args += "--onefile"
} else {
    $args += "--standalone"
}

Write-Host "开始 Nuitka 构建..."
python @args

if ($Mode -eq "onefile") {
    $oneFileExe = Join-Path $NuitkaOut "$AppName.exe"
    if (-not (Test-Path $oneFileExe)) {
        $oneFileExe = Join-Path $NuitkaOut "main.exe"
    }
    if (-not (Test-Path $oneFileExe)) {
        $exeCandidates = Get-ChildItem -Path $NuitkaOut -Filter *.exe -File | Sort-Object LastWriteTime -Descending
        if ($exeCandidates.Count -gt 0) {
            $oneFileExe = $exeCandidates[0].FullName
        }
    }
    if (-not (Test-Path $oneFileExe)) {
        throw "未找到 onefile 产物: $oneFileExe"
    }
    $ReleaseExe = Join-Path $ReleaseDir "$PackageBaseName.exe"
    Copy-Item $oneFileExe -Destination $ReleaseExe -Force
} else {
    $distDir = Join-Path $NuitkaOut "$AppName.dist"
    if (-not (Test-Path $distDir)) {
        $distDir = Join-Path $NuitkaOut "main.dist"
    }
    if (-not (Test-Path $distDir)) {
        $distCandidates = Get-ChildItem -Path $NuitkaOut -Directory -Filter *.dist | Sort-Object LastWriteTime -Descending
        if ($distCandidates.Count -gt 0) {
            $distDir = $distCandidates[0].FullName
        }
    }
    if (-not (Test-Path $distDir)) {
        throw "未找到 standalone 产物目录: $distDir"
    }
    Copy-Item $distDir\* -Destination $ReleaseDir -Recurse -Force
    $ReleaseExe = Join-Path $ReleaseDir "$AppName.exe"
}

if (-not (Test-Path $ReleaseExe -PathType Leaf)) {
    throw "发布程序不存在，无法执行 F3D 自检: $ReleaseExe"
}

Write-Host "执行发布包 F3D 自检..."
& $ReleaseExe --check-f3d-runtime
if ($LASTEXITCODE -ne 0) {
    throw "发布包 F3D 自检失败，拒绝发布"
}

Write-Host ""
Write-Host "构建完成。可发布目录:"
Write-Host (Resolve-Path $ReleaseDir).Path
