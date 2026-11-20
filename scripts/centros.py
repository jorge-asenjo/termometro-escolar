"""Calor en horas de clase para cada centro público en alta de la Comunidad de Madrid.

1. Temperatura horaria validada de las 28 estaciones de la Red de Calidad del Aire, solo días lectivos
   y horas de 9 a 14 h oficiales (cursos 2021/22 a 2025/26).
2. Interpolación a cada centro: inverso de la distancia al cuadrado, con corrección por altitud
   (-0,65 °C cada 100 m). Validada en interpolacion.py: RMSE 1,5 °C dejando fuera cada estación.
3. Por centro: días con >= 27 °C, grados-hora por encima de 25 °C, tramo (quintil) y confianza.
4. Alumnos estimados: matrícula en centros públicos del municipio (o distrito, en Madrid capital)
   y etapa, curso 2024/25, repartida a partes iguales entre los centros públicos que imparten esa etapa.

La altitud de cada centro se consulta una vez a la API de elevación de Open-Meteo (Copernicus DEM 90 m)
y se guarda en resultados/altitud_centros.csv.

Uso: python -I scripts/centros.py datos/meteo datos/estaciones/calidad_aire_estaciones.csv \
        datos/centros/centros_educativos.csv \
        datos/alumnos/alumnos_regimen_general_por_titularidad_y_financiacion.csv"""
import sys, glob, os, json, re, time, urllib.request, warnings
import numpy as np, pandas as pd
from pyproj import Transformer
warnings.simplefilter('ignore')
sys.stdout.reconfigure(encoding='utf-8')
dm, fe, fc, fa = sys.argv[1:5]
RES, WEB = 'resultados', 'docs'
os.makedirs(RES, exist_ok=True); os.makedirs(WEB, exist_ok=True)
num = lambda s: pd.to_numeric(s.astype(str).str.replace(',', '.'), errors='coerce')
LAPSE = -0.0065
CURSOS = [2021, 2022, 2023, 2024, 2025]

# ---------- temperatura horaria lectiva por estación
H = [f'h{i:02d}' for i in range(1, 25)]; V = [f'v{i:02d}' for i in range(1, 25)]
dfs = []
for f in sorted(glob.glob(os.path.join(dm, '20*.csv'))):
    x = pd.read_csv(f, sep=';', dtype=str, encoding='utf-8-sig')
    x = x[x['magnitud'] == '83'].copy()
    for h, v in zip(H, V):
        x[h] = num(x[h]).where(x[v] == 'V')
    dfs.append(x[['punto_muestreo', 'ano', 'mes', 'dia'] + H])
df = pd.concat(dfs, ignore_index=True)
df['cod'] = df['punto_muestreo'].str[:8]
df['fecha'] = pd.to_datetime(df['ano'] + '-' + df['mes'] + '-' + df['dia'], errors='coerce')
df = df.dropna(subset=['fecha'])


def ultdom(y, m):
    t = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return t - pd.Timedelta(days=(t.dayofweek + 1) % 7)


NOL25 = [('2025-12-20', '2026-01-07'), ('2026-03-27', '2026-04-06')]
SUE25 = [pd.Timestamp(s) for s in ['2025-10-13', '2025-11-03', '2025-12-08', '2026-05-01']]


def curso_de(fe):
    return fe.year if fe.month >= 9 else fe.year - 1


def lectivo(fe):
    c = curso_de(fe)
    if fe.day_of_week >= 5 or not (pd.Timestamp(c, 9, 8) <= fe <= pd.Timestamp(c + 1, 6, 19)):
        return False
    if c == 2025:
        return not (any(pd.Timestamp(a) <= fe <= pd.Timestamp(b) for a, b in NOL25) or fe in SUE25)
    return not (pd.Timestamp(c, 12, 22) <= fe <= pd.Timestamp(c + 1, 1, 7))


