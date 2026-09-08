param(
    [Parameter(Mandatory = $true)][int]$Port
)

try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch {
    $conns = $null
}

if ($conns) {
    $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        $procName = "desconhecido"
        try {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) { $procName = $proc.ProcessName }
        } catch {}
        Write-Host "OCUPADA: porta $Port em uso por PID $procId ($procName)"
    }
    exit 1
} else {
    Write-Host "LIVRE: porta $Port"
    exit 0
}
