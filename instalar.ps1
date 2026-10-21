# Instala dependências e cria os atalhos (Área de Trabalho + iniciar com o Windows).
# Uso: powershell -ExecutionPolicy Bypass -File instalar.ps1
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot

winget install --id OpenRGB.OpenRGB -e --accept-source-agreements --accept-package-agreements
python -m pip install -r "$dir\requirements.txt"

$pyw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
$ws = New-Object -ComObject WScript.Shell
$icon = 'C:\Program Files\OpenRGB\OpenRGB.exe,0'

$desk = $ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\LED Sync.lnk")
$desk.TargetPath = $pyw; $desk.Arguments = "`"$dir\ledsync.py`""
$desk.WorkingDirectory = $dir; $desk.IconLocation = $icon; $desk.Save()

$boot = $ws.CreateShortcut("$([Environment]::GetFolderPath('Startup'))\LED Sync.lnk")
$boot.TargetPath = $pyw; $boot.Arguments = "`"$dir\ledsync.py`" --background"
$boot.WorkingDirectory = $dir; $boot.IconLocation = $icon; $boot.WindowStyle = 7; $boot.Save()

Write-Host "Pronto. Use o atalho 'LED Sync' na Área de Trabalho."
