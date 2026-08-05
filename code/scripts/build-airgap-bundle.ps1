param(
    [string]$BundleDir = "",
    [string]$Tag = "",
    [string]$OnlyOfficeSourceImage = "onlyoffice/documentserver:9.3.1.2@sha256:0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31",
    [string]$OnlyOfficeFontBuilderSourceImage = "debian:bookworm-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e",
    [string]$RedisSourceImage = "redis:7-alpine",
    [string]$PostgresSourceImage = "pgvector/pgvector:pg16",
    [string]$MinioSourceImage = "minio/minio:RELEASE.2025-04-22T22-12-26Z",
    [switch]$IncludeOcr,
    [string]$OcrSourceImage = "vllm/vllm-openai:unlimited-ocr"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $($Command -join ' ')"
    }
}

function Ensure-Image {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    & docker image inspect $Image *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==> Reusing local $Label image..."
    } else {
        Write-Host "==> Pulling $Label image..."
        Invoke-Checked -Command @("docker", "pull", $Image)
    }
}

function Assert-DigestReference {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ($Image -notmatch "@sha256:[0-9a-f]{64}$") {
        throw "$Label must be pinned by sha256 digest: $Image"
    }
}

function Get-ComposeBuildCompatibilityArgs {
    $helpOutput = (& docker compose build --help 2>&1) -join "`n"
    if ($LASTEXITCODE -eq 0 -and $helpOutput -match "--provenance(?:\s|$)") {
        return @("--provenance=false")
    }

    Write-Warning "docker compose build does not support --provenance; continuing without disabling provenance."
    Write-Warning "Image IDs may vary across builds. Upgrade Docker Compose to 2.39 or newer to disable provenance."
    return @()
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $BundleDir) {
    $BundleDir = Join-Path $repoRoot "offline-dist"
}
if (-not $Tag) {
    $Tag = "offline-" + (Get-Date -Format "yyyyMMddHHmm")
}

$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)
$imagesDir = Join-Path $BundleDir "images"
$webImage = "sewpg-bid/web:$Tag"
$fastapiImage = "sewpg-bid/fastapi:$Tag"
$doclingImage = "sewpg-bid/docling-worker:$Tag"
$opencodeImage = "sewpg-bid/opencode:$Tag"
$onlyofficeImage = "sewpg-bid/onlyoffice:$Tag-fontpack-v1"
$redisImage = $RedisSourceImage
$postgresImage = $PostgresSourceImage
$minioImage = $MinioSourceImage
$ocrImage = $OcrSourceImage
$imageTar = Join-Path $imagesDir "sewpg-bid-images-$Tag.tar"
$manifestPath = Join-Path $BundleDir "bundle-manifest.json"
$checksumPath = Join-Path $BundleDir "SHA256SUMS"
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$gitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Cannot resolve the release Git SHA."
}
$gitStatus = (& git -C $repoRoot status --porcelain) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect the release Git worktree."
}
if ($gitStatus) {
    throw "Refusing to build a release bundle from a dirty worktree. Commit or remove tracked and untracked changes before retrying."
}

Assert-DigestReference -Image $OnlyOfficeSourceImage -Label "OnlyOffice base image"
Assert-DigestReference -Image $OnlyOfficeFontBuilderSourceImage -Label "OnlyOffice font builder image"

New-Item -ItemType Directory -Force -Path $imagesDir | Out-Null

$env:APP_IMAGE_TAG = $Tag
$env:WEB_IMAGE = $webImage
$env:FASTAPI_IMAGE = $fastapiImage
$env:DOCLING_IMAGE = $doclingImage
$env:OPENCODE_IMAGE = $opencodeImage
$env:ONLYOFFICE_IMAGE = $onlyofficeImage
$env:ONLYOFFICE_BASE_IMAGE = $OnlyOfficeSourceImage
$env:ONLYOFFICE_FONT_BUILDER_IMAGE = $OnlyOfficeFontBuilderSourceImage
$env:ONLYOFFICE_BUILD_REVISION = $gitSha
$env:REDIS_IMAGE = $redisImage
$env:OCR_IMAGE = $ocrImage

Write-Host "==> Building application and OnlyOffice font images..."
$composeBuildCommand = @("docker", "compose", "-f", $composeFile, "build")
$composeBuildCompatibilityArgs = @(Get-ComposeBuildCompatibilityArgs)
$composeBuildCommand += $composeBuildCompatibilityArgs
$composeBuildCommand += @("web", "fastapi", "docling-worker", "opencode", "onlyoffice")
Invoke-Checked -Command $composeBuildCommand
$onlyofficeImageId = (& docker image inspect --format "{{.Id}}" $onlyofficeImage).Trim()
if ($LASTEXITCODE -ne 0 -or -not $onlyofficeImageId) {
    throw "Cannot resolve the built OnlyOffice image ID."
}
Ensure-Image -Image $RedisSourceImage -Label "Redis"
Ensure-Image -Image $PostgresSourceImage -Label "PostgreSQL"
Ensure-Image -Image $MinioSourceImage -Label "MinIO"

