param(
    [ValidateSet("standalone", "onefile")]
    [string]$Mode = "standalone"
)

$ErrorActionPreference = "Stop"

$AppName = "SeaweedFSBrowser"
$MainPy = "main.py"
$VersionMatch = Select-String -Path $MainPy -Pattern '^APP_VERSION = "([^"]+)"$'
if (-not $VersionMatch) {
    throw "未能从 $MainPy 解析 APP_VERSION"
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

try {
    $F3dPackageDir = (python -c "import f3d, pathlib; print(pathlib.Path(f3d.__file__).resolve().parent)" | Select-Object -Last 1).Trim()
} catch {
    $F3dPackageDir = ""
}

$args = @(
    "-m", "nuitka",
    "--enable-plugin=pyside6",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=$IcoIcon",
    "--include-data-dir=resource=resource",
    "--output-dir=$NuitkaOut",
    "--output-filename=$AppName.exe",
    "--remove-output",
    "main.py"
)

if ($F3dPackageDir) {
    $F3dBinDir = Join-Path $F3dPackageDir "bin"
    $F3dShareDir = Join-Path $F3dPackageDir "share"
    if (Test-Path $F3dBinDir) {
        $f3dBinFiles = Get-ChildItem -Path $F3dBinDir -File
        foreach ($f3dBinFile in $f3dBinFiles) {
            $args += "--include-data-files=$($f3dBinFile.FullName)=f3d/bin/$($f3dBinFile.Name)"
        }
    }
    if (Test-Path $F3dShareDir) {
        $args += "--include-data-dir=$F3dShareDir=f3d/share"
    }
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
    Copy-Item $oneFileExe -Destination (Join-Path $ReleaseDir "$PackageBaseName.exe") -Force
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
}

Write-Host ""
Write-Host "构建完成。可发布目录:"
Write-Host (Resolve-Path $ReleaseDir).Path
