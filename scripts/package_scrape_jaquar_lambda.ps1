param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LambdaDir = Join-Path $ProjectRoot "lambdas\scrape_jaquar_prices"
$BuildRoot = Join-Path $ProjectRoot "build"
$BuildDir = Join-Path $BuildRoot "scrape_jaquar_prices"
$ZipPath = Join-Path $BuildRoot "scrape_jaquar_prices_lambda.zip"

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

& $Python -m pip install -r (Join-Path $LambdaDir "requirements.txt") -t $BuildDir
Copy-Item (Join-Path $LambdaDir "lambda_function.py") $BuildDir

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $BuildDir "*") -DestinationPath $ZipPath
Write-Host "Created $ZipPath"