if ($IncludeOcr) {
    Ensure-Image -Image $OcrSourceImage -Label "OCR vLLM"
}

if (Test-Path $imageTar) {
    Remove-Item $imageTar -Force
}

Write-Host "==> Exporting image bundle..."
$saveCommand = @(
    "docker",
    "save",
    "-o",
    $imageTar,
    $webImage,
    $fastapiImage,
    $doclingImage,
    $opencodeImage,
    $onlyofficeImage,
    $redisImage,
    $postgresImage,
    $minioImage
)
if ($IncludeOcr) {
    $saveCommand += $OcrSourceImage
}
Invoke-Checked -Command $saveCommand

Copy-Item (Join-Path $repoRoot "docker-compose.yml") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "docker-compose.airgap.yml") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "docker-compose.ocr.yml") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "docker-compose.ocr.airgap.yml") $BundleDir -Force
$envTemplatePath = Join-Path $BundleDir ".env.airgap.example"
Get-Content (Join-Path $repoRoot ".env.airgap.example") | ForEach-Object {
    if ($_ -match "^APP_IMAGE_TAG=") { "APP_IMAGE_TAG=$Tag" }
    elseif ($_ -match "^WEB_IMAGE=") { "WEB_IMAGE=sewpg-bid/web:$Tag" }
    elseif ($_ -match "^FASTAPI_IMAGE=") { "FASTAPI_IMAGE=sewpg-bid/fastapi:$Tag" }
    elseif ($_ -match "^DOCLING_IMAGE=") { "DOCLING_IMAGE=sewpg-bid/docling-worker:$Tag" }
    elseif ($_ -match "^OPENCODE_IMAGE=") { "OPENCODE_IMAGE=sewpg-bid/opencode:$Tag" }
    elseif ($_ -match "^ONLYOFFICE_IMAGE=") { "ONLYOFFICE_IMAGE=sewpg-bid/onlyoffice:$Tag-fontpack-v1" }
    else { $_ }
} | Set-Content -Encoding UTF8 $envTemplatePath
$onlyofficeConfigDir = Join-Path $BundleDir "sewpg-bid-backend\onlyoffice"
New-Item -ItemType Directory -Force -Path $onlyofficeConfigDir | Out-Null
Copy-Item (Join-Path $repoRoot "sewpg-bid-backend\onlyoffice\*") $onlyofficeConfigDir -Recurse -Force
$initdbDir = Join-Path $BundleDir "initdb"
New-Item -ItemType Directory -Force -Path $initdbDir | Out-Null
Copy-Item (Join-Path $repoRoot "initdb\*") $initdbDir -Recurse -Force
Copy-Item (Join-Path $repoRoot "scripts\load-airgap-images.sh") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "scripts\up-airgap.sh") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "scripts\up-ocr.sh") $BundleDir -Force

$images = @(
    $webImage,
    $fastapiImage,
    $doclingImage,
    $opencodeImage,
    $onlyofficeImage,
    $redisImage,
    $postgresImage,
    $minioImage
)
if ($IncludeOcr) {
    $images += $OcrSourceImage
}
$manifest = @{
    createdAt = (Get-Date).ToString("s")
    gitSha = $gitSha
    onlyofficeImageId = $onlyofficeImageId
    bundleFile = (Split-Path -Leaf $imageTar)
    images = $images
    composeFiles = @("docker-compose.yml", "docker-compose.airgap.yml", "docker-compose.ocr.yml", "docker-compose.ocr.airgap.yml")
    envTemplate = ".env.airgap.example"
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $manifestPath
$gitSha | Set-Content -Encoding ASCII (Join-Path $BundleDir "MAIN_SHA")

Get-ChildItem $BundleDir -Recurse -File |
    Where-Object { $_.FullName -ne $checksumPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = [System.IO.Path]::GetRelativePath($BundleDir, $_.FullName).Replace("\", "/")
        $hash = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relativePath"
    } |
    Set-Content -Encoding ASCII $checksumPath

Write-Host ""
Write-Host "Air-gapped bundle is ready:"
Write-Host "  Bundle dir : $BundleDir"
Write-Host "  Image tar  : $imageTar"
Write-Host "  Env sample : $(Join-Path $BundleDir '.env.airgap.example')"
Write-Host "  Git SHA    : $gitSha"
Write-Host "  Checksums  : $checksumPath"
