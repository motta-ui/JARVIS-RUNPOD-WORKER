$ErrorActionPreference = 'Stop'
$Image = 'motta010203/jarvis-worker:v6'
Write-Host "Building $Image ..." -ForegroundColor Cyan
docker build -t $Image .
Write-Host "Pushing $Image ..." -ForegroundColor Cyan
docker push $Image
Write-Host "DONE: $Image" -ForegroundColor Green
