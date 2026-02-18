param(
    [Parameter(Mandatory=$true)]
    [string]$ApplicationName,
    [Parameter(Mandatory=$true)]
    [string]$LogDirectory,
    [bool]$Force = $false,
    [bool]$AllowReboot = $false,
    [ValidateSet('Immediate', 'NonBusinessHours', 'AdminSchedule')]
    [string]$EnforcePreference = 'Immediate',
    [ValidateSet('Foreground', 'High', 'Normal', 'Low')]
    [string]$Priority = 'Normal',
    [switch]$NoWait
)

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$transcriptFile = Join-Path $LogDirectory "configmgr_transcript_${timestamp}_${ApplicationName}.log"

# Start transcript to capture everything
Start-Transcript -Path $transcriptFile -Force | Out-Null

try {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Starting update for application: $ApplicationName" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    # Get the application
    Write-Host "Querying ConfigMgr for application details..."
    $app = Get-CimInstance -ClassName CCM_Application -Namespace 'root\ccm\clientSDK' |
           Where-Object { $_.Name -eq $ApplicationName } |
           Select-Object -First 1

    if (-not $app) {
        Write-Host "Application not found: $ApplicationName" -ForegroundColor Red
        throw "Application not found"
    }

    Write-Host "Found application: $($app.Name) version $($app.SoftwareVersion)" -ForegroundColor Green
    Write-Host "Current InstallState: $($app.InstallState)"
    Write-Host "Current EvaluationState: $($app.EvaluationState)"

    # Check if already installed and not forcing
    if ($app.InstallState -eq 'Installed' -and -not $Force) {
        Write-Host "Application already installed. Use -Force to reinstall." -ForegroundColor Yellow
        @{
            Success = $true
            ApplicationName = $ApplicationName
            Message = "Application already installed"
            Status = "AlreadyInstalled"
            TranscriptFile = $transcriptFile
        } | ConvertTo-Json
        return
    }

    # Map EnforcePreference to numeric value
    $EnforcePreferenceMap = @{
        'Immediate'        = [uint32]0
        'NonBusinessHours' = [uint32]1
        'AdminSchedule'    = [uint32]2
    }

    # Build installation arguments
    $installArgs = @{
        EnforcePreference = $EnforcePreferenceMap[$EnforcePreference]
        Priority          = $Priority
        IsRebootIfNeeded  = $AllowReboot
        Id                = [string]$app.Id
        Revision          = [string]$app.Revision
        IsMachineTarget   = [bool]$app.IsMachineTarget
    }

    Write-Host "Installation parameters:" -ForegroundColor Cyan
    Write-Host "  EnforcePreference: $EnforcePreference (Numeric: $($installArgs.EnforcePreference))"
    Write-Host "  Priority: $($installArgs.Priority)"
    Write-Host "  IsRebootIfNeeded: $($installArgs.IsRebootIfNeeded)"
    Write-Host "  Id: $($installArgs.Id)"
    Write-Host "  Revision: $($installArgs.Revision)"
    Write-Host "  IsMachineTarget: $($installArgs.IsMachineTarget)"

    # Trigger installation using Install method
    Write-Host "Invoking installation..." -ForegroundColor Cyan
    $result = Invoke-CimMethod -Namespace 'root\ccm\clientSDK' -ClassName CCM_Application -MethodName Install -Arguments $installArgs

    Write-Host "Install method returned: ReturnValue=$($result.ReturnValue)"

    if ($result.ReturnValue -ne 0) {
        Write-Host "Installation returned non-zero code: $($result.ReturnValue)" -ForegroundColor Yellow
        @{
            Success = $false
            ApplicationName = $ApplicationName
            Message = "Installation returned code: $($result.ReturnValue)"
            ReturnValue = $result.ReturnValue
            Status = "Failed"
            TranscriptFile = $transcriptFile
        } | ConvertTo-Json
        return
    }

    Write-Host "Successfully initiated installation for: $ApplicationName" -ForegroundColor Green
    Write-Host "Installation triggered - not monitoring progress (NoWait mode)" -ForegroundColor Green

    @{
        Success = $true
        ApplicationName = $ApplicationName
        Message = "Installation initiated successfully"
        ReturnValue = $result.ReturnValue
        Status = "Initiated"
        TranscriptFile = $transcriptFile
    } | ConvertTo-Json
}
catch {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "Error updating $ApplicationName : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Exception Type: $($_.Exception.GetType().FullName)" -ForegroundColor Red

    if ($_.Exception.InnerException) {
        Write-Host "Inner Exception: $($_.Exception.InnerException.Message)" -ForegroundColor Red
    }

    Write-Host "Stack Trace:" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red

    @{
        Success = $false
        ApplicationName = $ApplicationName
        Message = $_.Exception.Message
        ExceptionType = $_.Exception.GetType().FullName
        Status = "Error"
        TranscriptFile = $transcriptFile
    } | ConvertTo-Json
}
finally {
    # Always stop transcript
    Stop-Transcript -ErrorAction SilentlyContinue
}
