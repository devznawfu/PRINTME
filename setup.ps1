python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
git config core.hooksPath .githooks

# DOCX -> PDF conversion needs LibreOffice headless (CLAUDE.md: "LibreOffice
# headless or equivalent") - installed here, once, silently, so nobody running
# this PC day to day ever needs to know it exists or install it by hand. This
# is the one step in this whole script that needs real internet access.
if (Get-Command soffice.exe -ErrorAction SilentlyContinue) {
    Write-Host "LibreOffice already installed - skipping."
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing LibreOffice via winget (silent)..."
    winget install --id TheDocumentFoundation.LibreOffice -e --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "winget not found - downloading the LibreOffice installer directly..."
    $installerUrl = "https://download.documentfoundation.org/libreoffice/stable/25.2.4/win/x86_64/LibreOffice_25.2.4_Win_x86-64.msi"
    $installerPath = Join-Path $env:TEMP "LibreOffice_installer.msi"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    Write-Host "Running silent install (this can take a few minutes)..."
    Start-Process msiexec.exe -ArgumentList "/i `"$installerPath`" /qn /norestart" -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue
}

if (Get-Command soffice.exe -ErrorAction SilentlyContinue) {
    Write-Host "LibreOffice is ready - DOCX printing will work."
} else {
    Write-Warning "LibreOffice install could not be confirmed (soffice.exe not found on PATH yet - a new terminal or a reboot may be needed for PATH to update). DOCX jobs will fail until this is resolved."
}
