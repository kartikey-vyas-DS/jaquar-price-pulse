$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LambdaDir = Join-Path $Root "lambdas\transform_prices"
$BuildDir = Join-Path $Root "build\transform_prices"
$ZipPath = Join-Path $Root "build\transform_prices_lambda.zip"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (!(Test-Path $Python)) {
    throw "Virtual environment Python not found at $Python"
}

if (Test-Path $BuildDir) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

& $Python -m pip install -r (Join-Path $LambdaDir "requirements.txt") -t $BuildDir
Copy-Item -LiteralPath (Join-Path $LambdaDir "lambda_function.py") -Destination $BuildDir

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $BuildDir "*") -DestinationPath $ZipPath

Write-Host "Created $ZipPath"
