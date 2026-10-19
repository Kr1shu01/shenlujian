param([Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $env:RUNNER_TEMP '神录剪 Windows packages'
$reportRoot = Join-Path $projectRoot 'build\windows\reports'
New-Item -ItemType Directory -Force -Path $testRoot, $reportRoot | Out-Null
$portable = Join-Path $projectRoot "releases\shenlujian-$Version-windows-x64-portable.zip"
$setup = Join-Path $projectRoot "releases\shenlujian-$Version-windows-x64-setup.exe"
if (!(Test-Path -LiteralPath $portable) -or !(Test-Path -LiteralPath $setup)) {
    throw 'Both Windows release packages are required'
}
$portableRoot = Join-Path $testRoot '解压 portable'
Expand-Archive -LiteralPath $portable -DestinationPath $portableRoot -Force
$portableExe = Join-Path $portableRoot 'shenlujian-windows-x64\shenlujian.exe'
& python (Join-Path $PSScriptRoot 'windows_smoke.py') --executable $portableExe --report (Join-Path $reportRoot 'portable.json')
if ($LASTEXITCODE -ne 0) { throw 'Portable application smoke failed' }
$installRoot = Join-Path $testRoot '安装 install'
$installLog = Join-Path $reportRoot 'installer.log'
$process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$installRoot`"", "/LOG=`"$installLog`"") -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installer failed ($($process.ExitCode))" }
$installedExe = Join-Path $installRoot 'shenlujian.exe'
if (!(Test-Path -LiteralPath $installedExe)) { throw 'Installer did not create application EXE' }
& python (Join-Path $PSScriptRoot 'windows_smoke.py') --executable $installedExe --report (Join-Path $reportRoot 'installed.json')
if ($LASTEXITCODE -ne 0) { throw 'Installed application smoke failed' }
$uninstaller = Join-Path $installRoot 'unins000.exe'
if (!(Test-Path -LiteralPath $uninstaller)) { throw 'Uninstaller is missing' }
$process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Uninstaller failed ($($process.ExitCode))" }
if (Test-Path -LiteralPath $installedExe) { throw 'Uninstaller left application EXE behind' }
# The runner is disposable; this is application-owned test media, never user media.
Remove-Item -LiteralPath $testRoot -Recurse -Force
Write-Host 'Portable startup, native recording, audio import/mix, setup and uninstall passed.'
