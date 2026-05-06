$lines = netstat -ano | Select-String ":8000"
foreach ($line in $lines) {
    $parts = $line.ToString().Trim() -split '\s+'
    $pid8000 = $parts[-1]
    if ($pid8000 -match '^\d+$') {
        Write-Host "Killing PID $pid8000"
        Stop-Process -Id ([int]$pid8000) -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

Remove-Item "C:\openclaw_agent\server_err.log","C:\openclaw_agent\server.log" -ErrorAction SilentlyContinue
Start-Process -FilePath "D:\Program_file\anaconda3\envs\openclaw\python.exe" `
    -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000") `
    -WorkingDirectory "C:\openclaw_agent" `
    -RedirectStandardOutput "C:\openclaw_agent\server.log" `
    -RedirectStandardError "C:\openclaw_agent\server_err.log" `
    -WindowStyle Hidden

Start-Sleep -Seconds 6
Write-Host "=== Server stderr ==="
Get-Content "C:\openclaw_agent\server_err.log"
