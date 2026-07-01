param(
    [string]$OutputDir,
    [switch]$RuntimeOnly,
    [switch]$IncludeBuilder,
    [switch]$IncludeOnnxModels,
    [switch]$IncludePythonInstaller,
    [switch]$IncludeLogitechInstaller,
    [switch]$ReplaceOutput
)

$ErrorActionPreference = "Stop"

function Write-Info($Message) {
    Write-Host "[INFO] $Message"
}

function Write-Warn($Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Resolve-FullPath($PathValue) {
    $executionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PathValue)
}

function Assert-UnderPath($PathValue, $ParentPath) {
    $full = Resolve-FullPath $PathValue
    $parent = (Resolve-FullPath $ParentPath).TrimEnd('\')
    if (-not ($full.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($parent + "\", [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing to modify path outside expected directory: $full"
    }
}

function Copy-FileIfExists($Source, $DestinationDir) {
    if (Test-Path -LiteralPath $Source -PathType Leaf) {
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
        Copy-Item -LiteralPath $Source -Destination (Join-Path $DestinationDir (Split-Path -Leaf $Source)) -Force
        return $true
    }
    return $false
}

function Copy-DirFiltered($SourceDir, $DestinationDir, [string[]]$ExcludeDirNames, [scriptblock]$IncludeFile) {
    if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
        return
    }

    $sourceRoot = (Resolve-FullPath $SourceDir).TrimEnd('\')
    $destRoot = Resolve-FullPath $DestinationDir
    New-Item -ItemType Directory -Path $destRoot -Force | Out-Null

    Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
        if ([string]::IsNullOrWhiteSpace($relative)) {
            return
        }

        $parts = $relative -split '[\\/]'
        foreach ($part in $parts) {
            if ($ExcludeDirNames -contains $part) {
                return
            }
        }

        $target = Join-Path $destRoot $relative
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $target -Force | Out-Null
            return
        }

        if (& $IncludeFile $_) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

function Get-DirectorySizeBytes($PathValue) {
    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        return 0
    }
    $sum = 0L
    Get-ChildItem -LiteralPath $PathValue -Recurse -Force -File | ForEach-Object {
        $sum += $_.Length
    }
    return $sum
}

function Format-Size($Bytes) {
    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }
    return "$Bytes B"
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = Join-Path $ProjectRoot "dist"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path $DistRoot "neko_release_qml_$stamp"
}

$OutputDir = Resolve-FullPath $OutputDir
Assert-UnderPath $OutputDir $DistRoot

if (Test-Path -LiteralPath $OutputDir) {
    if (-not $ReplaceOutput) {
        throw "Output already exists. Use -ReplaceOutput or choose a new -OutputDir: $OutputDir"
    }
    Assert-UnderPath $OutputDir $DistRoot
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Write-Info "Project: $ProjectRoot"
Write-Info "Output:  $OutputDir"

$runtimeSource = Join-Path $ProjectRoot "runtime"
$runtimeDest = Join-Path $OutputDir "runtime"
New-Item -ItemType Directory -Path $runtimeDest -Force | Out-Null

$rootFiles = @(
    "5_install_panel_python_deps.bat",
    "6_run_qml_panel.vbs",
    "6_run_web_panel.vbs",
    "run_panel_hidden.pyw",
    "run_web_panel_hidden.pyw",
    "gui_qml_trial.py",
    "gui_settings.json",
    "panel_requirements.txt",
    "NekoLauncher.bat",
    "NekoLauncher.ps1"
)

foreach ($file in $rootFiles) {
    $src = Join-Path $ProjectRoot $file
    if (-not (Copy-FileIfExists $src $OutputDir)) {
        Write-Warn "Missing optional root file: $file"
    }
}

$docs = Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "*.md" | Where-Object {
    $_.Name -ne "README.md"
}
foreach ($doc in $docs) {
    Copy-Item -LiteralPath $doc.FullName -Destination (Join-Path $OutputDir $doc.Name) -Force
}

if ($IncludePythonInstaller) {
    Copy-FileIfExists (Join-Path $ProjectRoot "python-3.11.9-amd64.exe") $OutputDir | Out-Null
}

if ($IncludeLogitechInstaller) {
    $logitechInstaller = Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "*2021.3.exe" | Select-Object -First 1
    if ($null -ne $logitechInstaller) {
        Copy-FileIfExists $logitechInstaller.FullName $OutputDir | Out-Null
    }
    else {
        Write-Warn "Logitech installer was requested but no *2021.3.exe file was found."
    }
}

Copy-DirFiltered `
    -SourceDir (Join-Path $ProjectRoot "backend") `
    -DestinationDir (Join-Path $OutputDir "backend") `
    -ExcludeDirNames @("__pycache__") `
    -IncludeFile { param($File) $File.Extension -ieq ".py" }

Copy-DirFiltered `
    -SourceDir (Join-Path $ProjectRoot "qml") `
    -DestinationDir (Join-Path $OutputDir "qml") `
    -ExcludeDirNames @("__pycache__") `
    -IncludeFile { param($File) $true }

Copy-DirFiltered `
    -SourceDir (Join-Path $ProjectRoot "updates") `
    -DestinationDir (Join-Path $OutputDir "updates") `
    -ExcludeDirNames @("__pycache__") `
    -IncludeFile {
        param($File)
        return $File.Extension -in @(".json", ".md")
    }

$runtimeTopLevelFiles = @(
    "TRT_ZeroCopy_Pipeline.exe",
    "TexturePreprocessPlugin.dll",
    "build_texture_preprocess_engine.exe",
    "config.txt",
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudart64_12.dll",
    "cudnn64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudnn_graph64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_ops64_9.dll",
    "logi_driver.dll",
    "nvfatbin_120_0.dll",
    "nvinfer_10.dll",
    "nvinfer_plugin_10.dll",
    "nvJitLink_120_0.dll",
    "nvrtc64_120_0.dll",
    "nvrtc-builtins64_124.dll"
)

foreach ($file in $runtimeTopLevelFiles) {
    $src = Join-Path $runtimeSource $file
    if (-not (Copy-FileIfExists $src $runtimeDest)) {
        Write-Warn "Missing optional runtime file: $file"
    }
}

Copy-DirFiltered `
    -SourceDir (Join-Path $runtimeSource "models") `
    -DestinationDir (Join-Path $runtimeDest "models") `
    -ExcludeDirNames @("__pycache__") `
    -IncludeFile {
        param($File)
        if ($File.Extension -ieq ".engine") { return $true }
        if ($IncludeOnnxModels -and $File.Extension -ieq ".onnx") { return $true }
        return $false
    }

if (-not $RuntimeOnly) {
    Copy-DirFiltered `
        -SourceDir (Join-Path $ProjectRoot "models") `
        -DestinationDir (Join-Path $OutputDir "models") `
        -ExcludeDirNames @("__pycache__") `
        -IncludeFile {
            param($File)
            if ($File.Extension -ieq ".engine") { return $true }
            if ($IncludeOnnxModels -and $File.Extension -ieq ".onnx") { return $true }
            return $false
        }
}

$vcRedistSource = Join-Path $ProjectRoot "engine_builder\prerequisites\VC_redist.x64.exe"
if (Copy-FileIfExists $vcRedistSource (Join-Path $OutputDir "prerequisites")) {
    @'
@echo off
setlocal
cd /d "%~dp0"

set "REDIST=%~dp0prerequisites\VC_redist.x64.exe"
if not exist "%REDIST%" (
    echo [ERROR] VC_redist.x64.exe not found.
    pause
    exit /b 1
)

echo [INFO] Launching VC++ x64 Redistributable installer...
start "" "%REDIST%"
pause
'@ | Set-Content -LiteralPath (Join-Path $OutputDir "1_install_vcredist.bat") -Encoding ASCII
}
else {
    Write-Warn "VC_redist.x64.exe not found; 1_install_vcredist.bat was not generated."
}

if ($IncludeBuilder) {
    Copy-DirFiltered `
        -SourceDir (Join-Path $ProjectRoot "engine_builder") `
        -DestinationDir (Join-Path $OutputDir "engine_builder") `
        -ExcludeDirNames @("__pycache__", "output") `
        -IncludeFile { param($File) $true }
}

$readme = @'
# Neko Clean Release Package

This package is generated by `8_make_clean_release.bat` and uses the QML panel as the main entry.

## Included
- QML panel entry: `6_run_qml_panel.vbs`
- QML panel controller: `run_panel_hidden.pyw`, `gui_qml_trial.py`, `qml/`, and `backend/qml_bridge.py`
- Web fallback entry: `6_run_web_panel.vbs`
- Runtime core: `runtime/TRT_ZeroCopy_Pipeline.exe`
- Runtime config: `runtime/config.txt`
- TensorRT/CUDA runtime DLLs
- `runtime/models/*.engine`
- Root `models/*.engine`
- VC++ x64 redistributable installer when available

## Removed
- `.codex/`
- `branches/`
- `simulators/`
- `firmware/`
- `tools/`
- `__pycache__/`
- test binaries and temporary configs
- `.bak` backup files
- `.onnx` source models by default
- full ONNX -> TensorRT builder by default

## Usage

1. Run `1_install_vcredist.bat` to install the VC++ runtime.
2. Run `5_install_panel_python_deps.bat` if Python dependencies are missing.
3. Double-click `6_run_qml_panel.vbs` to start the QML panel.

## Optional Rebuild Flags

```bat
8_make_clean_release.bat -RuntimeOnly
8_make_clean_release.bat -IncludePythonInstaller
8_make_clean_release.bat -IncludeOnnxModels
8_make_clean_release.bat -IncludeBuilder
8_make_clean_release.bat -IncludeLogitechInstaller
```
'@
$readme | Set-Content -LiteralPath (Join-Path $OutputDir "README_RELEASE.md") -Encoding UTF8

$manifest = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    project_root = [string]$ProjectRoot
    output_dir = $OutputDir
    panel_mode = "qml"
    runtime_only = [bool]$RuntimeOnly
    include_builder = [bool]$IncludeBuilder
    include_onnx_models = [bool]$IncludeOnnxModels
    include_python_installer = [bool]$IncludePythonInstaller
    include_logitech_installer = [bool]$IncludeLogitechInstaller
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDir "release_manifest.json") -Encoding UTF8

$sourceSize = Get-DirectorySizeBytes $ProjectRoot
$outputSize = Get-DirectorySizeBytes $OutputDir
Write-Info "Source size: $(Format-Size $sourceSize)"
Write-Info "Output size: $(Format-Size $outputSize)"
Write-Info "QML-main clean release ready: $OutputDir"
