$base = "http://127.0.0.1:8000"
$PASS = "[PASS]"
$FAIL = "[FAIL]"

function Test-API {
    param($name, $method, $url, $body)
    try {
        if ($body) {
            $resp = Invoke-WebRequest -Method $method -Uri $url -Body (ConvertTo-Json $body -Depth 5) -ContentType "application/json" -UseBasicParsing -ErrorAction Stop
        } else {
            $resp = Invoke-WebRequest -Method $method -Uri $url -UseBasicParsing -ErrorAction Stop
        }
        $json = $resp.Content | ConvertFrom-Json
        Write-Host "$PASS $name" -ForegroundColor Green
        Write-Host "      HTTP $($resp.StatusCode) | ok=$($json.ok)"
        Write-Host "      data=$(($json.data | ConvertTo-Json -Compress -Depth 4))"
        return $json
    } catch {
        $status = $_.Exception.Response.StatusCode.value__
        Write-Host "$FAIL $name" -ForegroundColor Red
        Write-Host "      HTTP $status | $($_.Exception.Message)"
        try {
            $errBody = $_.ErrorDetails.Message | ConvertFrom-Json
            Write-Host "      error_data=$($errBody | ConvertTo-Json -Compress -Depth 3)"
        } catch {}
        return $null
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " OpenClaw Agent API Test" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# 0. Health
Test-API "0. GET  /health" "GET" "$base/health" | Out-Null

# ---- Media ----
# 1. POST /media/resolve_video
$r1 = Test-API "1. POST /media/resolve_video" "POST" "$base/media/resolve_video" @{
    platform = "douyin"
    source_type = "video"
    source_id = "test_vid_001"
    share_url = "https://www.douyin.com/video/test001"
}

# 2. POST /media/fetch_video  (需要 resolved_video_ref)
$resolved_ref = $null
if ($r1 -and $r1.data.resolved_video_ref) {
    $resolved_ref = $r1.data.resolved_video_ref
} else {
    # mock: 直接构造
    $resolved_ref = @{
        platform = "douyin"
        source_type = "video"
        source_id = "test_vid_001"
        source_url = "https://www.douyin.com/video/test001"
        video_url = "https://example.com/video.mp4"
        downloadable = $true
        title = "Test Video"
        author = "Test Author"
    }
}
$r2 = Test-API "2. POST /media/fetch_video" "POST" "$base/media/fetch_video" @{
    resolved_video_ref = $resolved_ref
}

# 拿到 media_id 用于后续测试
$media_id = $null
if ($r2 -and $r2.data.media_id) {
    $media_id = $r2.data.media_id
    Write-Host "      >> media_id=$media_id" -ForegroundColor Yellow
}

# 3. POST /media/cleanup (dry_run)
Test-API "3. POST /media/cleanup (dry_run)" "POST" "$base/media/cleanup" @{
    dry_run = $true
    older_than_hours = 0
} | Out-Null

# ---- Transcribe ----
# 4. POST /transcribe/start
$r4 = Test-API "4. POST /transcribe/start" "POST" "$base/transcribe/start" @{
    media_id = if ($media_id) { $media_id } else { "md_mock_001" }
    lang = "zh"
    mode = "highlights"
}

$job_id_tr = $null
if ($r4 -and $r4.data.job_id) {
    $job_id_tr = $r4.data.job_id
    Write-Host "      >> transcribe job_id=$job_id_tr" -ForegroundColor Yellow
}

# 5. GET /transcribe/result/{job_id}
if ($job_id_tr) {
    Start-Sleep -Seconds 3
    Test-API "5. GET  /transcribe/result/$job_id_tr" "GET" "$base/transcribe/result/$job_id_tr" | Out-Null
}

# 6. DELETE /transcribe/{job_id}
if ($job_id_tr) {
    Test-API "6. DELETE /transcribe/$job_id_tr" "DELETE" "$base/transcribe/$job_id_tr" | Out-Null
}

# ---- Video Analyze ----
# 7. POST /video/analyze/start
$r7 = Test-API "7. POST /video/analyze/start" "POST" "$base/video/analyze/start" @{
    media_id = if ($media_id) { $media_id } else { "md_mock_001" }
    analysis_types = @("content", "tags", "highlights")
    lang = "zh"
}

$job_id_va = $null
if ($r7 -and $r7.data.job_id) {
    $job_id_va = $r7.data.job_id
    Write-Host "      >> analyze job_id=$job_id_va" -ForegroundColor Yellow
}

# 8. GET /video/analyze/result/{job_id}
if ($job_id_va) {
    Start-Sleep -Seconds 3
    Test-API "8. GET  /video/analyze/result/$job_id_va" "GET" "$base/video/analyze/result/$job_id_va" | Out-Null
}

# 9. DELETE /video/analyze/{job_id}
if ($job_id_va) {
    Test-API "9. DELETE /video/analyze/$job_id_va" "DELETE" "$base/video/analyze/$job_id_va" | Out-Null
}

# ---- Tag ----
# 10. POST /tag/script_pack
Test-API "10. POST /tag/script_pack" "POST" "$base/tag/script_pack" @{
    tag = "搞笑"
} | Out-Null

# ---- Media cleanup final ----
# 11. DELETE /media/{media_id}
if ($media_id) {
    Test-API "11. DELETE /media/$media_id" "DELETE" "$base/media/$media_id" | Out-Null
}

Write-Host "`n=======================================" -ForegroundColor Cyan
Write-Host " Test complete" -ForegroundColor Cyan
Write-Host "=======================================`n" -ForegroundColor Cyan
