<#
.SYNOPSIS
    ConcurseiroOS - Setup e Inicialização
    Verifica dependências, instala o que falta e inicia a aplicação com hot-reload.
#>

Set-Location $PSScriptRoot

# --- Configurações ---
$BackendDir       = Join-Path $PSScriptRoot "backend"
$RequirementsFile = Join-Path $BackendDir "requirements.txt"
$AppUrl           = "http://localhost:8000"
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
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $output = & $cmd --version 2>&1
            if ($output -match "^Python (\d+\.\d+\.\d+)") {
                return @{ Command = $cmd; Version = $Matches[1] }
            }
        }
        catch {}
    }
    return $null
}

# --- Banner ---
Write-Host ""
Write-Host "=================================================" -ForegroundColor Magenta
Write-Host "   ConcurseiroOS - Plataforma de Estudos         " -ForegroundColor Magenta
Write-Host "   Setup e Inicializacao                          " -ForegroundColor Magenta
Write-Host "=================================================" -ForegroundColor Magenta
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

    $pythonInfo = Get-PythonCommand
    if (-not $pythonInfo) {
        Write-Host ""
        Write-Status "Python instalado mas nao encontrado no PATH." "ERRO"
        Write-Status "Feche este terminal, abra um novo e execute novamente." "ERRO"
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
    Write-Status "Python $pyVersionStr encontrado, mas e necessario 3.10+." "ERRO"
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
        Write-Status "Falha ao instalar pip." "ERRO"
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Status "pip instalado." "OK"
}
else {
    $pipVersionInfo = if ($pipVersionRaw -match "pip (\S+)") { $Matches[1] } else { "?" }
    Write-Status "pip $pipVersionInfo disponivel." "OK"
}

# --- 3. Instalar dependências ---
Write-Status "Verificando dependencias Python..."

$requirements = Get-Content $RequirementsFile | Where-Object { $_ -match '\S' }
$todasInstaladas = $true

foreach ($pacote in $requirements) {
    $checkResult = & $pythonCmd -m pip show $pacote 2>&1
    if ($LASTEXITCODE -ne 0) {
        $todasInstaladas = $false
    }
}

if (-not $todasInstaladas) {
    Write-Status "Instalando dependencias..."
    & $pythonCmd -m pip install -r $RequirementsFile --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Erro ao instalar dependencias." "ERRO"
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Status "Dependencias instaladas." "OK"
}
else {
    Write-Status "Todas as dependencias ja instaladas." "OK"
}

# --- 4. Limpar cache Python (garante código atualizado) ---
$cacheDir = Join-Path $BackendDir "__pycache__"
if (Test-Path $cacheDir) {
    Remove-Item $cacheDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Status "Cache Python limpo (__pycache__ removido)." "OK"
}

# --- 5. Verificar porta 8000 ---
Write-Status "Verificando porta 8000..."

$portaEmUso = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($portaEmUso) {
    $processoId = ($portaEmUso | Select-Object -First 1).OwningProcess
    $processo = Get-Process -Id $processoId -ErrorAction SilentlyContinue
    Write-Status "Porta 8000 em uso por '$($processo.ProcessName)' (PID: $processoId). Encerrando..." "AVISO"
    Stop-Process -Id $processoId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Write-Status "Processo encerrado." "OK"
}
else {
    Write-Status "Porta 8000 livre." "OK"
}

# --- 6. Iniciar aplicação ---
Write-Host ""
Write-Host "=================================================" -ForegroundColor Green
Write-Host "   ConcurseiroOS iniciando...                     " -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL: $AppUrl" -ForegroundColor Cyan
Write-Host "  Modo: Hot-reload (detecta alteracoes no codigo)" -ForegroundColor Cyan
Write-Host "  Parar: Ctrl+C" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Funcionalidades:" -ForegroundColor White
Write-Host "    - Leitor PDF com progresso" -ForegroundColor Gray
Write-Host "    - Edital verticalizado (tree hierarquico)" -ForegroundColor Gray
Write-Host "    - Flashcards SRS (repeticao espacada)" -ForegroundColor Gray
Write-Host "    - Banco de questoes + simulados" -ForegroundColor Gray
Write-Host "    - Dashboard com graficos" -ForegroundColor Gray
Write-Host "    - Ciclo de estudos + cronometro" -ForegroundColor Gray
Write-Host "    - Streaks, metas, countdown para provas" -ForegroundColor Gray
Write-Host "    - Tema claro/escuro (WCAG acessivel)" -ForegroundColor Gray
Write-Host ""

# Abrir navegador após delay
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process $using:AppUrl
} | Out-Null

# Iniciar servidor com --reload
Set-Location $BackendDir
& $pythonCmd -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
