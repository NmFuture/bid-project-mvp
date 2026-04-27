param(
    [string]$BundleDir = "",
    [string]$Tag = "",
    [string]$OnlyOfficeSourceImage = "onlyoffice/documentserver:9.3.1.2",
    [string]$RedisSourceImage = "redis:7-alpine"
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
$opencodeImage = "sewpg-bid/opencode:$Tag"
$onlyofficeImage = "sewpg-bid/onlyoffice:9.3.1.2"
$redisImage = $RedisSourceImage
$imageTar = Join-Path $imagesDir "sewpg-bid-images-$Tag.tar"
$manifestPath = Join-Path $BundleDir "bundle-manifest.json"
$composeFile = Join-Path $repoRoot "docker-compose.yml"

New-Item -ItemType Directory -Force -Path $imagesDir | Out-Null

$env:APP_IMAGE_TAG = $Tag
$env:WEB_IMAGE = $webImage
$env:FASTAPI_IMAGE = $fastapiImage
$env:OPENCODE_IMAGE = $opencodeImage
$env:ONLYOFFICE_IMAGE = $onlyofficeImage
$env:REDIS_IMAGE = $redisImage

Write-Host "==> Building application images..."
Invoke-Checked -Command @("docker", "compose", "-f", $composeFile, "build", "web", "fastapi", "opencode")

& docker image inspect $OnlyOfficeSourceImage *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Reusing local OnlyOffice image..."
} else {
    Write-Host "==> Pulling OnlyOffice image..."
    Invoke-Checked -Command @("docker", "pull", $OnlyOfficeSourceImage)
}

Write-Host "==> Retagging OnlyOffice image..."
Invoke-Checked -Command @("docker", "tag", $OnlyOfficeSourceImage, $onlyofficeImage)

& docker image inspect $RedisSourceImage *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Reusing local Redis image..."
} else {
    Write-Host "==> Pulling Redis image..."
    Invoke-Checked -Command @("docker", "pull", $RedisSourceImage)
}

if (Test-Path $imageTar) {
    Remove-Item $imageTar -Force
}

Write-Host "==> Exporting image bundle..."
Invoke-Checked -Command @(
    "docker",
    "save",
    "-o",
    $imageTar,
    $webImage,
    $fastapiImage,
    $opencodeImage,
    $onlyofficeImage,
    $redisImage
)

Copy-Item (Join-Path $repoRoot "docker-compose.yml") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "docker-compose.airgap.yml") $BundleDir -Force
Copy-Item (Join-Path $repoRoot ".env.airgap.example") $BundleDir -Force
$onlyofficeConfigDir = Join-Path $BundleDir "sewpg-bid-backend\onlyoffice"
New-Item -ItemType Directory -Force -Path $onlyofficeConfigDir | Out-Null
Copy-Item (Join-Path $repoRoot "sewpg-bid-backend\onlyoffice\docker-entrypoint.sh") $onlyofficeConfigDir -Force
Copy-Item (Join-Path $repoRoot "scripts\load-airgap-images.sh") $BundleDir -Force
Copy-Item (Join-Path $repoRoot "scripts\up-airgap.sh") $BundleDir -Force

$manifest = @{
    createdAt = (Get-Date).ToString("s")
    bundleFile = (Split-Path -Leaf $imageTar)
    images = @($webImage, $fastapiImage, $opencodeImage, $onlyofficeImage, $redisImage)
    composeFiles = @("docker-compose.yml", "docker-compose.airgap.yml")
    envTemplate = ".env.airgap.example"
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $manifestPath

Write-Host ""
Write-Host "Air-gapped bundle is ready:"
Write-Host "  Bundle dir : $BundleDir"
Write-Host "  Image tar  : $imageTar"
Write-Host "  Env sample : $(Join-Path $BundleDir '.env.airgap.example')"
