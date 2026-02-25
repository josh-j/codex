[CmdletBinding()]
param([string[]]$Accounts)
$ErrorActionPreference='Stop'
$maxAge = 30
$now = Get-Date
$out = foreach ($n in $Accounts) {
  try {
    $u = Get-LocalUser -Name $n -ErrorAction Stop
    $pls = $u.PasswordLastSet
    $expires = $null
    if (-not $u.PasswordNeverExpires -and $pls -and $maxAge) {
      $expires = $pls.AddDays($maxAge)
    }
    [pscustomobject]@{
      Account         = $n
      PasswordLastSet = $pls
      MaxPasswordAge  = $maxAge
      PasswordExpires = $expires
      DaysUntilExpiry = if ($expires) { [math]::Floor(($expires - $now).TotalDays) } else { $null }
    }
  } catch {
    [pscustomobject]@{ Account=$n; Error=$_.Exception.Message }
  }
}
$out | ConvertTo-Json -Depth 5
