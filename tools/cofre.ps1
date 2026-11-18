# COFRE - funciones de PowerShell (paso 7.4).
# Cargalas desde tu perfil:  . "C:\Users\Sammi\AI\cofre\tools\cofre.ps1"
# No guardan valores: solo llaman a run.cmd.

$CofreRepo = Split-Path -Parent $PSScriptRoot

function cofre {
    & "$CofreRepo\run.cmd" @args
}

function cofre-run {
    # cofre-run -- npm start   (busca .cofre-env.json hacia arriba)
    & "$CofreRepo\run.cmd" run -- @args
}

function cofre-copy {
    # cofre-copy NOMBRE  -> portapapeles, sin imprimir el valor
    param([Parameter(Mandatory = $true)][string]$Nombre)
    & "$CofreRepo\run.cmd" get $Nombre --allow-pipe | Set-Clipboard
}
