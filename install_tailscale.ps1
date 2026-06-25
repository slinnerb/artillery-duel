# Downloads and installs Tailscale. The game installer runs this only when
# Tailscale isn't already present. It always exits 0 so that a declined/failed
# Tailscale install never blocks the game from finishing installing.
$ErrorActionPreference = 'Stop'

$tsExe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (Test-Path $tsExe) {
    Write-Host 'Tailscale is already installed.'
    exit 0
}

$msi = Join-Path $env:TEMP 'tailscale-setup.msi'
try {
    Write-Host 'Downloading Tailscale...'
    Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi' `
        -OutFile $msi -UseBasicParsing

    Write-Host 'Installing Tailscale (please approve the Windows permission prompt)...'
    # /qn = silent; -Verb RunAs triggers the one UAC prompt Tailscale needs.
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Verb RunAs -PassThru -Wait
    if ($p.ExitCode -eq 0) {
        Write-Host 'Tailscale installed successfully.'
    } else {
        Write-Host "Tailscale installer returned exit code $($p.ExitCode)."
    }
} catch {
    Write-Host "Could not install Tailscale automatically: $($_.Exception.Message)"
    Write-Host 'You can install it later from https://tailscale.com/download'
} finally {
    Remove-Item $msi -ErrorAction SilentlyContinue
}
exit 0
