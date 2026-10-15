#!/usr/bin/env bash
set -euo pipefail
mkdir -p output
lease-extract --type 'Notice: Rent Change' \
  --input 'sample_inputs/rent increase 2025-2026 NT2.pdf' \
  --output 'output/notice.json' "$@"
lease-extract --type 'Lease: Residential (AST)' \
  --input 'sample_inputs/AST nt 2.pdf' \
  --output 'output/residential.json' "$@"
lease-extract --type 'Lease: Commercial' \
  --input 'sample_inputs/2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf' \
  --output 'output/commercial.json' "$@"
