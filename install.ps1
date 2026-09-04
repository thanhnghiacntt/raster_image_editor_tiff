# Cai plugin Raster Image Editor Tiff vao profile QGIS cua nguoi dung.
# Dung:  powershell -ExecutionPolicy Bypass -File install.ps1  [-Profile default]

param(
    [string]$Profile = "default"
)

$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
$relative = "QGIS\QGIS3\profiles\$Profile\python\plugins\raster_image_editor_tiff"
$target = Join-Path $env:APPDATA $relative

if (-not (Test-Path (Join-Path $source "metadata.txt"))) {
    throw "Khong tim thay metadata.txt trong $source - hay chay script tu trong thu muc plugin."
}

$parent = Split-Path $target -Parent
if (-not (Test-Path $parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

if (Test-Path $target) {
    Write-Host "Xoa ban cu: $target"
    Remove-Item -Recurse -Force $target -Confirm:$false
}

Write-Host "Chep $source -> $target"
Copy-Item -Recurse -Force $source $target
Remove-Item -Recurse -Force (Join-Path $target "__pycache__") -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Xong. Mo QGIS -> Plugins -> Manage and Install Plugins -> Installed -> bat 'Raster Image Editor Tiff'."
