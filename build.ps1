param(
    [ValidateSet("standalone", "onefile")]
    [string]$Mode = "standalone"
)

$ErrorActionPreference = "Stop"

$AppName = "SeaweedFSBrowser"
$BuildRoot = "build"
$NuitkaOut = Join-Path $BuildRoot "nuitka"
$ReleaseRoot = "release"
$ReleaseDir = Join-Path $ReleaseRoot $AppName

Write-Host "构建模式: $Mode"
Write-Host "准备目录..."

if (Test-Path $NuitkaOut) { Remove-Item -Recurse -Force $NuitkaOut }
if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
New-Item -ItemType Directory -Path $NuitkaOut | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

$args = @(
    "-m", "nuitka",
    "--enable-plugin=pyside6",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--include-data-dir=resource=resource",
    "--output-dir=$NuitkaOut",
    "--output-filename=$AppName.exe",
    "--remove-output",
    "main.py"
)

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
    Copy-Item $oneFileExe -Destination (Join-Path $ReleaseDir "$AppName.exe") -Force
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
