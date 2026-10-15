# Reset the local Supabase database (migrations + empty seed).
# On Windows/Docker Desktop the CLI times out unless SSL is disabled for local Postgres.
$ErrorActionPreference = "Stop"
$env:PGSSLMODE = "disable"
Set-Location (Join-Path $PSScriptRoot "..")
supabase db reset @args