fechas = pd.Series(sorted(df['fecha'].unique()))
fechas = fechas[fechas.map(lambda f: lectivo(f) and curso_de(f) in CURSOS)]
df = df[df['fecha'].isin(set(fechas))]
# las columnas hNN cubren la hora UTC [NN-1, NN): 9-14 h oficiales = h08..h12 en verano, h09..h13 en invierno
ver = (df['fecha'] >= df['fecha'].dt.year.map(lambda a: ultdom(a, 3))) & (df['fecha'] < df['fecha'].dt.year.map(lambda a: ultdom(a, 10)))
A = df[['h08', 'h09', 'h10', 'h11', 'h12']].to_numpy(float)
B = df[['h09', 'h10', 'h11', 'h12', 'h13']].to_numpy(float)
L = np.where(ver.to_numpy()[:, None], A, B)
long = pd.DataFrame({'cod': np.repeat(df['cod'].values, 5), 'fecha': np.repeat(df['fecha'].values, 5),
                     'slot': np.tile(np.arange(5), len(df)), 't': L.ravel()})
P = long.pivot_table(index=['fecha', 'slot'], columns='cod', values='t', aggfunc='mean')
P = P.reindex(pd.MultiIndex.from_product([fechas.values, range(5)], names=['fecha', 'slot']))

e = pd.read_csv(fe, sep=';', dtype=str, encoding='utf-8-sig').set_index('estacion_codigo')
st = pd.DataFrame({'x': num(e['estacion_coord_UTM_ETRS89_x']), 'y': num(e['estacion_coord_UTM_ETRS89_y']),
                   'z_oficial': num(e['estacion_altitud']), 'muni': e['estacion_municipio']}).loc[P.columns]
print('Estaciones:', len(st), '· días lectivos:', len(fechas), '· horas:', len(P))
# Posible cambio de sensor o de emplazamiento (robustez.py): se calientan 1,5-2 °C frente al resto de la red.
# Esos periodos se quitan y la interpolación los cubre con las estaciones vecinas.
SOSPECHA = {'28092005': '2025-04-01', '28074007': '2026-01-01'}
fi = P.index.get_level_values('fecha')
for cod, desde in SOSPECHA.items():
    P.loc[fi >= pd.Timestamp(desde), cod] = np.nan
TR = Transformer.from_crs('EPSG:25830', 'EPSG:4326', always_xy=True)


def elevacion(df, cache):
    """Altitud del terreno (Copernicus DEM 90 m, vía Open-Meteo) para cada fila con lat/lon; con caché."""
    z = pd.read_csv(cache, dtype={'CODIGO': str}) if os.path.exists(cache) else pd.DataFrame(columns=['CODIGO', 'alt'])
    falta = df[~df['CODIGO'].isin(z['CODIGO'])]
    for i in range(0, len(falta), 50):
        b = falta.iloc[i:i + 50]
        url = ('https://api.open-meteo.com/v1/elevation?latitude=' + ','.join(map(str, b['lat'])) +
               '&longitude=' + ','.join(map(str, b['lon'])))
        for intento in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'termometro-escolar'}), timeout=60) as r:
                    el = json.load(r)['elevation']
                break
            except OSError:
                time.sleep(2 ** intento)
        else:
            sys.exit('No responde la API de elevación; vuelve a lanzar el script (guarda lo ya bajado).')
        z = pd.concat([z, pd.DataFrame({'CODIGO': b['CODIGO'].values, 'alt': el})], ignore_index=True)
        z.to_csv(cache, index=False)
        time.sleep(0.5)
    return df.merge(z, on='CODIGO', how='left')['alt'].to_numpy(float)


lo, la = TR.transform(st['x'].values, st['y'].values)
st['z'] = elevacion(pd.DataFrame({'CODIGO': st.index, 'lat': np.round(la, 5), 'lon': np.round(lo, 5)}),
                    os.path.join(RES, 'altitud_estaciones.csv'))
mal = st[(st['z'] - st['z_oficial']).abs() > 100]
for cod, r in mal.iterrows():
    print(f'Altitud oficial de {r["muni"]} ({cod}): {r["z_oficial"]:.0f} m; terreno: {r["z"]:.0f} m. Se usa la del terreno.')

