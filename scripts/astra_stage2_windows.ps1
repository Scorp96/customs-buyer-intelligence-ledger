#requires -Version 5.1
param(
    [switch]$Elevated,
    [switch]$Restarted,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"
$FeatureBranch = "astra-phase2-pull-worker-design-20260909"
$Repository = "Scorp96/customs-buyer-intelligence-ledger"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateRoot = Join-Path $env:ProgramData "ASTRAWorker"
$SecretPath = Join-Path $StateRoot "secrets.bin"
$DisabledPath = Join-Path $StateRoot "DISABLED"
$WorkerLauncher = Join-Path $SourceRoot "scripts\astra_worker.py"
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
    if ($null -eq $Value) {
        return '""'
    }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Join-ProcessArguments([string[]]$Arguments) {
    return (($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " ")
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Action
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = Join-ProcessArguments $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        throw "$Action could not start"
    }
    try {
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "$Action failed with exit code $($process.ExitCode)"
        }
        return [pscustomobject]@{ Stdout = $stdout; Stderr = $stderr; ExitCode = $process.ExitCode }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-ProcessWithInput {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$InputText,
        [Parameter(Mandatory = $true)][string]$Action
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = Join-ProcessArguments $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        throw "$Action could not start"
    }
    try {
        # Secrets are transferred only through the child process StandardInput.
        # No HMAC key or worker token is placed in argv or written as cleartext to disk.
        $process.StandardInput.Write($InputText)
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "$Action failed with exit code $($process.ExitCode)"
        }
        return [pscustomobject]@{ Stdout = $stdout; Stderr = $stderr; ExitCode = $process.ExitCode }
    }
    finally {
        $process.Dispose()
    }
}

function New-RandomHmacKeyB64 {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes)
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

function ConvertFrom-SecureStringToPlainText([Security.SecureString]$SecureValue) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LogPath = Join-Path $env:TEMP "ASTRA-Stage2-$stamp.log"
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        Write-Error "ASTRA_STAGE2_FAILED: elevation token was requested but is not active"
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
        Write-Error "ASTRA_STAGE2_FAILED: administrator elevation was cancelled or failed"
        exit 1
    }

    Write-Host "ASTRA Stage 2 elevated process exit code: $($child.ExitCode)"
    Write-Host "ASTRA Stage 2 log: $LogPath"
    exit $child.ExitCode
}

$exitCode = 1
$workerToken = $null
$taskKeyB64 = $null
$receiptKeyB64 = $null
$secretPayload = $null
$workerTokenSecure = $null

