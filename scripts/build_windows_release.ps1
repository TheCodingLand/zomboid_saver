[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipDependencySync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-AppVersion {
    param([string]$PyprojectPath)

    $versionLine = Get-Content -Path $PyprojectPath | Select-String -Pattern '^version\s*=\s*"(?<version>[^"]+)"$' | Select-Object -First 1
    if ($null -eq $versionLine) {
        throw "Unable to determine project version from $PyprojectPath"
    }

    return $versionLine.Matches[0].Groups['version'].Value
}

function Get-CommandPath {
    param([string]$Name)

    $command = Get-Command -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required command '$Name' was not found on PATH."
    }

    return $command.Source
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"
$portableExe = Join-Path $distDir "zomboid_saver-windows.exe"
$nuitkaExe = Join-Path $buildDir "zomboid_saver.exe"
$installerScript = Join-Path $repoRoot "packaging\windows\zomboid_saver.iss"

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-AppVersion -PyprojectPath $pyprojectPath
}

$uvPath = Get-CommandPath -Name "uv"
$isccPath = Get-CommandPath -Name "iscc"

Push-Location $repoRoot
try {
    if (-not $SkipDependencySync) {
        & $uvPath sync --frozen --extra build
    }

    New-Item -ItemType Directory -Path $distDir -Force | Out-Null

    & $uvPath run python -m nuitka `
        --onefile `
        --standalone `
        --assume-yes-for-downloads `
        --enable-plugin=pyqt6 `
        --windows-console-mode=disable `
        --msvc=latest `
        --output-dir=build `
        --output-filename=zomboid_saver `
        --remove-output `
        .\zomboid_saver_ui.py

    if (-not (Test-Path -LiteralPath $nuitkaExe)) {
        throw "Nuitka did not produce $nuitkaExe"
    }

    Copy-Item -LiteralPath $nuitkaExe -Destination $portableExe -Force

    & $isccPath "/DAppVersion=$Version" "/DSourceExe=$portableExe" "/O$distDir" $installerScript
}
finally {
    Pop-Location
}