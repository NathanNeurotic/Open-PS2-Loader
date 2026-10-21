Thanks for the detailed report and for attaching your RiptOPL folder, that saved a lot of guessing.

A reset straight to the PS2 browser on this path means Neutrino itself stopped with an error before the game started. Neutrino has no screen of its own, so the error never shows on the TV. While RiptOPL is running UDPFS, though, the PS2 broadcasts that text over your network on UDP port 18194, so a PC on the same network can catch it. One capture will tell us exactly which step fails.

**What you need:** the Windows PC that runs PS2 Servers, on the same network as the PS2. Nothing to install.

**1. Free port 18194.** PS2 Servers' RetroAchievements receiver uses the same port. If it is running, stop it (keep the UDPFS server running). Also close xeRAbora or any other achievements client.

**2. Start the listener.** Open PowerShell in a folder you can find again (for example your Desktop), paste this and press Enter:

```powershell
$udp = New-Object System.Net.Sockets.UdpClient 18194
$from = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
$log = Join-Path (Get-Location) 'neutrino-log.txt'
Write-Host "Listening on UDP 18194 -> $log  (Ctrl+C to stop)"
while ($true) {
    $bytes = $udp.Receive([ref]$from)
    if ($bytes.Length -le 2) { continue }
    $text = [System.Text.Encoding]::ASCII.GetString($bytes, 2, $bytes.Length - 2)
    Write-Host -NoNewline $text
    Add-Content -Path $log -Value $text -NoNewline
}
```

If Windows Firewall asks about PowerShell, allow it on **private** networks.

**3. (Optional, helps a lot)** In RiptOPL, turn on **Settings > Game Launching > Show Launch Arguments**. Before the launch, RiptOPL shows the exact arguments it passes to Neutrino. Take a photo of that screen, then confirm.

**4. Launch one game** the same way as before. Some text may appear in the PowerShell window as soon as you select it. That's expected.

**5.** When the PS2 is back at the browser, press **Ctrl+C** in PowerShell and attach `neutrino-log.txt` here, plus the photo from step 3 if you took one.

If the log stays completely empty, tell us that too. It narrows things down just as much.
