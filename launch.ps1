# Shared PowerShell bootstrap. All paths are literal argument values, including spaces/CJK.
$ErrorActionPreference = 'Stop'
$appArgs = @($args)
$pythonExe = $null
$pythonPrefix = @()
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) {
    $pythonExe = $localPython
} else {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($version in @('-3.13', '-3.12', '-3')) {
            # Windows PowerShell 5.1 turns redirected native stderr into an error
            # record. A missing preferred version must not abort fallback probing.
            $ErrorActionPreference = 'Continue'
            & $pyLauncher.Source $version -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) and sys.maxsize > 2**32 else 1)' 2>$null
            $ErrorActionPreference = 'Stop'
            if ($LASTEXITCODE -eq 0) {
                $pythonExe = $pyLauncher.Source
                $pythonPrefix = @($version)
                break
            }
        }
    }
    if (-not $pythonExe) {
        $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($candidate) { $pythonExe = $candidate.Source }
    }
}
if (-not $pythonExe) {
    Write-Host 'Install 64-bit Python 3.13 from https://www.python.org/downloads/windows/ and enable Add Python to PATH.'
    exit 1
}
& $pythonExe @pythonPrefix (Join-Path $PSScriptRoot 'launcher.py') @appArgs
exit $LASTEXITCODE
