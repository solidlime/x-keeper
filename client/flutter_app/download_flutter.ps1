param(
    [string]$OutFile,
    [string]$DestDir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# バッチから渡されたパスに残留する引用符・末尾スラッシュを除去
$DestDir = $DestDir.Trim('"').TrimEnd('\').TrimEnd('/')
$OutFile = $OutFile.Trim('"')

Write-Host "[flutter-dl] DestDir : $DestDir"
Write-Host "[flutter-dl] OutFile : $OutFile"

# ──────────────────────────────────────────────────────
# 1/2  最新安定版 URL を取得してダウンロード
# ──────────────────────────────────────────────────────
Write-Host "[1/2] Fetching Flutter stable release list..."
try {
    $json = (Invoke-WebRequest `
        -Uri 'https://storage.googleapis.com/flutter_infra_release/releases/releases_windows.json' `
        -UseBasicParsing).Content | ConvertFrom-Json
} catch {
    Write-Error "[ERROR] Failed to fetch release list: $_"
    exit 1
}

$rel = $json.releases | Where-Object { $_.channel -eq 'stable' } | Select-Object -First 1
if (-not $rel) {
    Write-Error "[ERROR] No stable release found in JSON."
    exit 1
}
$url = $json.base_url + '/' + $rel.archive
Write-Host "[1/2] Downloading: $url"

try {
    Invoke-WebRequest -Uri $url -OutFile $OutFile -UseBasicParsing
} catch {
    Write-Error "[ERROR] Download failed: $_"
    exit 1
}

if (-not (Test-Path $OutFile)) {
    Write-Error "[ERROR] ZIP not found after download: $OutFile"
    exit 1
}
Write-Host "[1/2] Download OK  ($([math]::Round((Get-Item $OutFile).Length/1MB,1)) MB)"

# ──────────────────────────────────────────────────────
# 2/2  展開
# ──────────────────────────────────────────────────────
Write-Host "[2/2] Extracting to $DestDir ..."
try {
    Expand-Archive -Path $OutFile -DestinationPath $DestDir -Force
} catch {
    Write-Error "[ERROR] Extraction failed: $_"
    exit 1
}

$flutterBat = Join-Path $DestDir "flutter\bin\flutter.bat"
if (-not (Test-Path $flutterBat)) {
    Write-Error "[ERROR] flutter.bat not found after extraction. Expected: $flutterBat"
    exit 1
}

Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
Write-Host "[OK] Flutter installed: $flutterBat"
exit 0
