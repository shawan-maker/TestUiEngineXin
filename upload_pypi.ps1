# upload_pypi.ps1 - PyPI 上传脚本（带代理）
# 使用方法: .\upload_pypi.ps1

# 设置代理（根据你的代理软件端口修改）
$proxy_ports = @{
    "Clash"    = 7890
    "V2rayN"   = 10809
    "SSR"      = 1080
    "Shadowsocks" = 8388
}

# 自动检测可用代理
$proxy_found = $false
foreach ($name, $port in $proxy_ports.GetEnumerator()) {
    $test = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
    if ($test.TcpTestSucceeded) {
        Write-Host "检测到 $name 代理 (端口 $port)" -ForegroundColor Green
        $env:HTTP_PROXY = "http://127.0.0.1:$port"
        $env:HTTPS_PROXY = "http://127.0.0.1:$port"
        $proxy_found = $true
        break
    }
}

if (-not $proxy_found) {
    Write-Host "未检测到常见代理，请手动设置：" -ForegroundColor Yellow
    Write-Host '$env:HTTP_PROXY="http://127.0.0.1:你的代理端口"'
    Write-Host '$env:HTTPS_PROXY="http://127.0.0.1:你的代理端口"'
    exit 1
}

# 上传
Write-Host "正在上传到 PyPI..." -ForegroundColor Cyan
twine upload dist/* --timeout 60
