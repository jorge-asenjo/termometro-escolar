"""Días y horas lectivas de calor por estación de la Red de Calidad del Aire, por curso (2020/21-2025/26).
Fuente: calidad_aire_datos_meteo_historico (magnitud 83, temperatura, solo datos 'V').
Decisiones de método:
  1) Hora: las columnas hNN cubren la hora UTC [NN-1, NN) (comprobado con el pico de radiación, hora.py),
     así que 9-14 h oficiales = UTC 7-12 en horario de verano (h08..h12) y UTC 8-13 en invierno (h09..h13).
  2) Calendario 2025/26: clases del 8-sep-2025 al 19-jun-2026; Navidad 20-dic a 7-ene;
     Semana Santa 27-mar a 6-abr; no lectivos 13-oct, 3-nov, 8-dic y 1-may (prensa sobre la orden).
     Otros cursos: ventana 8-sep..19-jun, sin Navidad.
  3) Cobertura: >=4 de 5 horas válidas en el día y >=90 % de días lectivos con dato por estación-curso.
Uso: python -I scripts/calor_lectivo.py <carpeta_meteo> <estaciones.csv> <salida_csv>"""
import sys, glob, os
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
d, estf, outf = sys.argv[1:4]
H = [f'h{i:02d}' for i in range(1, 25)]
V = [f'v{i:02d}' for i in range(1, 25)]
dfs = []
for f in sorted(glob.glob(os.path.join(d, '20*.csv'))):
    x = pd.read_csv(f, sep=';', dtype=str, encoding='utf-8-sig')
    x = x[x['magnitud'] == '83'].copy()
    for h, v in zip(H, V):
        x[h] = pd.to_numeric(x[h].str.replace(',', '.'), errors='coerce').where(x[v] == 'V')
    dfs.append(x[['punto_muestreo', 'ano', 'mes', 'dia'] + H])
df = pd.concat(dfs, ignore_index=True)
df['cod'] = df['punto_muestreo'].str[:8]
df['fecha'] = pd.to_datetime(df['ano'] + '-' + df['mes'] + '-' + df['dia'], errors='coerce')
df = df.dropna(subset=['fecha']).reset_index(drop=True)
dup = df.duplicated(['cod', 'fecha']).sum()
print('Filas de temperatura:', len(df), '· duplicadas estación-fecha:', dup)


def ultdom(y, m):
    t = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return t - pd.Timedelta(days=(t.day_of_week + 1) % 7)


yrs = df['fecha'].dt.year
ini = yrs.map(lambda a: ultdom(a, 3))
fin = yrs.map(lambda a: ultdom(a, 10))
verano = ((df['fecha'] >= ini) & (df['fecha'] < fin)).to_numpy()
A = df[['h08', 'h09', 'h10', 'h11', 'h12']].to_numpy(float)
B = df[['h09', 'h10', 'h11', 'h12', 'h13']].to_numpy(float)
L = np.where(verano[:, None], A, B)                       # 5 horas lectivas, 9-14 h oficiales
nval = (~np.isnan(L)).sum(axis=1)
with np.errstate(all='ignore'):
    import warnings; warnings.simplefilter('ignore')
    tl = np.nanmax(L, 1)
df['tmax_lect'] = np.where(nval >= 4, tl, np.nan)
df['h27'] = np.where(nval >= 4, (L >= 27).sum(axis=1), np.nan)
df['h30'] = np.where(nval >= 4, (L >= 30).sum(axis=1), np.nan)
f = df['fecha']; m = f.dt.month
df['curso'] = np.where(m >= 9, f.dt.year, f.dt.year - 1)
NOL25 = [('2025-12-20', '2026-01-07'), ('2026-03-27', '2026-04-06')]
SUE25 = [pd.Timestamp(s) for s in ['2025-10-13', '2025-11-03', '2025-12-08', '2026-05-01']]


