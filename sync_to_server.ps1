[CmdletBinding()]
param(
    [string]$RemoteHost = "vaipe_aiotlab",
    [string]$RemoteDir = "/mnt/disk4/similar_cases_retrieval/code/"
)

$ErrorActionPreference = "Stop"

$localRoot = $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$archiveName = "medical-similar-cases-code-$stamp.tar.gz"
$archivePath = Join-Path ([System.IO.Path]::GetTempPath()) $archiveName
$remoteArchive = "/tmp/$archiveName"

try {
    & tar.exe -czf $archivePath `
        --exclude=.git `
        --exclude=.venv `
        --exclude=venv `
        --exclude=__pycache__ `
        --exclude=.DS_Store `
        --exclude='*.pyc' `
        --exclude=data `
        --exclude=datasets `
        --exclude=checkpoints `
        --exclude=outputs `
        --exclude=preprocessed `
        -C $localRoot .
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create sync archive."
    }

    & ssh.exe $RemoteHost "mkdir -p '$RemoteDir'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create remote code directory."
    }

    & scp.exe $archivePath "${RemoteHost}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload sync archive."
    }

    & ssh.exe $RemoteHost "tar -xzf '$remoteArchive' -C '$RemoteDir' && rm -f '$remoteArchive'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract sync archive on the server."
    }

    Write-Host "Sync completed: $localRoot -> ${RemoteHost}:$RemoteDir"
}
finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}
