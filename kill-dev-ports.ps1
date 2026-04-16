# Free AlphaScan dev resources: Vite (:1420), uvicorn (:8000), and stray Python still
# holding market.duckdb (e.g. global Python from IDE while .bat uses .venv).
param(
    [string]$ProjectRoot = $PSScriptRoot
)

$ErrorActionPreference = 'SilentlyContinue'
$rootKey = $ProjectRoot.TrimEnd('\').ToLowerInvariant()

function Stop-ListenPort {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object {
                Write-Host "[kill-dev-ports] Stop PID $($_.OwningProcess) (port $port)"
                Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
            }
    }
}

Stop-ListenPort -Ports @(8000, 1420)
Start-Sleep -Milliseconds 400

# Second pass: Python launched as "uvicorn ..." from this repo (often holds DuckDB even if port state is odd)
Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
        $_.CommandLine -and
        ($_.CommandLine.ToLowerInvariant().Contains($rootKey)) -and
        ($_.CommandLine -match '(?i)uvicorn')
    } |
    ForEach-Object {
        Write-Host "[kill-dev-ports] Stop Python PID $($_.ProcessId) (uvicorn in this repo)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Let DuckDB / OS release file locks before the new uvicorn starts
Start-Sleep -Seconds 2
