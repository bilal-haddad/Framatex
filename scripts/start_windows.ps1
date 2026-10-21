<# Windows PowerShell 5.1+. Preparation only; the foreground Python supervisor
owns the exclusive socket, worker and Windows Job. No Start-Process Uvicorn,
asynchronous PowerShell callbacks, event subscriptions or WaitForExit race. #>
[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$Demo, [switch]$NoBrowser, [switch]$CheckOnly, [switch]$Reload
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$DemoEmail = 'admin.test@framatex.com'
$script:PythonExe = $null
$script:Secret = $null

function Invoke-Native([string]$File, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    # PowerShell 5.1 native stderr must not turn a successful pip into an exception.
    $ErrorActionPreference = 'Continue'
    try { & $File @Arguments; $script:NativeExit = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
}
function Invoke-Checked([string]$File, [string[]]$Arguments) {
    Invoke-Native $File $Arguments
    if ($script:NativeExit -ne 0) { throw "Commande en echec (code $script:NativeExit). Voir ci-dessus." }
}
function ConvertTo-PlainText([System.Security.SecureString]$Value) {
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
function Initialize-Python {
    $script:PythonExe = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $script:PythonExe)) {
        if (Test-Path -LiteralPath (Join-Path $Root '.venv')) {
            throw '.venv existe mais son Python Windows manque. Dossier conserve : utilisez un environnement Windows valide.'
        }
        $base = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($base) { Invoke-Checked $base.Source @('-3','-m','venv',(Join-Path $Root '.venv')) }
        else {
            $base = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $base) { throw 'Python 3.11+ introuvable. Installer Python depuis python.org (Add python.exe to PATH).' }
            Invoke-Checked $base.Source @('-m','venv',(Join-Path $Root '.venv'))
        }
    }
    Invoke-Checked $script:PythonExe @('-c','import sys; print(sys.executable, sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3,11) else 1)')
    $requirements = Join-Path $Root 'requirements.txt'
    if ($Demo) { $requirements = Join-Path $Root 'requirements-dev.txt' }
    Invoke-Native $script:PythonExe @((Join-Path $Root 'scripts\windows_preflight.py'),'deps')
    $install = $script:NativeExit -ne 0
    if ($Demo) {
        # Python quotes must be single quotes inside this argument: PowerShell
        # 5.1 native argv marshalling removes unescaped embedded double quotes.
        Invoke-Native $script:PythonExe @('-c',"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('playwright') else 1)")
        $install = $install -or ($script:NativeExit -ne 0)
    }
    if ($install) { Invoke-Checked $script:PythonExe @('-m','pip','install','--disable-pip-version-check','-r',$requirements) }
    Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_preflight.py'),'deps')
    if ($Demo) { Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_runtime.py'),'browser-deps') }
}
function Invoke-WithSecret([string[]]$Arguments) {
    $env:FRAMATEX_SECRET_INPUT = ConvertTo-PlainText $script:Secret
    try { Invoke-Native $script:PythonExe $Arguments }
    finally { Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue }
}
function Initialize-Demo {
    $preflight = Join-Path $Root 'scripts\windows_preflight.py'
    Invoke-Native $script:PythonExe @($preflight,'accounts','--email',$DemoEmail)
    $status = $script:NativeExit
    if ($status -ne 0 -and $status -ne 10) {
        throw "$DemoEmail doit etre un Administrateur actif. Aucun compte existant ne sera modifie automatiquement."
    }
    if (-not $script:Secret) {
        if ($status -eq 10) {
            $script:Secret = Read-Host "Mot de passe a definir pour $DemoEmail (12 a 256 caracteres)" -AsSecureString
            $confirm = Read-Host 'Confirmez le mot de passe' -AsSecureString
            $same = (ConvertTo-PlainText $script:Secret) -ceq (ConvertTo-PlainText $confirm)
            $confirm.Dispose()
            if (-not $same) { throw 'Les mots de passe saisis different.' }
        } else { $script:Secret = Read-Host "Mot de passe de $DemoEmail (verification obligatoire)" -AsSecureString }
    }
    if ($script:Secret.Length -lt 12 -or $script:Secret.Length -gt 256) { throw 'Mot de passe requis : 12 a 256 caracteres.' }
    if ($status -eq 10) {
        Invoke-WithSecret @($preflight,'create-admin','--email',$DemoEmail)
        if ($script:NativeExit -ne 0) { throw 'Creation du compte admin refusee.' }
    }
    Invoke-Checked $script:PythonExe @($preflight,'seed','--email',$DemoEmail)
}
if ($MyInvocation.InvocationName -eq '.') { return } # unit tests can dot-source
$exitCode = 1
$transcriptStarted = $false
try {
    Set-Location -LiteralPath $Root
    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    # Session only: never rewrite the registry or user proxy configuration.
    $env:NO_PROXY = (@($env:NO_PROXY -split ',' | Where-Object { $_ }) + @('localhost','127.0.0.1','::1') | Select-Object -Unique) -join ','
    if ($env:FRAMATEX_DEMO_PASSWORD) { $script:Secret = ConvertTo-SecureString $env:FRAMATEX_DEMO_PASSWORD -AsPlainText -Force }
    Remove-Item Env:FRAMATEX_DEMO_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue
    Initialize-Python
    $logs = Join-Path $Root 'data\logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    try {
        Start-Transcript -LiteralPath (Join-Path $logs ("start-windows-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) | Out-Null
        $transcriptStarted = $true
    } catch { Write-Warning 'Transcription indisponible ; journaux serveur conserves separement.' }
    if (Get-Command git.exe -ErrorAction SilentlyContinue) {
        Invoke-Checked 'git.exe' @('branch','--show-current')
        Invoke-Checked 'git.exe' @('rev-parse','HEAD')
    }
    Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_preflight.py'),'code')
    # Clean BEFORE SQLite. Serve performs another inventory for concurrent starts.
    Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_runtime.py'),'cleanup')
    Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_preflight.py'),'db')
    if ($Demo) { Initialize-Demo }
    else { Invoke-Checked $script:PythonExe @((Join-Path $Root 'scripts\windows_preflight.py'),'accounts') }
    if ($Reload) { Write-Warning '-Reload ignore : un seul worker sans reloader pour un port stable.' }
    $runtimeArgs = @((Join-Path $Root 'scripts\windows_runtime.py'),'serve','--port',"$Port")
    if ($Demo) { $runtimeArgs += @('--demo-email',$DemoEmail) }
    if ($NoBrowser) { $runtimeArgs += '--no-browser' }
    if ($CheckOnly) { $runtimeArgs += '--check-only'; Write-Host 'CheckOnly : arret EXPLICITE apres les verifications T+60 s.' }
    Write-Host 'Supervision au premier plan : Ctrl+C ou fermeture de cette fenetre = arret volontaire.'
    # No array/pipeline capture of this long-running native command.
    if ($Demo) { Invoke-WithSecret $runtimeArgs }
    else { Invoke-Native $script:PythonExe $runtimeArgs }
    $exitCode = $script:NativeExit
} catch {
    Write-Host ("ECHEC : {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Diagnostic sans modification de DB : .\scripts\diagnose_windows.cmd'
    $exitCode = 1
} finally {
    Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue
    Remove-Item Env:FRAMATEX_DEMO_PASSWORD -ErrorAction SilentlyContinue
    if ($script:Secret) { $script:Secret.Dispose(); $script:Secret = $null }
    if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
}
exit $exitCode
