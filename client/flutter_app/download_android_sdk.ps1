param([string]$SDKDir)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$SDKDir = $SDKDir.Trim('"').TrimEnd('\').TrimEnd('/')
Write-Host "[android-sdk] SDKDir: $SDKDir"

# ─────────────────────────────────────────
# 0  JDK 確認 / 自動ダウンロード
# ─────────────────────────────────────────
function Find-JavaHome {
    if ($env:JAVA_HOME -and (Test-Path "$env:JAVA_HOME\bin\java.exe")) { return $env:JAVA_HOME }
    $j = Get-Command java -ErrorAction SilentlyContinue
    if ($j) {
        $p = Split-Path (Split-Path $j.Source)
        if (Test-Path "$p\bin\java.exe") { return $p }
    }
    foreach ($p in @(
        "$env:PROGRAMFILES\Android\Android Studio\jbr",
        "$env:LOCALAPPDATA\Programs\Android Studio\jbr"
    )) { if (Test-Path "$p\bin\java.exe") { return $p } }
    $local = Get-ChildItem "$SDKDir\jdk" -Directory -ErrorAction SilentlyContinue |
             Where-Object { Test-Path "$($_.FullName)\bin\java.exe" } |
             Select-Object -First 1
    if ($local) { return $local.FullName }
    return $null
}

$javaHome = Find-JavaHome
if (-not $javaHome) {
    Write-Host "[0/4] JDK not found. Downloading Adoptium JDK 21..."
    $rel = (Invoke-WebRequest `
        -Uri 'https://api.github.com/repos/adoptium/temurin21-binaries/releases/latest' `
        -UseBasicParsing).Content | ConvertFrom-Json
    $asset = $rel.assets |
             Where-Object { $_.name -match '^OpenJDK\d+U-jdk_x64_windows.*\.zip$' } |
             Select-Object -First 1
    if (-not $asset) { Write-Error "[ERROR] JDK zip asset not found."; exit 1 }

    $jdkZip = "$env:TEMP\temurin21.zip"
    Write-Host "[0/4] Downloading: $($asset.browser_download_url)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $jdkZip -UseBasicParsing
    $jdkDir = "$SDKDir\jdk"
    New-Item -ItemType Directory -Force -Path $jdkDir | Out-Null
    Write-Host "[0/4] Extracting JDK..."
    Expand-Archive -Path $jdkZip -DestinationPath $jdkDir -Force
    Remove-Item $jdkZip -Force -ErrorAction SilentlyContinue

    $javaHome = Find-JavaHome
    if (-not $javaHome) { Write-Error "[ERROR] java.exe not found after extraction."; exit 1 }
}
Write-Host "[0/4] JAVA_HOME: $javaHome"
$env:JAVA_HOME = $javaHome
$env:PATH      = "$javaHome\bin;$env:PATH"

# ─────────────────────────────────────────
# 1/4  cmdline-tools 確認 / ダウンロード
# ─────────────────────────────────────────
$sdkmanager = "$SDKDir\cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sdkmanager)) {
    Write-Host "[1/4] Resolving Android cmdline-tools URL..."
    $xml = [xml](Invoke-WebRequest `
        -Uri 'https://dl.google.com/android/repository/repository2-3.xml' `
        -UseBasicParsing).Content

    $pkg = $null
    foreach ($node in $xml.GetElementsByTagName("remotePackage")) {
        if ($node.GetAttribute("path") -eq "cmdline-tools;latest") { $pkg = $node; break }
    }
    if (-not $pkg) { Write-Error "[ERROR] cmdline-tools;latest not found."; exit 1 }

    $archive = $null
    foreach ($a in $pkg.GetElementsByTagName("archive")) {
        $osNode = $a.GetElementsByTagName("host-os")
        if ($osNode.Count -gt 0 -and $osNode[0].InnerText -eq "windows") { $archive = $a; break }
    }
    if (-not $archive) { Write-Error "[ERROR] Windows archive not found."; exit 1 }

    $url      = "https://dl.google.com/android/repository/" + $archive.GetElementsByTagName("url")[0].InnerText
    $toolsZip = "$env:TEMP\android_cmdtools.zip"
    $toolsDir  = "$SDKDir\cmdline-tools"

    Write-Host "[1/4] Downloading cmdline-tools: $url"
    Invoke-WebRequest -Uri $url -OutFile $toolsZip -UseBasicParsing
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    Write-Host "[1/4] Extracting..."
    Expand-Archive -Path $toolsZip -DestinationPath $toolsDir -Force
    Remove-Item $toolsZip -Force -ErrorAction SilentlyContinue

    $extracted = Get-ChildItem $toolsDir -Directory |
                 Where-Object { $_.Name -ne "latest" } | Select-Object -First 1
    if ($extracted) {
        $dest = "$toolsDir\latest"
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Rename-Item $extracted.FullName "latest"
    }
} else {
    Write-Host "[1/4] cmdline-tools already present."
}

if (-not (Test-Path $sdkmanager)) {
    Write-Error "[ERROR] sdkmanager.bat not found: $sdkmanager"; exit 1
}
Write-Host "[1/4] sdkmanager OK"

# ─────────────────────────────────────────
# 2/4  platform-tools が既にあればスキップ
# ─────────────────────────────────────────
if (Test-Path "$SDKDir\platform-tools\adb.exe") {
    Write-Host "[2/4] platform-tools already installed."
} else {
    Write-Host "[2/4] Accepting licenses..."
    "y`ny`ny`ny`ny`ny`ny`ny`ny`ny`n" | & $sdkmanager --licenses --sdk_root="$SDKDir" 2>&1 | Out-Null

    Write-Host "[2/4] Installing: platform-tools, platforms;android-35, build-tools;35.0.0 ..."
    & $sdkmanager --sdk_root="$SDKDir" `
        "platform-tools" `
        "platforms;android-35" `
        "build-tools;35.0.0" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Error "[ERROR] sdkmanager install failed."; exit 1 }
}

# ─────────────────────────────────────────
# 3/4  local.properties に sdk.dir を書き込む
# ─────────────────────────────────────────
$localProps    = Join-Path $PSScriptRoot "android\local.properties"
$sdkDirEscaped = $SDKDir.Replace('\', '/')
Write-Host "[3/4] Writing sdk.dir to $localProps ..."
$content = if (Test-Path $localProps) { Get-Content $localProps -Raw } else { "" }
if ($content -match "sdk\.dir=") {
    $content = $content -replace "sdk\.dir=[^\r\n]*(\r?\n)?", "sdk.dir=$sdkDirEscaped`r`n"
} else {
    $content = $content.TrimEnd() + "`r`nsdk.dir=$sdkDirEscaped`r`n"
}
Set-Content $localProps $content -NoNewline
Write-Host "[OK] Android SDK setup complete."
exit 0