try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "=================================================="
    Write-Host " ASTRA PHASE 2A - WINDOWS STAGE 2 CONTROLLED RUN"
    Write-Host "=================================================="

    $service = Get-Service ASTRAWorker -ErrorAction Stop
    if ($service.Status -ne [ServiceProcess.ServiceControllerStatus]::Stopped) {
        throw "ASTRAWorker must be stopped before Stage 2 activation"
    }
    if (Test-Path -LiteralPath $SecretPath -PathType Leaf) {
        throw "secrets.bin already exists; Stage 2 refuses implicit secret rotation"
    }
    if (Test-Path -LiteralPath $DisabledPath -PathType Leaf) {
        throw "DISABLED marker exists; remove only after reviewing why the worker was disabled"
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

    $ghCommand = Get-Command gh.exe -ErrorAction SilentlyContinue
    if ($null -eq $ghCommand) {
        $ghCommand = Get-Command gh -ErrorAction Stop
    }
    $GhExe = $ghCommand.Source

    # The operator's normal GitHub CLI login is used only to create repository
    # Actions secrets. It is never copied into the worker's DPAPI bundle.
    $auth = Invoke-CapturedProcess -FilePath $GhExe -Arguments @("auth", "status", "--hostname", "github.com") -Action "GitHub CLI authentication check"
    $repoView = Invoke-CapturedProcess -FilePath $GhExe -Arguments @("repo", "view", $Repository, "--json", "nameWithOwner", "--jq", ".nameWithOwner") -Action "GitHub repository access check"
    if ($repoView.Stdout.Trim() -ne $Repository) {
        throw "GitHub CLI is authenticated but the expected repository was not resolved"
    }

    $workerTokenSecure = Read-Host "Paste the fine-grained ASTRAWorker token (input hidden)" -AsSecureString
    $workerToken = ConvertFrom-SecureStringToPlainText $workerTokenSecure
    if ([string]::IsNullOrWhiteSpace($workerToken) -or $workerToken.Contains([char]0) -or $workerToken.Contains("`r") -or $workerToken.Contains("`n")) {
        throw "worker GitHub token is empty or malformed"
    }

    # Authenticate the narrow worker credential before storing it. The endpoint is
    # read-only; write authority is proven later by the signed-task canary.
    try {
        $headers = @{
            Authorization = "Bearer $workerToken"
            Accept = "application/vnd.github+json"
            "User-Agent" = "astra-phase2-stage2/0.1"
            "X-GitHub-Api-Version" = "2022-11-28"
        }
        $null = Invoke-RestMethod -Method Get -Uri "https://api.github.com/repos/$Repository/issues?state=open&per_page=1" -Headers $headers -UseBasicParsing
    }
    catch {
        throw "fine-grained worker token GitHub preflight failed"
    }

    $taskKeyB64 = New-RandomHmacKeyB64
    do {
        $receiptKeyB64 = New-RandomHmacKeyB64
    } while ($receiptKeyB64 -eq $taskKeyB64)

    Write-Host "Provisioning repository Actions HMAC secrets via gh secret set stdin..."
    $null = Invoke-ProcessWithInput -FilePath $GhExe -Arguments @("secret", "set", "ASTRA_TASK_HMAC_KEY_B64", "--repo", $Repository) -InputText $taskKeyB64 -Action "ASTRA task HMAC Actions secret provisioning"
    $null = Invoke-ProcessWithInput -FilePath $GhExe -Arguments @("secret", "set", "ASTRA_RECEIPT_HMAC_KEY_B64", "--repo", $Repository) -InputText $receiptKeyB64 -Action "ASTRA receipt HMAC Actions secret provisioning"
    Write-Host "ASTRA_ACTIONS_SECRETS_SET"

    $secretPayload = ([ordered]@{
        task_hmac_key_b64 = $taskKeyB64
        receipt_hmac_key_b64 = $receiptKeyB64
        github_token = $workerToken
    } | ConvertTo-Json -Compress)

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction Stop
    }
    $PythonExe = $pythonCommand.Source

    $provision = Invoke-ProcessWithInput -FilePath $PythonExe -Arguments @($WorkerLauncher, "provision-secrets", "--stdin") -InputText $secretPayload -Action "DPAPI worker secret provisioning"
    if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
        throw "DPAPI provisioning returned success but secrets.bin is absent"
    }
    Write-Host "ASTRA_DPAPI_SECRETS_PROVISIONED"

    # Minimize cleartext lifetime before any further process is launched.
    $secretPayload = $null
    $workerToken = $null
    $taskKeyB64 = $null
    $receiptKeyB64 = $null
    if ($null -ne $workerTokenSecure) {
        $workerTokenSecure.Dispose()
        $workerTokenSecure = $null
    }

    $validation = Invoke-CapturedProcess -FilePath $PythonExe -Arguments @($WorkerLauncher, "validate-install") -Action "ASTRA install validation"
    if ($validation.Stdout -notmatch "ASTRA_INSTALL_OK") {
        throw "validate-install returned without ASTRA_INSTALL_OK"
    }
    Write-Host "ASTRA_INSTALL_VALIDATED"

    # Deliberately resolve the service executable only after validate-install has
    # succeeded, so no service start is possible before the installation gate.
    $WinSWExe = Join-Path $StateRoot "ASTRAWorker.exe"
    if (-not (Test-Path -LiteralPath $WinSWExe -PathType Leaf)) {
        throw "ASTRAWorker.exe is missing after successful install validation"
    }

    $null = Invoke-CapturedProcess -FilePath $WinSWExe -Arguments @("start") -Action "ASTRAWorker service start"

    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $service = Get-Service ASTRAWorker -ErrorAction Stop
        if ($service.Status -eq [ServiceProcess.ServiceControllerStatus]::Running) {
            break
        }
    } while ((Get-Date) -lt $deadline)

    Start-Sleep -Seconds 3
    $service = Get-Service ASTRAWorker -ErrorAction Stop
    if ($service.Status -ne [ServiceProcess.ServiceControllerStatus]::Running) {
        throw "ASTRAWorker did not remain Running after activation"
    }

    Write-Host "ASTRA_STAGE2_OK"
    Write-Host "HEAD=$currentHead"
    Write-Host "SERVICE=Running"
    Write-Host "DPAPI_SECRETS=True"
    Write-Host "ACTIONS_HMAC_SECRETS=True"
    Write-Host "LOG=$LogPath"
    $exitCode = 0
}
catch {
    Write-Error "ASTRA_STAGE2_FAILED: $($_.Exception.Message)"
    Write-Host "LOG=$LogPath"
    $exitCode = 1
}
finally {
    $secretPayload = $null
    $workerToken = $null
    $taskKeyB64 = $null
    $receiptKeyB64 = $null
    if ($null -ne $workerTokenSecure) {
        $workerTokenSecure.Dispose()
    }
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $exitCode
