# Allows a friend to connect to your hosted game by opening TCP 50713 in
# Windows Firewall. The game installer runs this; it self-elevates (one UAC
# prompt) to make the change. It always exits 0 so a declined prompt or any
# error never blocks the install from finishing.
$ErrorActionPreference = 'SilentlyContinue'

$RuleName = 'Artillery Duel'
$Port     = 50713

# Re-launch elevated if we're not already an administrator.
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    try {
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    } catch {
        # User declined the UAC prompt — that's fine, just stop.
    }
    exit 0
}

# Elevated from here: remove any stale rule, then add a fresh inbound allow on
# all network profiles (Tailscale traffic is often classed as Public).
netsh advfirewall firewall delete rule name="$RuleName" | Out-Null
netsh advfirewall firewall add rule name="$RuleName" dir=in action=allow `
    protocol=TCP localport=$Port profile=any | Out-Null
exit 0
