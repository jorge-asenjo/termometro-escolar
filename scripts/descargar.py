"""Descarga del Portal de Datos Abiertos de la Comunidad de Madrid los conjuntos que usa el proyecto.
Pregunta las URL a la API del portal (CKAN), así que sirve también cuando se publique un año nuevo.
Uso: python -I scripts/descargar.py [carpeta_destino]   (por defecto: datos/)"""
import json, os, sys, urllib.request

API = 'https://datos.comunidad.madrid/api/3/action/package_show?id='
CONJUNTOS = {
    # id del conjunto: (subcarpeta, qué recursos bajar)
    'calidad_aire_datos_meteo_historico': ('meteo', lambda r: r['format'].upper() == 'CSV'),
    'calidad_aire_estaciones': ('estaciones', lambda r: r['format'].upper() == 'CSV'),
    'centros_educativos': ('centros', lambda r: r['format'].upper() == 'CSV'),
    'spacm_estadisticas_alumnos': ('alumnos', lambda r: r['url'].endswith(
        '/alumnos_regimen_general_por_titularidad_y_financiacion.csv')),
}
destino = sys.argv[1] if len(sys.argv) > 1 else 'datos'


def bajar(url, ruta):
    req = urllib.request.Request(url, headers={'User-Agent': 'termometro-escolar'})
    with urllib.request.urlopen(req, timeout=300) as r, open(ruta, 'wb') as f:
        while bloque := r.read(1 << 20):
            f.write(bloque)


for conjunto, (sub, quiero) in CONJUNTOS.items():
    with urllib.request.urlopen(API + conjunto, timeout=60) as r:
        recursos = json.load(r)['result']['resources']
    os.makedirs(os.path.join(destino, sub), exist_ok=True)
    for rec in filter(quiero, recursos):
        nombre = rec['url'].rsplit('/', 1)[-1]
        ruta = os.path.join(destino, sub, nombre)
        if os.path.exists(ruta) and os.path.getsize(ruta) > 0:
            print('ya está', ruta)
            continue
        print('bajando', ruta)
        bajar(rec['url'], ruta)
print('Listo. Siguiente paso: python -I scripts/calor_lectivo.py datos/meteo datos/estaciones/calidad_aire_estaciones.csv resultados/calor_lectivo.csv')
