param([int]$RequestDelay = 5)
$ErrorActionPreference = 'Stop'
New-Item -Path 'output' -ItemType Directory -Force | Out-Null
lease-extract --type 'Notice: Rent Change' --input 'sample_inputs/rent increase 2025-2026 NT2.pdf' --output 'output/notice.json' --request-delay $RequestDelay
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
lease-extract --type 'Lease: Residential (AST)' --input 'sample_inputs/AST nt 2.pdf' --output 'output/residential.json' --request-delay $RequestDelay
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
lease-extract --type 'Lease: Commercial' --input 'sample_inputs/2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf' --output 'output/commercial.json' --request-delay $RequestDelay
exit $LASTEXITCODE
