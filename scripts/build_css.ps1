# Rebuilds printme/static/css/output.css from printme/static/src/input.css
# using the Tailwind standalone CLI (tailwindcss.exe, repo root - not
# committed, not on the internet dependency path: this is a dev-time
# build step only, the compiled output.css is what actually ships).
#
# Usage: powershell -File scripts/build_css.ps1 [-Watch]

param(
    [switch]$Watch
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Tailwind = Join-Path $RepoRoot "tailwindcss.exe"
$Input = Join-Path $RepoRoot "printme\static\src\input.css"
$Output = Join-Path $RepoRoot "printme\static\css\output.css"

if (-not (Test-Path $Tailwind)) {
    Write-Error "tailwindcss.exe not found at $Tailwind - download the standalone CLI from https://github.com/tailwindlabs/tailwindcss/releases and place it at the repo root."
    exit 1
}

$cliArgs = @("-i", $Input, "-o", $Output)
if ($Watch) { $cliArgs += "--watch" }

& $Tailwind @cliArgs
