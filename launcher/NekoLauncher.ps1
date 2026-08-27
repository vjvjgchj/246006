param(
    [string]$ManifestUrl = "https://gitee.com/w246006/246006/raw/main/updates/stable.json",
    [string]$InstallDir = "",
    [switch]$NoLaunch,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$script:UpdatePublicKeyId = "neko-update-2026-08-27"
$script:UpdatePublicKeyModulus = "ulf+JmecuyfFay9/OYn9U4sNY+vndzW9dEPhRSxjCgkoPRdri8LKyQzyFNUYeKlmXim9jEwTjrfuszRcQThHj7Mf4csMXrUCHd/L4fawM6mHt97picczt5eAQr7GeqoGbJyJKbnlfa2HIqDXjsIHrsl8tzhwqS7Ii2XHbz7pRQgY6Ggz+zIGmoBgBut4WS481vwrTxE2fx1S79A0AmTNJjrhXjP3P61A+bPhmGSJGqodJMEJ0ZetMc9a80bHDpyQWfzuxmTmN8Kvc14WLZftmelgChm7hkwsslmCvLKUo9oQ7Y/CXb0f2mgY8SseroQWnOYlWfnIX3uo5qYA5OcEClVWNjZnA2ubM97YbQr2m8gsfM5KUDGv2tG0SczD27exzv3UyzI5uAiHnaXGM6cvjPM6HL3MP5sYAIMxsvFP0g/W2Fv9/OT5wEAwe7xYLXsgSJ4AXA9lfmrLmoUg4SvlxKh2mRjhpfMCGdi4CCdCqs9VKr4ZeF1XwiU3BDhsffvx"
$script:UpdatePublicKeyExponent = "AQAB"
$script:LegacyBootstrapManifests = @{
    "https://gitee.com/w246006/246006/raw/main/updates/stable.json" = "5D39FE423218229E806C4438F213F4E9632C66B567F1B6CA9874E3E301921C99"
    "https://raw.githubusercontent.com/vjvjgchj/246006/main/updates/stable.json" = "5D39FE423218229E806C4438F213F4E9632C66B567F1B6CA9874E3E301921C99"
}

function Write-Info($Message) {
    Write-Host "[INFO] $Message"
}

function Write-Warn($Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Resolve-DefaultInstallDir {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }
    return (Get-Location).Path
}

function Normalize-RelativePath([string]$Value) {
    $path = $Value -replace "\\", "/"
    if ($path -ne $path.Trim()) {
        throw "Unsafe update path: $Value"
    }
    if ([string]::IsNullOrWhiteSpace($path)) {
        throw "Empty update path."
    }
    if ($path.StartsWith("/")) {
        throw "Unsafe update path: $Value"
    }
    $parts = @()
    foreach ($part in $path.Split("/")) {
        if ([string]::IsNullOrEmpty($part) -or $part -eq ".") {
            continue
        }
        if ($part -eq ".." -or $part.EndsWith(".") -or $part.EndsWith(" ") -or $part.Contains(":") -or $part -match "^[^~]{1,6}~\d+(?:\.[^.]{0,3})?$") {
            throw "Unsafe Windows update path: $Value"
        }
        $parts += $part
    }
    if ($parts.Count -lt 1) {
        throw "Unsafe update path: $Value"
    }
    return $parts -join "/"
}

function ConvertTo-FullPath([string]$PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Assert-UnderPath([string]$PathValue, [string]$ParentPath) {
    $full = ConvertTo-FullPath $PathValue
    $parent = (ConvertTo-FullPath $ParentPath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    if (-not ($full.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($parent + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing path outside install dir: $full"
    }
    $relative = $full.Substring($parent.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $current = $parent
    foreach ($part in $relative.Split([System.IO.Path]::DirectorySeparatorChar, [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $current = Join-Path $current $part
        if (-not (Test-Path -LiteralPath $current)) {
            break
        }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing update path through a reparse point: $current"
        }
    }
}

function Test-SameOrChild([string]$Path, [string]$Parent) {
    $parent = $Parent.TrimEnd("/")
    return $Path.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase) -or $Path.StartsWith($parent + "/", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Sha256([string]$PathValue) {
    $getFileHash = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($null -ne $getFileHash) {
        return (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToUpperInvariant()
    }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($PathValue)
    try {
        return (($sha.ComputeHash($stream) | ForEach-Object { $_.ToString("X2") }) -join "")
    }
    finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Get-Sha256Bytes([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash($Bytes) | ForEach-Object { $_.ToString("X2") }) -join "")
    }
    finally {
        $sha.Dispose()
    }
}

function ConvertTo-CanonicalJson([object]$Value, [bool]$ExcludeTopLevelSignature = $false) {
    if ($null -eq $Value) {
        return "null"
    }
    if ($Value -is [string] -or $Value -is [char]) {
        return $script:JsonSerializer.Serialize([string]$Value)
    }
    if ($Value -is [bool]) {
        if ($Value) { return "true" }
        return "false"
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $names = [string[]]@($Value.Keys | ForEach-Object { [string]$_ })
        [Array]::Sort($names, [System.StringComparer]::Ordinal)
        $parts = @()
        foreach ($name in $names) {
            if ($ExcludeTopLevelSignature -and $name -eq "signature") { continue }
            $parts += $script:JsonSerializer.Serialize($name) + ":" + (ConvertTo-CanonicalJson $Value[$name])
        }
        return "{" + ($parts -join ",") + "}"
    }
    if ($Value -is [pscustomobject]) {
        $names = [string[]]@($Value.PSObject.Properties.Name)
        [Array]::Sort($names, [System.StringComparer]::Ordinal)
        $parts = @()
        foreach ($name in $names) {
            if ($ExcludeTopLevelSignature -and $name -eq "signature") { continue }
            $parts += $script:JsonSerializer.Serialize($name) + ":" + (ConvertTo-CanonicalJson $Value.$name)
        }
        return "{" + ($parts -join ",") + "}"
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $parts = @()
        foreach ($item in $Value) {
            $parts += ConvertTo-CanonicalJson $item
        }
        return "[" + ($parts -join ",") + "]"
    }
    if ($Value -is [double] -or $Value -is [single]) {
        return $Value.ToString("R", [Globalization.CultureInfo]::InvariantCulture)
    }
    if ($Value -is [decimal]) {
        return $Value.ToString([Globalization.CultureInfo]::InvariantCulture)
    }
    return [Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture)
}

function Test-ManifestSignature([object]$Manifest) {
    if ($null -eq $Manifest.signature) {
        return $false
    }
    if ([string]$Manifest.signature.key_id -ne $script:UpdatePublicKeyId -or [string]$Manifest.signature.algorithm -ne "RS256") {
        throw "Update manifest signature metadata is invalid."
    }
    try {
        $signature = [Convert]::FromBase64String([string]$Manifest.signature.value)
    }
    catch {
        throw "Update manifest signature encoding is invalid."
    }
    $canonical = ConvertTo-CanonicalJson $Manifest $true
    $data = [Text.Encoding]::UTF8.GetBytes($canonical)
    $parameters = New-Object System.Security.Cryptography.RSAParameters
    $parameters.Modulus = [Convert]::FromBase64String($script:UpdatePublicKeyModulus)
    $parameters.Exponent = [Convert]::FromBase64String($script:UpdatePublicKeyExponent)
    $rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider
    try {
        $rsa.ImportParameters($parameters)
        return $rsa.VerifyData($data, [System.Security.Cryptography.CryptoConfig]::MapNameToOID("SHA256"), $signature)
    }
    finally {
        $rsa.Dispose()
    }
}

function Assert-RemoteManifestAuthentic([string]$Url, [byte[]]$RawBytes, [object]$Manifest) {
    if ($null -ne $Manifest.signature) {
        if (-not (Test-ManifestSignature $Manifest)) {
            throw "Update manifest signature verification failed."
        }
        return
    }
    $expectedLegacyHash = $script:LegacyBootstrapManifests[$Url]
    if ($expectedLegacyHash -and (Get-Sha256Bytes $RawBytes) -eq $expectedLegacyHash) {
        return
    }
    throw "Remote update manifest is unsigned."
}

function Invoke-DownloadFile([string]$Url, [string]$OutputPath) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
    if ($Url.StartsWith("file://", [System.StringComparison]::OrdinalIgnoreCase)) {
        $localPath = ([Uri]$Url).LocalPath
        Copy-Item -LiteralPath $localPath -Destination $OutputPath -Force
        return
    }
    if (Test-Path -LiteralPath $Url -PathType Leaf) {
        Copy-Item -LiteralPath $Url -Destination $OutputPath -Force
        return
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $OutputPath -TimeoutSec 60
    }
    catch {
        Write-Warn "Invoke-WebRequest failed, trying WebClient fallback..."
        $client = New-Object System.Net.WebClient
        try {
            $client.DownloadFile($Url, $OutputPath)
        }
        finally {
            $client.Dispose()
        }
    }
}

function Get-Manifest([string]$Url, [string]$TempDir) {
    $manifestPath = ""
    $isRemote = $Url.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase) -or $Url.StartsWith("http://", [System.StringComparison]::OrdinalIgnoreCase)
    if ($Url.StartsWith("file://", [System.StringComparison]::OrdinalIgnoreCase)) {
        $manifestPath = ([Uri]$Url).LocalPath
    }
    elseif (Test-Path -LiteralPath $Url -PathType Leaf) {
        $manifestPath = $Url
    }
    else {
        $manifestPath = Join-Path $TempDir "stable.json"
        Invoke-DownloadFile $Url $manifestPath
    }
    $rawBytes = [System.IO.File]::ReadAllBytes($manifestPath)
    $manifest = [Text.Encoding]::UTF8.GetString($rawBytes) | ConvertFrom-Json
    if ($isRemote) {
        Assert-RemoteManifestAuthentic $Url $rawBytes $manifest
    }
    return $manifest
}

function Resolve-AssetUrl([string]$ManifestUrlValue, [string]$AssetUrl) {
    if ([Uri]::IsWellFormedUriString($AssetUrl, [UriKind]::Absolute)) {
        return $AssetUrl
    }
    if ([Uri]::IsWellFormedUriString($ManifestUrlValue, [UriKind]::Absolute)) {
        return ([Uri]::new([Uri]$ManifestUrlValue, $AssetUrl)).AbsoluteUri
    }
    $base = Split-Path -Parent (ConvertTo-FullPath $ManifestUrlValue)
    return Join-Path $base $AssetUrl
}

function Expand-SafeZip([string]$ZipPath, [string]$Destination, [string[]]$PreservePaths) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationFull = ConvertTo-FullPath $Destination
    $preserve = @()
    foreach ($item in $PreservePaths) {
        if (-not [string]::IsNullOrWhiteSpace($item)) {
            $preserve += (Normalize-RelativePath $item).ToLowerInvariant()
        }
    }

    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $zip.Entries) {
            if ([string]::IsNullOrWhiteSpace($entry.Name)) {
                continue
            }
            $relative = Normalize-RelativePath $entry.FullName
            $relativeLower = $relative.ToLowerInvariant()
            $skip = $false
            foreach ($blocked in $preserve) {
                if (Test-SameOrChild $relativeLower $blocked) {
                    Write-Info "Preserve local file, skip package member: $relative"
                    $skip = $true
                    break
                }
            }
            if ($skip) {
                continue
            }

            $target = Join-Path $destinationFull ($relative -replace "/", [System.IO.Path]::DirectorySeparatorChar)
            Assert-UnderPath $target $destinationFull
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    }
    finally {
        $zip.Dispose()
    }
}

function Assert-DeletableRelativePath([string]$RelativePath, [string[]]$PreservePaths) {
    $relative = Normalize-RelativePath $RelativePath
    $relativeLower = $relative.ToLowerInvariant()
    foreach ($item in $PreservePaths) {
        if ([string]::IsNullOrWhiteSpace($item)) {
            continue
        }
        $blocked = (Normalize-RelativePath $item).ToLowerInvariant()
        if ((Test-SameOrChild $relativeLower $blocked) -or (Test-SameOrChild $blocked $relativeLower)) {
            throw "Refusing to delete protected path: $relative"
        }
    }
    return $relative
}

function Remove-ManifestPaths([string]$InstallRoot, [object]$Manifest, [string[]]$PreservePaths) {
    $deletePaths = @()
    if ($Manifest.delete) {
        foreach ($item in $Manifest.delete) {
            $deletePaths += [string]$item
        }
    }
    if ($Manifest.remove) {
        foreach ($item in $Manifest.remove) {
            $deletePaths += [string]$item
        }
    }
    if ($deletePaths.Count -lt 1) {
        return
    }

    $installFull = ConvertTo-FullPath $InstallRoot
    foreach ($item in $deletePaths) {
        if ([string]::IsNullOrWhiteSpace($item)) {
            continue
        }
        $relative = Assert-DeletableRelativePath $item $PreservePaths
        $target = Join-Path $installFull ($relative -replace "/", [System.IO.Path]::DirectorySeparatorChar)
        Assert-UnderPath $target $installFull
        if (-not (Test-Path -LiteralPath $target)) {
            continue
        }
        Write-Info "Removing retired path: $relative"
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "PowerShell 5.1 or newer is required."
}
Add-Type -AssemblyName System.Web.Extensions
$script:JsonSerializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Resolve-DefaultInstallDir
}

$InstallDir = ConvertTo-FullPath $InstallDir
$stateDir = Join-Path $InstallDir ".updates"
$tempDir = Join-Path $stateDir "launcher_tmp"
$versionFile = Join-Path $stateDir "current_version.txt"

Write-Info "Manifest: $ManifestUrl"
Write-Info "Install:  $InstallDir"

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$manifest = Get-Manifest $ManifestUrl $tempDir
if ([string]::IsNullOrWhiteSpace($manifest.version)) {
    throw "Manifest has no version."
}
if ([string]$manifest.version -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$") {
    throw "Manifest version is unsafe."
}
if ($null -eq $manifest.packages -or $manifest.packages.Count -lt 1) {
    throw "Launcher requires a packages[] manifest. Current manifest does not contain packages[]."
}

$current = ""
if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
    $current = (Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8).Trim()
}

if (-not $Force -and $current -eq $manifest.version) {
    Write-Info "Already installed version $current."
}
else {
    $preserve = @(".updates", "runtime/config.txt", "runtime/logi_driver.dll", "gui_settings.json")
    if ($manifest.preserve) {
        foreach ($item in $manifest.preserve) {
            $preserve += [string]$item
        }
    }

    foreach ($package in $manifest.packages) {
        $name = [string]$package.name
        if ([string]::IsNullOrWhiteSpace($name)) {
            throw "Package name is empty."
        }
        $url = Resolve-AssetUrl $ManifestUrl ([string]$package.url)
        $safeName = ($name -replace "[^A-Za-z0-9._-]", "_").Trim("._-")
        if ([string]::IsNullOrWhiteSpace($safeName)) {
            $safeName = "package"
        }
        $zipPath = Join-Path $tempDir ($safeName + ".zip")
        if (-not $zipPath.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
            $zipPath = $zipPath + ".zip"
        }

        Write-Info "Downloading package: $name"
        Invoke-DownloadFile $url $zipPath

        $actualHash = Get-Sha256 $zipPath
        $expectedHash = ([string]$package.sha256).ToUpperInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "SHA256 mismatch for package $name. Expected $expectedHash, got $actualHash"
        }
        if ($package.size -and ((Get-Item -LiteralPath $zipPath).Length -ne [int64]$package.size)) {
            throw "Size mismatch for package $name."
        }

        Write-Info "Applying package: $name"
        Expand-SafeZip $zipPath $InstallDir $preserve
    }

    Remove-ManifestPaths $InstallDir $manifest $preserve

    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($versionFile, [string]$manifest.version, $utf8NoBom)
    Write-Info "Installed version $($manifest.version)."
}

if (-not $NoLaunch) {
    $entry = Join-Path $InstallDir "6_run_qml_panel.vbs"
    if (Test-Path -LiteralPath $entry -PathType Leaf) {
        Write-Info "Launching QML panel..."
        Start-Process -FilePath "wscript.exe" -ArgumentList @("`"$entry`"") -WorkingDirectory $InstallDir
    }
    else {
        Write-Warn "Panel entry not found: $entry"
        Write-Warn "Install may be package-only. Use a full package manifest for first install."
    }
}
