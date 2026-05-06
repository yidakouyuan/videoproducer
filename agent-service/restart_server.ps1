# 杀掉占用 8000 端口的进程
$conn = netstat -ano | Select-String ":8000 "
if ($conn) {
    $pid8000 = ($conn -split '\s+')[-1]
    Stop-Process -Id $pid8000 -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $pid8000"
}
Start-Sleep -Seconds 2

# 重启
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
