param(
    [string]$ManifestUrl = "https://gitee.com/w246006/246006/raw/main/updates/stable.json",
    [string]$InstallDir = "",
    [switch]$NoLaunch,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

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
    $path = ($Value -replace "\\", "/").Trim().TrimStart("/")
    if ([string]::IsNullOrWhiteSpace($path)) {
        throw "Empty update path."
    }
    if ($path.StartsWith("../") -or $path.Contains("/../") -or $path.Contains(":")) {
        throw "Unsafe update path: $Value"
    }
    return $path
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
}

function Test-SameOrChild([string]$Path, [string]$Parent) {
    $parent = $Parent.TrimEnd("/")
    return $Path.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase) -or $Path.StartsWith($parent + "/", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Sha256([string]$PathValue) {
    return (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToUpperInvariant()
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
    if ($Url.StartsWith("file://", [System.StringComparison]::OrdinalIgnoreCase)) {
        $manifestPath = ([Uri]$Url).LocalPath
        return Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    if (Test-Path -LiteralPath $Url -PathType Leaf) {
        return Get-Content -LiteralPath $Url -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $manifestPath = Join-Path $TempDir "stable.json"
    Invoke-DownloadFile $Url $manifestPath
    return Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
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
    $entry = Join-Path $InstallDir "6_run_web_panel.vbs"
    if (Test-Path -LiteralPath $entry -PathType Leaf) {
        Write-Info "Launching web panel..."
        Start-Process -FilePath "wscript.exe" -ArgumentList @("`"$entry`"") -WorkingDirectory $InstallDir
    }
    else {
        Write-Warn "Panel entry not found: $entry"
        Write-Warn "Install may be package-only. Use a full package manifest for first install."
    }
}
