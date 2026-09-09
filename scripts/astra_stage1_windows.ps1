#requires -Version 5.1
param(
    [switch]$Elevated,
    [switch]$Restarted,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"
$FeatureBranch = "astra-phase2-pull-worker-design-20260909"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ConfigPath = Join-Path $SourceRoot "worker-config.json"
$StateRoot = Join-Path $env:ProgramData "ASTRAWorker"
$SecretPath = Join-Path $StateRoot "secrets.bin"
$TranscriptStarted = $false

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-NativeSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE"
    }
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LogPath = Join-Path $env:TEMP "ASTRA-Stage1-$stamp.log"
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        Write-Error "ASTRA_STAGE1_FAILED: elevation token was requested but is not active"
        exit 1
    }

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-ProcessArgument $PSCommandPath),
        "-Elevated",
        "-LogPath", (Quote-ProcessArgument $LogPath)
    )

    try {
        $child = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    }
    catch {
        Write-Error "ASTRA_STAGE1_FAILED: administrator elevation was cancelled or failed: $($_.Exception.Message)"
        exit 1
    }

    Write-Host "ASTRA Stage 1 elevated process exit code: $($child.ExitCode)"
    Write-Host "ASTRA Stage 1 log: $LogPath"
    exit $child.ExitCode
}

$exitCode = 1
try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "=================================================="
    Write-Host " ASTRA PHASE 2A - WINDOWS STAGE 1 CONTROLLED RUN"
    Write-Host "=================================================="

    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "worker-config.json is missing at $ConfigPath"
    }
    if (Test-Path -LiteralPath $SecretPath -PathType Leaf) {
        throw "secrets.bin already exists; Stage 1 must not provision or reuse secrets"
    }

    $service = Get-Service ASTRAWorker -ErrorAction Stop
    if ($service.Status -ne [ServiceProcess.ServiceControllerStatus]::Stopped) {
        throw "ASTRAWorker must remain stopped during Stage 1"
    }

    Push-Location $SourceRoot
    try {
        & git fetch origin $FeatureBranch
        Assert-NativeSuccess "git fetch"

        $remoteHead = (& git rev-parse "origin/$FeatureBranch").Trim()
        Assert-NativeSuccess "remote HEAD resolution"
        if ($remoteHead -notmatch '^[0-9a-f]{40}$') {
            throw "remote feature HEAD is not a full commit SHA"
        }

        $currentHead = (& git rev-parse HEAD).Trim()
        Assert-NativeSuccess "current HEAD resolution"

        if ($currentHead -ne $remoteHead) {
            & git checkout --detach $remoteHead
            Assert-NativeSuccess "exact feature HEAD checkout"

            if ($Restarted) {
                throw "feature HEAD changed again during controlled restart"
            }

            if ($TranscriptStarted) {
                Stop-Transcript | Out-Null
                $TranscriptStarted = $false
            }

            $restartArgs = @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", (Quote-ProcessArgument $PSCommandPath),
                "-Elevated",
                "-Restarted",
                "-LogPath", (Quote-ProcessArgument $LogPath)
            )
            $restart = Start-Process -FilePath "powershell.exe" -ArgumentList $restartArgs -Wait -PassThru
            exit $restart.ExitCode
        }

        Write-Host "ASTRA_EXACT_HEAD=$currentHead"
    }
    finally {
        Pop-Location
    }

    $InstallerPath = Join-Path $SourceRoot "scripts\install_astra_worker.ps1"
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw "install_astra_worker.ps1 is missing"
    }

    Write-Host "----- installer -----"
    $installerOutput = @(
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $InstallerPath -ConfigPath $ConfigPath 2>&1
    )
    $installerExit = $LASTEXITCODE
    $installerOutput | ForEach-Object { Write-Host $_ }
    $installerText = $installerOutput | Out-String

    $hardenCount = ([regex]::Matches($installerText, "ASTRA_ACL_HARDENED")).Count
    if ($hardenCount -ne 2) {
        throw "expected exactly two ASTRA_ACL_HARDENED markers; observed $hardenCount"
    }
    if ($installerText -notmatch "Protected secrets are not present") {
        throw "installer did not reach the protected secrets gate"
    }
    if ($installerExit -eq 0) {
        throw "installer unexpectedly succeeded while secrets are absent"
    }

    $sidOutput = (& sc.exe showsid ASTRAWorker 2>&1 | Out-String)
    Assert-NativeSuccess "service SID lookup"
    $serviceSid = [regex]::Match($sidOutput, "S-1-5-80(?:-\d+)+").Value
    if ([string]::IsNullOrWhiteSpace($serviceSid)) {
        throw "virtual service SID could not be resolved"
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction Stop
    }
    $pythonExe = $pythonCommand.Source
    $WorkerLauncher = Join-Path $SourceRoot "scripts\astra_worker.py"

    Write-Host "----- independent ACL verifier -----"
    Push-Location $SourceRoot
    try {
        $verifyOutput = @(
            & $pythonExe $WorkerLauncher verify-acl --path $StateRoot --service-sid $serviceSid 2>&1
        )
        $verifyExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $verifyOutput | ForEach-Object { Write-Host $_ }
    $verifyText = $verifyOutput | Out-String
    if ($verifyExit -ne 0) {
        throw "independent exact ACL verifier failed with exit code $verifyExit"
    }
    if ($verifyText -notmatch "ASTRA_ACL_OK") {
        throw "independent exact ACL verifier did not emit ASTRA_ACL_OK"
    }

    $service = Get-Service ASTRAWorker -ErrorAction Stop
    if ($service.Status -ne [ServiceProcess.ServiceControllerStatus]::Stopped) {
        throw "ASTRAWorker unexpectedly started during Stage 1"
    }
    if (Test-Path -LiteralPath $SecretPath -PathType Leaf) {
        throw "secrets.bin unexpectedly appeared during Stage 1"
    }

    $serviceConfig = (& sc.exe qc ASTRAWorker 2>&1 | Out-String)
    Assert-NativeSuccess "service account inspection"
    if ($serviceConfig -notmatch 'SERVICE_START_NAME\s*:\s*NT SERVICE\\ASTRAWorker') {
        throw "ASTRAWorker is not configured for the virtual service account"
    }

    $sidType = (& sc.exe qsidtype ASTRAWorker 2>&1 | Out-String)
    Assert-NativeSuccess "service SID type inspection"
    if ($sidType -notmatch 'SERVICE_SID_TYPE\s*:\s*UNRESTRICTED') {
        throw "ASTRAWorker service SID type is not UNRESTRICTED"
    }

    $aclRoot = (& icacls.exe $StateRoot 2>&1 | Out-String)
    Assert-NativeSuccess "elevated ACL root inspection"
    Write-Host $aclRoot

    Write-Host "ASTRA_STAGE1_OK"
    Write-Host "HEAD=$currentHead"
    Write-Host "SERVICE=Stopped"
    Write-Host "SERVICE_START_NAME=NT SERVICE\ASTRAWorker"
    Write-Host "SERVICE_SID_TYPE=UNRESTRICTED"
    Write-Host "SECRETS=False"
    Write-Host "LOG=$LogPath"
    $exitCode = 0
}
catch {
    Write-Error "ASTRA_STAGE1_FAILED: $($_.Exception.Message)"
    Write-Host "LOG=$LogPath"
    $exitCode = 1
}
finally {
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $exitCode