# ---------- centros públicos en alta
c = pd.read_csv(fc, sep=';', dtype=str, encoding='utf-8-sig')
c = c[(c['SITUACIÓN'] == 'ALTA') & c['TITULARIDAD'].str.startswith('PÚB', na=False)].copy()
c['X'] = num(c['UTM_X']); c['Y'] = num(c['UTM_Y'])
sin = (~c['X'].between(350000, 520000)) | (~c['Y'].between(4380000, 4580000))
print('Centros públicos en alta:', len(c), '· sin coordenadas válidas:', int(sin.sum()))
c = c[~sin].reset_index(drop=True)
lon, lat = TR.transform(c['X'].values, c['Y'].values)
c['lat'], c['lon'] = np.round(lat, 5), np.round(lon, 5)
c['alt'] = elevacion(c, os.path.join(RES, 'altitud_centros.csv'))
print('Altitud de los centros: min', c['alt'].min(), '· máx', c['alt'].max())

# ---------- interpolación IDW con corrección por altitud
T = P.to_numpy(float)
M = ~np.isnan(T)
SX, SY, SZ = st['x'].to_numpy(), st['y'].to_numpy(), st['z'].to_numpy()
Tn = T - LAPSE * SZ[None, :]                            # temperatura llevada a nivel del mar


def idw(x, y, z, cols=None):
    """Temperatura horaria en los puntos (x, y, z) a partir de las estaciones `cols` (todas por defecto)."""
    k = np.arange(len(SX)) if cols is None else np.asarray(cols)
    d = np.hypot(x[:, None] - SX[None, k], y[:, None] - SY[None, k])
    w = 1 / np.maximum(d, 50.0) ** 2
    return (np.nan_to_num(Tn[:, k]) @ w.T) / (M[:, k] @ w.T) + LAPSE * z[None, :]


# validación: se quita cada estación y se predice con las demás
err = []
for j in range(len(SX)):
    otras = [k for k in range(len(SX)) if k != j]
    pr = idw(SX[[j]], SY[[j]], SZ[[j]], otras)[:, 0]
    ok = M[:, j]
    err.append(pd.DataFrame({'cod': st.index[j], 'e': pr[ok] - T[ok, j]}))
E = pd.concat(err)
por = E.groupby('cod')['e'].apply(lambda s: np.sqrt((s ** 2).mean()))
print(f'\nValidación dejando fuera cada estación (horas lectivas 2021/22-2025/26): RMSE {np.sqrt((E.e ** 2).mean()):.2f} °C · '
      f'mediana por estación {por.median():.2f} °C · sesgo {E.e.mean():+.2f} °C')
print('Estaciones con más error (°C):', por.sort_values(ascending=False).head(5).round(2).rename(st['muni']).to_dict())

D = np.hypot(c['X'].to_numpy()[:, None] - SX[None, :], c['Y'].to_numpy()[:, None] - SY[None, :])
Tc = idw(c['X'].to_numpy(), c['Y'].to_numpy(), c['alt'].to_numpy(float))   # horas x centros
c['dkm'] = (D.min(axis=1) / 1000).round(1)
c['est_cercana'] = st['muni'].to_numpy()[D.argmin(axis=1)]

# ---------- métricas por centro
nd = len(fechas)
Td = Tc.reshape(nd, 5, -1)                              # día x hora x centro
tmax = Td.max(axis=1)                                   # día x centro
gh = np.clip(Td - 25, 0, None).sum(axis=1)              # grados-hora > 25 °C por día
cur = fechas.map(curso_de).to_numpy()
for k in CURSOS:
    s = cur == k
    c[f'd27_{k}'] = (tmax[s] >= 27).sum(axis=0)
    c[f'gh25_{k}'] = gh[s].sum(axis=0).round(0)
    c[f'h27_{k}'] = (Td[s] >= 27).sum(axis=(0, 1))
