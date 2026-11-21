# COFRE - funciones de PowerShell (paso 7.4).
# Configuracion recomendada, UNA sola vez (M10):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# Permite tus scripts locales y sigue exigiendo firma a los descargados.
# Cargalas desde tu perfil:  . "C:\ruta\a\cofre\tools\cofre.ps1"
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
