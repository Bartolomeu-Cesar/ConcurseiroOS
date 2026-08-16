<#
.SYNOPSIS
    Script de setup e inicialização do LeitorPDF.
    Verifica dependências, instala o que falta e inicia a aplicação.
#>

Set-Location $PSScriptRoot

# --- Configurações ---
$BackendDir    = Join-Path $PSScriptRoot "backend"
$RequirementsFile = Join-Path $BackendDir "requirements.txt"
$AppUrl        = "http://localhost:8000"
$PythonMinVersion = [version]"3.10"

# --- Funções auxiliares ---
function Write-Status {
    param([string]$Mensagem, [string]$Tipo = "INFO")
    $cor = switch ($Tipo) {
        "OK"    { "Green" }
        "AVISO" { "Yellow" }
        "ERRO"  { "Red" }
        default { "Cyan" }
    }
    Write-Host "[$Tipo] $Mensagem" -ForegroundColor $cor
}

function Get-PythonCommand {
    <#
    .DESCRIPTION
        Tenta localizar um interpretador Python real (não o alias do Windows Store).
        Retorna $null se nenhum for encontrado.
    #>
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $output = & $cmd --version 2>&1
            # Verifica se a saída realmente contém "Python X.Y.Z"
            if ($output -match "^Python (\d+\.\d+\.\d+)") {
                return @{ Command = $cmd; Version = $Matches[1] }
            }
        }
        catch {
            # Comando não existe ou falhou, tentar próximo
        }
    }
    return $null
}

# --- Banner ---
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   LeitorPDF - Setup e Inicializacao     " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. Verificar Python ---
Write-Status "Verificando instalacao do Python..."

$pythonInfo = Get-PythonCommand

if (-not $pythonInfo) {
    Write-Status "Python nao encontrado no sistema." "AVISO"
    Write-Status "Tentando instalar Python 3.12 via winget..." "INFO"

    if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Status "winget nao disponivel." "ERRO"
        Write-Status "Instale o Python 3.10+ manualmente: https://www.python.org/downloads/" "ERRO"
        Write-Status "IMPORTANTE: Marque 'Add Python to PATH' durante a instalacao." "ERRO"
        Write-Host ""
        Read-Host "Pressione Enter para sair"
        exit 1
    }

    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Falha na instalacao via winget." "ERRO"
        Write-Status "Instale manualmente: https://www.python.org/downloads/" "ERRO"
        Read-Host "Pressione Enter para sair"
        exit 1
    }

    # Atualizar PATH na sessão atual
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Re-verificar
    $pythonInfo = Get-PythonCommand
    if (-not $pythonInfo) {
        Write-Host ""
        Write-Status "Python foi instalado mas nao foi encontrado no PATH atual." "ERRO"
        Write-Status "Feche este terminal, abra um novo e execute o script novamente." "ERRO"
        Write-Host ""
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Status "Python instalado com sucesso." "OK"
}

$pythonCmd = $pythonInfo.Command
$pyVersionStr = $pythonInfo.Version
$pyVersion = [version]$pyVersionStr

if ($pyVersion -lt $PythonMinVersion) {
    Write-Status "Python $pyVersionStr encontrado, mas e necessario 3.10+. Atualize o Python." "ERRO"
    Write-Status "Baixe em: https://www.python.org/downloads/" "ERRO"
    Read-Host "Pressione Enter para sair"
    exit 1
}

Write-Status "Python $pyVersionStr encontrado ($pythonCmd)." "OK"

# --- 2. Verificar pip ---
Write-Status "Verificando pip..."

$pipVersionRaw = & $pythonCmd -m pip --version 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Write-Status "pip nao encontrado. Instalando..." "AVISO"
    & $pythonCmd -m ensurepip --upgrade 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Falha ao instalar pip. Tente: $pythonCmd -m ensurepip --upgrade" "ERRO"
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Status "pip instalado com sucesso." "OK"
}
else {
    $pipVersionInfo = if ($pipVersionRaw -match "pip (\S+)") { $Matches[1] } else { "?" }
    Write-Status "pip $pipVersionInfo disponivel." "OK"
}

# --- 3. Instalar dependências Python ---
Write-Status "Verificando dependencias Python..."

$requirements = Get-Content $RequirementsFile | Where-Object { $_ -match '\S' }
$todasInstaladas = $true

foreach ($pacote in $requirements) {
    $checkResult = & $pythonCmd -m pip show $pacote 2>&1
    if ($LASTEXITCODE -ne 0) {
        $todasInstaladas = $false
        Write-Status "Pacote '$pacote' nao encontrado. Sera instalado." "AVISO"
    }
    else {
        $versaoInstalada = if ($checkResult -match "Version: (.+)") { $Matches[1] } else { "?" }
        Write-Status "Pacote '$pacote' ($versaoInstalada) ja instalado." "OK"
    }
}

if (-not $todasInstaladas) {
    Write-Status "Instalando dependencias faltantes..."
    $pipOutput = & $pythonCmd -m pip install -r $RequirementsFile --quiet 2>&1
    $pipErrors = $pipOutput | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] -and $_.Exception.Message -notmatch "\[notice\]" }
    if ($LASTEXITCODE -ne 0 -and $pipErrors) {
        Write-Status "Erro ao instalar dependencias. Verifique sua conexao com a internet." "ERRO"
        $pipErrors | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Status "Todas as dependencias instaladas com sucesso." "OK"
}
else {
    Write-Status "Todas as dependencias ja estao instaladas." "OK"
}

# --- 4. Verificar se a porta 8000 está livre ---
Write-Status "Verificando porta 8000..."

$portaEmUso = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($portaEmUso) {
    $processoId = ($portaEmUso | Select-Object -First 1).OwningProcess
    $processo = Get-Process -Id $processoId -ErrorAction SilentlyContinue
    Write-Status "Porta 8000 em uso pelo processo '$($processo.ProcessName)' (PID: $processoId)." "AVISO"
    Write-Status "Encerrando processo existente..."
    Stop-Process -Id $processoId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Write-Status "Processo encerrado." "OK"
}
else {
    Write-Status "Porta 8000 livre." "OK"
}

# --- 5. Iniciar a aplicação ---
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "   Iniciando LeitorPDF...                " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Status "Abrindo navegador em $AppUrl em 2 segundos..."

# Abre o navegador após um pequeno delay (em background)
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process $using:AppUrl
} | Out-Null

# Inicia o servidor (bloqueia o terminal)
Set-Location $BackendDir
Write-Status "Servidor iniciando. Pressione Ctrl+C para encerrar." "INFO"
Write-Host ""
& $pythonCmd -m uvicorn main:app --host 0.0.0.0 --port 8000
