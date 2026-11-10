# Инсталиране на Data Analize Compilator без .exe (работи и при включен Smart App Control).
# Изисква Python 3.10+ (от Microsoft Store или python.org).
$ErrorActionPreference = 'Stop'
$repo = 'buildenthusiast/dataanalizecompilator'
$dest = Join-Path $env:LOCALAPPDATA 'DataAnalizeCompilator'

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw 'Python не е инсталиран. Инсталирайте Python 3.12 от Microsoft Store и пуснете отново.' }
& $py -c "import sys; assert sys.version_info >= (3,10), sys.version"
$pyw = & $py -c "import sys,os; p=os.path.join(os.path.dirname(sys.executable),'pythonw.exe'); print(p if os.path.exists(p) else sys.executable)"

Write-Host 'Изтегляне на последната версия...'
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'DataAnalizeCompilator' }
$zip = Join-Path $env:TEMP 'DataAnalizeCompilator_src.zip'
Invoke-WebRequest $rel.zipball_url -OutFile $zip -UseBasicParsing -Headers @{ 'User-Agent' = 'DataAnalizeCompilator' }
$tmp = Join-Path $env:TEMP ('DataAnalizeCompilator_' + [guid]::NewGuid())
Expand-Archive $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path (Join-Path $inner.FullName '*') -Destination $dest -Recurse -Force
Remove-Item $tmp -Recurse -Force; Remove-Item $zip -Force

Write-Host 'Инсталиране на библиотеките...'
& $py -m pip install --user -q --disable-pip-version-check -r (Join-Path $dest 'requirements.txt')

$launcher = Join-Path $dest 'DataAnalizeCompilator.pyw'
if (-not (Test-Path $launcher)) {
    Set-Content -Path $launcher -Encoding UTF8 -Value @(
        'import os, sys',
        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))',
        'from main import main',
        'sys.exit(main())')
}
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $ws.CreateShortcut((Join-Path $dir 'Data Analize Compilator.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "`"$launcher`""
    $lnk.WorkingDirectory = $dest
    $lnk.Save()
}
Write-Host "Готово: $dest (версия $($rel.tag_name)). Иконата е на работния плот."
