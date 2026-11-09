param([string]$PythonExecutable = "")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$python = if ($PythonExecutable) { $PythonExecutable } else { Join-Path $PSScriptRoot ".venv-win/Scripts/python.exe" }
$arguments = @("-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--name", "FramePort", "--icon", "$PSScriptRoot/assets/app.ico", "--version-file", "$PSScriptRoot/assets/version.txt", "--distpath", "$PSScriptRoot/release", "--workpath", "$PSScriptRoot/build/pyinstaller", "--specpath", "$PSScriptRoot/build", "--collect-all", "playwright")
foreach ($resource in @("assets")) {
    $arguments += @("--add-data", "$PSScriptRoot/$resource;$resource")
}
$arguments += @("--add-data", "$PSScriptRoot/profiles/example.json;profiles")
foreach ($resource in @("cwebp.exe", "COPYING", "PATENTS", "AUTHORS")) {
    $arguments += @("--add-data", "$PSScriptRoot/tools/webp/$resource;tools/webp")
}
$arguments += "$PSScriptRoot/app.py"
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built release/FramePort/FramePort.exe"

& $python "$PSScriptRoot/package-release.py"
if ($LASTEXITCODE -ne 0) { throw "Packaging failed" }
