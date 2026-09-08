param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSeconds = 45
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastError = ""

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            Write-Host "OK: $Url respondeu (HTTP $($resp.StatusCode))"
            exit 0
        }
    } catch {
        $lastError = $_.Exception.Message
        Start-Sleep -Milliseconds 800
    }
}

Write-Host "ERRO: $Url nao respondeu dentro de $TimeoutSeconds segundos."
if ($lastError) {
    Write-Host "Ultimo erro: $lastError"
}
exit 1
