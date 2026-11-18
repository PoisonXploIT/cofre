"""COFRE - catalogo de mensajes (paso 6.3).

La paleta y los textos cortos del primer uso ya toman sus cadenas de aqui.
`msg()` admite datos con `{nombre}`.

Las claves de llaves y ajustes estan preparadas; sus cadenas, las frases largas
del asistente y las cadenas antiguas de la GUI y del CLI se migran en la pasada
de textos, para no mezclar un cambio de texto con cambios de logica.
"""

from __future__ import annotations

MSG = {
    # comunes
    "comun.siguiente": "Siguiente",
    "comun.atras": "Atrás",
    "comun.cerrar": "Cerrar",
    "comun.copiar": "Copiar",
    "comun.guardar": "Guardar",
    "comun.no_coincide": "no coincide; revisa las palabras y vuelve a probar",
    "comun.abre_cofre": "abre el cofre para {accion}",

    # paleta
    "paleta.titulo": "COFRE - comandos",
    "paleta.campo": "Buscar secretos y acciones",
    "paleta.pie": "Enter ejecuta  ·  flechas mueven  ·  Esc cierra",
    "paleta.sin_resultados": "sin resultados",
    "paleta.bloquear": "Bloquear el cofre",
    "paleta.salud": "Comprobar salud de las credenciales",
    "paleta.nuevo": "Nuevo secreto",
    "paleta.ajustes": "Ajustes",
    "paleta.llaves": "Llaves y recuperación",
    "paleta.registro": "Registro de accesos",
    "paleta.guia": "Guía de uso",
    "paleta.atajos": "Atajos de teclado",
    "paleta.buscar": "Buscar en la lista",
    "paleta.abrir": "Abrir {nombre}",
    "paleta.copiar": "Copiar {nombre}",
    "paleta.rotar": "Rotar {nombre}",
    "paleta.error": "no se pudo ejecutar: {error}",

    # primer uso
    "primer_uso.titulo": "COFRE - primera vez",
    "primer_uso.bienvenida": "COFRE: tu bóveda local",
    "primer_uso.empezar": "Empezar",
    "primer_uso.pendrive": "1. Elige el pendrive principal",
    "primer_uso.sin_unidades": "No hay ninguna unidad conectada. Enchufa el "
                              "pendrive y vuelve a abrir este asistente.",
    "primer_uso.crear": "Crear llave y cofre",
    "primer_uso.código": "2. El código de recuperación",
    "primer_uso.imprimir": "Imprimir",
    "primer_uso.apuntado": "Ya lo he apuntado",
    "primer_uso.confirmar": "3. Confirma que lo tienes",
    "primer_uso.palabra": "palabra {número}",
    "primer_uso.confirmar_boton": "Confirmar",
    "primer_uso.reserva": "4. Pendrive de reserva (recomendado)",
    "primer_uso.sin_reserva": "No hay otra unidad conectada; puedes saltar "
                              "este paso y añadirla después en Llaves.",
    "primer_uso.anadir_reserva": "Añadir reserva",
    "primer_uso.saltar": "Saltar",
    "primer_uso.extension": "5. La extensión del navegador (opcional)",
    "primer_uso.abrir_guia": "Abrir la guía",
    "primer_uso.terminar": "Terminar",
    "primer_uso.error_crear": "no se pudo crear: {error}",
    "primer_uso.error_reserva": "no se pudo añadir la reserva: {error}",
    "primer_uso.error_abrir": "el cofre está creado, pero no se pudo abrir: {error}",
    "primer_uso.error_imprimir": "no se pudo imprimir: {error}",
    "primer_uso.impreso": "código enviado a imprimir; el temporal se borra en un minuto",

    # llaves
    "llaves.titulo": "Llaves y recuperación",
    "llaves.cabecera": "Llaves del cofre",
    "llaves.intro": "Todo lo que abre este cofre. El código de recuperación "
                    "vive en papel; no se puede leer aquí.",
    "llaves.anadir": "Añadir pendrive",
    "llaves.nuevo_codigo": "Nuevo código",
    "llaves.probar": "Probar código",
    "llaves.recovery": "Código de recuperación en papel",
    "llaves.recovery_nota": "25 palabras · no se puede leer desde aquí",
    "llaves.actual": "Es la llave abierta",
    "llaves.actual_aviso": "para darla de baja, abre el cofre con el otro pendrive",
    "llaves.baja": "Dar de baja",
    "llaves.sin_registrar": "SIN REGISTRAR",
    "llaves.sin_uso": "sin uso registrado",
    "llaves.uso": "último uso: {fecha}",
    "llaves.conectada": "conectada",
    "llaves.no_conectada": "no conectada",
    "llaves.abierta": "abierta ahora",
    "llaves.huerfano": "registro sin ranura",
    "llaves.pie": "Dar de baja un pendrive lo saca del cofre. Si haces rekey, "
                  "cambia la clave maestra: las copias viejas dejan de abrir "
                  "con la nueva y los pendrives no conectados se quedan fuera.",
    "llaves.sin_sesion": "abre el cofre para ver las llaves",
    "llaves.solo_pendrive": "no se puede dar de baja el único pendrive: añade otro antes",
    "llaves.baja_titulo": "Dar de baja un pendrive",
    "llaves.baja_texto": "Ese pendrive dejará de abrir el cofre. Si eliges rekey, "
                         "también cambia la clave maestra: las copias viejas no "
                         "se abrirán con la nueva y los pendrives que no estén "
                         "conectados se quedarán fuera. El rekey cierra el tramo "
                         "del registro y empieza otro.",
    "llaves.solo_baja": "Solo dar de baja",
    "llaves.baja_rekey": "Dar de baja y rekey",
    "llaves.ranura_quitada": "ranura del serial {serial} quitada",
    "llaves.rekey_hecho": "rekey hecho; el pendrive actual sigue abriendo",
    "llaves.rekey_error": "el rekey falló; el cofre sigue como estaba",
    "llaves.rekey_reabrir": "rekey hecho, pero no se pudo reabrir: {error}. "
                            "Bloquea y abre de nuevo",
    "llaves.rekey_codigo": "cambiando la clave maestra...",
    "llaves.rekey_sin_llave": "sin el pendrive actual no se puede hacer rekey desde aquí",
    "llaves.anadir_titulo": "Añadir un pendrive",
    "llaves.anadir_texto": "1. Se escribe COFRE.KEY.nuevo en la unidad elegida. "
                           "El COFRE.KEY que ya tenga ese pendrive no se toca.\n"
                           "2. Se añade una ranura al cofre y se comprueba que la "
                           "llave nueva abre antes de darla por buena.\n"
                           "3. Cuando confirmes, borra o renombra el COFRE.KEY "
                           "viejo y renombra COFRE.KEY.nuevo a COFRE.KEY.",
    "llaves.anadir_crear": "Crear llave nueva",
    "llaves.sin_unidad": "no hay otra unidad conectada",
    "llaves.sin_pendrive": "abre el cofre con un pendrive para poder añadir otro",
    "llaves.codigo_titulo": "Código de recuperación nuevo",
    "llaves.codigo_aviso": "Apunta estas 25 palabras en papel. Se muestran una "
                           "sola vez. El código anterior ya no abre.",
    "llaves.codigo_confirmar": "Se va a reemplazar el código de recuperación. "
                               "El anterior dejará de abrir el cofre. Los "
                               "pendrives no cambian.",
    "llaves.probar_titulo": "Probar el código de recuperación",
    "llaves.probar_texto": "Pega las 25 palabras. No se guarda nada.",
    "llaves.probar_boton": "Probar",
    "llaves.abre": "ABRE: {motivo}",
    "llaves.no_abre": "NO ABRE: {motivo}",

    # ajustes
    "ajustes.titulo": "Ajustes",
    "ajustes.intro": "Todo esto se guarda en cofre-settings.json, junto al "
                     "cofre. No hay secretos ahí.",
    "ajustes.seguridad": "Seguridad",
    "ajustes.generador": "Generador",
    "ajustes.alertas": "Umbrales de alertas",
    "ajustes.navegador": "Navegador",
    "ajustes.copias": "Copias",
    "ajustes.acerca": "Acerca de",
    "ajustes.emergencia": "Emergencia",
    "ajustes.inactividad": "Bloquear por inactividad (min)",
    "ajustes.maximo": "Tiempo máximo de sesión (h)",
    "ajustes.portapapeles": "Vaciar el portapapeles (s; 0 = nunca)",
    "ajustes.revelar": "Ocultar el valor revelado (s)",
    "ajustes.perfil": "Perfil por defecto",
    "ajustes.palabras": "Palabras",
    "ajustes.idioma": "Idioma",
    "ajustes.rafaga": "Lecturas para una ráfaga",
    "ajustes.rafaga_min": "Minutos de la ráfaga",
    "ajustes.desde": "Hora rara: desde",
    "ajustes.hasta": "Hora rara: hasta",
    "ajustes.pausa": "Pausa entre alertas (min)",
    "ajustes.fallos": "Fallos de apertura seguidos",
    "ajustes.rotación": "Horas para rotación colgada",
    "ajustes.puente": "Conectar el puente al abrir el cofre",
    "ajustes.emparejar": "Emparejar de nuevo",
    "ajustes.carpeta": "Elegir",
    "ajustes.copiar": "Copiar el cofre ahora",
    "ajustes.copia_aviso": "La copia es el cofre cifrado. La llave del pendrive "
                           "NO debe ir en la misma carpeta.",
    "ajustes.versión": "COFRE {versión} · formato {formato}",
    "ajustes.guardado": "ajustes guardados",
    "ajustes.numeros": "los tiempos y umbrales tienen que ser números",
    "ajustes.copia_sin_carpeta": "elige primero la carpeta de copias",
    "ajustes.copia_hecha": "copia escrita en {ruta}. La llave NO va en esa carpeta.",
    "ajustes.emparejar_aviso": "Se va a registrar el host de mensajería nativa "
                               "para el navegador. Cierra el navegador si el "
                               "instalador lo pide.",
}


def msg(clave: str, **datos) -> str:
    texto = MSG.get(clave)
    if texto is None:
        return clave
    try:
        return texto.format(**datos)
    except (KeyError, IndexError):
        return texto