c['d27_media'] = c[[f'd27_{k}' for k in CURSOS]].mean(axis=1).round(1)
c['h27_media'] = c[[f'h27_{k}' for k in CURSOS]].mean(axis=1).round(1)
c['gh25_media'] = c[[f'gh25_{k}' for k in CURSOS]].mean(axis=1).round(0)
c['percentil'] = (c['gh25_media'].rank(pct=True) * 100).round(0).astype(int)
c['tramo'] = pd.qcut(c['gh25_media'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
c['confianza'] = np.where((c['MUNICIPIO'] == 'Madrid') | (c['dkm'] > 10), 'baja',
                          np.where(c['dkm'] > 5, 'media', 'alta'))

# ---------- alumnos estimados (curso 2024/25, centros públicos)
ETAPAS = {
    'E. Infantil Primer Ciclo': ['EEI', 'EEI-CN'],
    'E. Infantil Segundo Ciclo': ['CP INF-PRI', 'CP INF-PRI-SEC', 'CIMELPR PRSEC'],
    'E. Primaria': ['CP INF-PRI', 'CP INF-PRI-SEC', 'CP PRI', 'CIMELPR PRSEC', 'CIMPR SEC'],
    'E.S.O.': ['IES', 'CP INF-PRI-SEC', 'CIMELPR PRSEC', 'CIMPR SEC'],
    'Bachillerato': ['IES'],
    'C.F. Grado Básico': ['IES', 'CP IFP'],
    'C.F. Grado Medio': ['IES', 'CP IFP'],
    'C.F. Grado Superior': ['IES', 'CP IFP'],
    'Educación Especial': ['CP EE'],
}
al = pd.read_csv(fa, sep=';', dtype=str, encoding='utf-8-sig')
al = al[(al['CURSO_ACADEMICO'] == '2024/2025') & al['TCENTRO'].str.contains('blicos') & al['ENSENANZA'].isin(ETAPAS)]
al['zona'] = np.where(al['DISTRITO_MUNICIPAL'].str.startswith('28079'),
                      '28079-' + al['DISTRITO_MUNICIPAL'].str[5:7], al['ACOD_MUNICIPIO'])
al = al.groupby(['zona', 'ENSENANZA'])['DATO'].apply(lambda s: num(s).sum()).reset_index()
c['zona'] = np.where(c['MUNICIPIO'] == 'Madrid', '28079-' + c['CDDISTRITO'].fillna('').str.zfill(2),
                     '28' + c['CDMUNI'].fillna('').str.zfill(3))
c['alumnos'] = 0.0
for _, r in al.iterrows():
    m = (c['zona'] == r['zona']) & c['TIPO_ABRV'].isin(ETAPAS[r['ENSENANZA']])
    if m.any():
        c.loc[m, 'alumnos'] += r['DATO'] / m.sum()
c['alumnos'] = c['alumnos'].round(0).astype(int)
asignados = c['alumnos'].sum(); total = al['DATO'].sum()
print(f'Alumnos de centros públicos 2024/25 en esas etapas: {total:,.0f} · asignados a centros: {asignados:,.0f}')

# ---------- salidas
TIPO = {'CP INF-PRI': 'Colegio de infantil y primaria', 'CP INF-PRI-SEC': 'Colegio de infantil, primaria y secundaria',
        'CP PRI': 'Colegio de primaria', 'IES': 'Instituto', 'EEI': 'Escuela infantil', 'EEI-CN': 'Casa de niños',
        'CP EE': 'Colegio de educación especial', 'CIMELPR PRSEC': 'Colegio de infantil, primaria y secundaria',
        'CIMPR SEC': 'Colegio de primaria y secundaria', 'CEPA': 'Centro de educación de personas adultas',
        'EOI': 'Escuela oficial de idiomas', 'CP IFP': 'Centro de formación profesional'}
GRUPO = {'CP INF-PRI': 'cole', 'CP INF-PRI-SEC': 'cole', 'CP PRI': 'cole', 'CIMELPR PRSEC': 'cole', 'CIMPR SEC': 'cole',
         'CP EE': 'cole', 'IES': 'ies', 'CP IFP': 'ies', 'EEI': 'infantil', 'EEI-CN': 'infantil'}
c['tipo'] = c['TIPO_ABRV'].map(TIPO).fillna(c['TIPO_EXT'].str.capitalize())
c['grupo'] = c['TIPO_ABRV'].map(GRUPO).fillna('otro')
PEQ = {'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'en', 'a', 'al'}


def nombre(s):
    out = []
    for i, w in enumerate(str(s).lower().split()):
        if re.fullmatch(r'[ivxl]+', w) and len(w) <= 4:
            out.append(w.upper())
        elif i and w in PEQ:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return re.sub(r'-(\w)', lambda m: '-' + m.group(1).upper(), ' '.join(out)).replace('"', '')


def muni(s):
    m = re.fullmatch(r'(.+), (El|La|Los|Las)', str(s))
    return f'{m.group(2)} {m.group(1)}' if m else str(s)


c['nombre'] = c['CENTRO'].map(nombre)
c['municipio'] = c['MUNICIPIO'].map(muni)
c['fundado'] = pd.to_datetime(c['FECHA CONSTITUCIÓN'].str[:10], errors='coerce').dt.year
cols = (['CODIGO', 'nombre', 'tipo', 'TIPO_ABRV', 'grupo', 'municipio', 'DISTRITO', 'lat', 'lon', 'alt', 'dkm', 'est_cercana',
         'confianza', 'fundado', 'alumnos', 'd27_media', 'h27_media', 'gh25_media', 'percentil', 'tramo']
        + [f'd27_{k}' for k in CURSOS] + [f'h27_{k}' for k in CURSOS])
c[cols].sort_values('gh25_media', ascending=False).to_csv(os.path.join(RES, 'centros.csv'), index=False, encoding='utf-8')

# web: días calurosos del curso 2025/26, día a día, para la animación
s25 = cur == 2025
dias25 = [f.strftime('%Y-%m-%d') for f in fechas[s25]]
hot = (tmax[s25] >= 27)                                  # días x centros


def bits(col):
    by = np.packbits(col.astype(np.uint8))
    return ''.join(f'{b:02x}' for b in by)


reg = {'d27_media_mediana': float(c['d27_media'].median()), 'n': int(len(c))}
web = {'dias': dias25, 'region': reg, 'cursos': CURSOS,
       'campos': ['id', 'nombre', 'tipo', 'grupo', 'municipio', 'distrito', 'lat', 'lon', 'alt', 'dkm', 'estacion',
                  'confianza', 'fundado', 'alumnos', 'd27', 'h27', 'gh25', 'percentil', 'tramo', 'serie', 'calor2526'],
       'centros': []}
for i, r in c.iterrows():
    web['centros'].append([r['CODIGO'], r['nombre'], r['tipo'], r['grupo'], r['municipio'],
                           r['DISTRITO'] if r['MUNICIPIO'] == 'Madrid' and isinstance(r['DISTRITO'], str) else '',
                           float(r['lat']), float(r['lon']), int(r['alt']), float(r['dkm']), r['est_cercana'],
                           r['confianza'], int(r['fundado']) if pd.notna(r['fundado']) else None, int(r['alumnos']),
                           float(r['d27_media']), float(r['h27_media']), int(r['gh25_media']), int(r['percentil']),
                           int(r['tramo']), [int(r[f'd27_{k}']) for k in CURSOS], bits(hot[:, i])])
with open(os.path.join(WEB, 'centros.json'), 'w', encoding='utf-8') as f:
    json.dump(web, f, ensure_ascii=False, separators=(',', ':'))

print('\nDías lectivos con >= 27 °C (media 2021/22-2025/26) por tramo:')
print(c.groupby('tramo')['d27_media'].describe()[['count', 'min', '50%', 'max']].round(1).to_string())
print('\nPor confianza:', c['confianza'].value_counts().to_dict())
print('\nLos 10 centros con más calor en horario de clase (grados-hora > 25 °C, media de 5 cursos):')
print(c.sort_values('gh25_media', ascending=False)[['nombre', 'tipo', 'municipio', 'd27_media', 'gh25_media', 'confianza']].head(10).to_string(index=False))
print('\nLos 5 con menos:')
print(c.sort_values('gh25_media')[['nombre', 'tipo', 'municipio', 'd27_media', 'gh25_media']].head(5).to_string(index=False))
print('\nAlumnos estimados en centros del tramo 5:', int(c.loc[c.tramo == 5, 'alumnos'].sum()))