def lectivo(fe):
    c = fe.year if fe.month >= 9 else fe.year - 1
    if fe.day_of_week >= 5:
        return False
    if not (pd.Timestamp(c, 9, 8) <= fe <= pd.Timestamp(c + 1, 6, 19)):
        return False
    if c == 2025:
        if any(pd.Timestamp(a) <= fe <= pd.Timestamp(b) for a, b in NOL25) or fe in SUE25:
            return False
    elif pd.Timestamp(c, 12, 22) <= fe <= pd.Timestamp(c + 1, 1, 7):
        return False
    return True


fu = pd.Series(f.unique())
mp = dict(zip(fu, fu.map(lectivo)))
df['lect'] = f.map(mp).astype(bool)
e = pd.read_csv(estf, sep=';', dtype=str, encoding='utf-8-sig')
e = e[['estacion_codigo', 'estacion_municipio', 'estacion_altitud']].rename(
    columns={'estacion_codigo': 'cod', 'estacion_municipio': 'muni', 'estacion_altitud': 'alt'})
D = df[df['lect']].copy()
nlect = D.groupby('curso')['fecha'].nunique()
print('Días lectivos en la ventana por curso:', nlect.to_dict())
g = D.groupby(['cod', 'curso']).agg(
    dias_ok=('tmax_lect', 'count'), d27=('tmax_lect', lambda s: int((s >= 27).sum())),
    d30=('tmax_lect', lambda s: int((s >= 30).sum())), h27=('h27', 'sum'), h30=('h30', 'sum')).reset_index()
g['cobertura'] = (g['dias_ok'] / g['curso'].map(nlect)).round(3)
g = g.merge(e, on='cod', how='left')
g.to_csv(outf, index=False, encoding='utf-8')
pd.set_option('display.width', 250)
c = g[g.curso == 2025].sort_values('d27', ascending=False)
print('\nCurso 2025/26 (8-sep-2025 a 19-jun-2026), T exterior en 9-14 h oficiales:')
print(c[['cod', 'muni', 'alt', 'cobertura', 'd27', 'd30', 'h27']].to_string(index=False))
ok = c[(c.cobertura >= 0.9) & (c.cod != '28120001')]
print(f'\nEstaciones válidas (cobertura >= 90 %, sin Puerto de Cotos a 1.870 m): {len(ok)}')
for k in ['d27', 'd30', 'h27']:
    print(f'{k}: min {ok[k].min()} · mediana {ok[k].median()} · máx {ok[k].max()}')
print('\nSerie por curso (estaciones con cobertura >= 90 %, sin Cotos):')
G = g[(g.cobertura >= 0.9) & (g.cod != '28120001') & (g.curso.between(2020, 2025))]
print(G.groupby('curso').agg(n=('cod', 'count'), d27_med=('d27', 'median'), d27_min=('d27', 'min'),
                             d27_max=('d27', 'max'), d30_med=('d30', 'median'), h27_med=('h27', 'median')).to_string())
# Comprobación de sensor: sesgo frente a la mediana diaria de la red
D['med_red'] = D.groupby('fecha')['tmax_lect'].transform('median')
D['dif'] = D['tmax_lect'] - D['med_red']
S = D[D.curso.between(2020, 2025)].pivot_table(index='cod', columns='curso', values='dif', aggfunc='mean').round(2)
S = S.join(e.set_index('cod')['muni'])
print('\nSesgo medio (°C) frente a la mediana de la red el mismo día (un salto entre cursos indicaría cambio de sensor o de sitio):')
print(S.to_string())
D['mes'] = D['fecha'].dt.month
M = (D[D.cod != '28120001'].groupby(['curso', 'mes', 'cod'])['tmax_lect']
     .apply(lambda s: (s >= 27).sum()).groupby(['curso', 'mes']).median().unstack(0))
print('\nDías >= 27 °C por mes (mediana de estaciones):')
print(M.reindex([5, 6, 9, 10]).to_string())
