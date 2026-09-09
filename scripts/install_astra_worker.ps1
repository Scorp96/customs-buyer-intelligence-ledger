#requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$WinSWUrl = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
$WinSWSha256 = "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"
$StateRoot = Join-Path $env:ProgramData "ASTRAWorker"
$ServiceName = "ASTRAWorker"
$ServiceAccount = "NT SERVICE\ASTRAWorker"
$SystemSid = "S-1-5-18"
$AdministratorsSid = "S-1-5-32-544"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TemplatePath = Join-Path $RepositoryRoot "deploy\astra-worker\ASTRAWorker.xml.template"
$WorkerLauncher = Join-Path $RepositoryRoot "scripts\astra_worker.py"
$WinSWExe = Join-Path $StateRoot "ASTRAWorker.exe"
$WinSWXml = Join-Path $StateRoot "ASTRAWorker.xml"
$ConfigTarget = Join-Path $StateRoot "config.json"
$SecretTarget = Join-Path $StateRoot "secrets.bin"
$LogRoot = Join-Path $StateRoot "log"

function Assert-NativeSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE"
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "ASTRA worker setup requires an elevated administrator token"
}

if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
    throw "service template is missing"
}
if (-not (Test-Path -LiteralPath $WorkerLauncher -PathType Leaf)) {
    throw "worker launcher is missing"
}
$ResolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path

$PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -eq $PythonCommand) {
    $PythonCommand = Get-Command python -ErrorAction Stop
}
$PythonExe = $PythonCommand.Source

$Directories = @(
    $StateRoot,
    $LogRoot,
    (Join-Path $StateRoot "repos"),
    (Join-Path $StateRoot "worktrees"),
    (Join-Path $StateRoot "empty-hooks"),
    (Join-Path $StateRoot "home"),
    (Join-Path $StateRoot "xdg-config")
)
foreach ($Directory in $Directories) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
}
Copy-Item -LiteralPath $ResolvedConfig -Destination $ConfigTarget -Force

if (Test-Path -LiteralPath $WinSWExe -PathType Leaf) {
    $ExistingHash = (Get-FileHash -LiteralPath $WinSWExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExistingHash -ne $WinSWSha256) {
        Remove-Item -LiteralPath $WinSWExe -Force
        throw "existing WinSW binary failed the pinned SHA256 check"
    }
}
else {
    $DownloadPath = Join-Path $env:TEMP "ASTRAWorker.WinSW-x64.exe"
    Remove-Item -LiteralPath $DownloadPath -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest -Uri $WinSWUrl -OutFile $DownloadPath -UseBasicParsing
    $DownloadedHash = (Get-FileHash -LiteralPath $DownloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($DownloadedHash -ne $WinSWSha256) {
        Remove-Item -LiteralPath $DownloadPath -Force -ErrorAction SilentlyContinue
        throw "downloaded WinSW binary failed the pinned SHA256 check"
    }
    Move-Item -LiteralPath $DownloadPath -Destination $WinSWExe -Force
}

$Escape = [Security.SecurityElement]::Escape
$Template = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8
$RenderedXml = $Template.Replace("@@PYTHON_EXE@@", $Escape.Invoke($PythonExe))
$RenderedXml = $RenderedXml.Replace("@@REPOSITORY_ROOT@@", $Escape.Invoke($RepositoryRoot))
$RenderedXml = $RenderedXml.Replace("@@STATE_ROOT@@", $Escape.Invoke($StateRoot))
$RenderedXml = $RenderedXml.Replace("@@LOG_ROOT@@", $Escape.Invoke($LogRoot))

$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -eq $ExistingService) {
    Push-Location $StateRoot
    try {
        & $WinSWExe install
        Assert-NativeSuccess "WinSW service registration"
    }
    finally {
        Pop-Location
    }
}

& sc.exe sidtype $ServiceName unrestricted | Out-Null
Assert-NativeSuccess "service SID configuration"
& sc.exe config $ServiceName obj= $ServiceAccount password= "" | Out-Null
Assert-NativeSuccess "virtual service account configuration"

$SidOutput = (& sc.exe showsid $ServiceName 2>&1 | Out-String)
Assert-NativeSuccess "service SID lookup"
$SidMatch = [regex]::Match($SidOutput, "S-1-5-80(?:-\d+)+")
if (-not $SidMatch.Success) {
    throw "virtual service SID could not be resolved"
}
$ServiceSid = $SidMatch.Value
$RenderedXml = $RenderedXml.Replace("@@SERVICE_SID@@", $Escape.Invoke($ServiceSid))
[IO.File]::WriteAllText($WinSWXml, $RenderedXml, (New-Object Text.UTF8Encoding($false)))

$ServiceGrant = "*$ServiceSid`:(OI)(CI)F"
$SystemGrant = "*$SystemSid`:(OI)(CI)F"
$AdministratorsGrant = "*$AdministratorsSid`:(OI)(CI)F"
& icacls.exe $StateRoot /inheritance:r /grant:r $ServiceGrant $SystemGrant $AdministratorsGrant /T /C | Out-Null
Assert-NativeSuccess "worker state ACL hardening"

if (-not (Test-Path -LiteralPath $SecretTarget -PathType Leaf)) {
    Write-Host "Protected secrets are not present. Run: python scripts/astra_worker.py provision-secrets --stdin"
    throw "protected secret provisioning is required before the service can run"
}

& $PythonExe $WorkerLauncher validate-install
Assert-NativeSuccess "ASTRA worker configuration validation"

$ExistingService = Get-Service -Name $ServiceName -ErrorAction Stop
if ($ExistingService.Status -ne [ServiceProcess.ServiceControllerStatus]::Running) {
    & $WinSWExe start
    Assert-NativeSuccess "ASTRA worker service activation"
}
