"""Viabilidad de la interpolación a cada centro: (1) centros activos y distancia a estación con temperatura;
(2) validación dejando fuera una estación (LOO) de la interpolación de temperatura horaria
9-14 h en días lectivos del curso 2025/26; (3) error en horas >=27 ºC por estación.
Uso: python -I scripts/interpolacion.py <carpeta_meteo> <estaciones.csv> <centros.csv>"""
import sys, glob, os, pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
dm, fe, fc = sys.argv[1:4]
num = lambda s: pd.to_numeric(s.astype(str).str.replace(',', '.'), errors='coerce')

e = pd.read_csv(fe, sep=';', dtype=str, encoding='utf-8-sig')
e['x'] = num(e['estacion_coord_UTM_ETRS89_x']); e['y'] = num(e['estacion_coord_UTM_ETRS89_y'])
e['z'] = num(e['estacion_altitud'])

# --- temperatura horaria, curso 2025/26
hs = [f'h{i:02d}' for i in range(10, 15)]
rows = []
for f in ['2025.csv', '2026.csv']:
    x = pd.read_csv(os.path.join(dm, f), sep=';', dtype=str)
    x = x[x['magnitud'] == '83']
    rows.append(x)
df = pd.concat(rows)
df['fecha'] = pd.to_datetime(df['ano'] + '-' + df['mes'] + '-' + df['dia'], errors='coerce')
print('Última fecha con temperatura en 2026.csv:', df['fecha'].max().date())
df = df[(df.fecha >= '2025-09-08') & (df.fecha <= '2026-06-19')]
f = df['fecha']
df = df[(f.dt.day_of_week < 5) & ~(((f.dt.month == 12) & (f.dt.day >= 22)) | ((f.dt.month == 1) & (f.dt.day <= 7)))]
df['cod'] = df['punto_muestreo'].str[:8]
long = []
for h in hs:
    v = 'v' + h[1:]
    t = num(df[h]).where(df[v] == 'V')
    long.append(pd.DataFrame({'cod': df['cod'].values, 'fecha': df['fecha'].values, 'h': int(h[1:]), 't': t.values}))
L = pd.concat(long).dropna()
P = L.pivot_table(index=['fecha', 'h'], columns='cod', values='t')
st = e.set_index('estacion_codigo').loc[P.columns, ['estacion_municipio', 'x', 'y', 'z']]
print('Estaciones con temperatura en el curso:', P.shape[1], '| horas lectivas-hora:', P.shape[0])
print('Cobertura media por estación (% horas válidas):', round(P.notna().mean().mean() * 100, 1),
      '| mín:', round(P.notna().mean().min() * 100, 1), P.notna().mean().idxmin())
print('Altitud estaciones: min', st.z.min(), 'max', st.z.max())

# --- LOO
def interp(P, st, tgt, method, lapse=-0.0065, p=2, k=None):
    others = [c for c in P.columns if c != tgt]
    d = np.hypot(st.loc[others, 'x'] - st.loc[tgt, 'x'], st.loc[others, 'y'] - st.loc[tgt, 'y']).values
    T = P[others].values.copy()
    if 'lapse' in method:
        T = T + lapse * (st.loc[tgt, 'z'] - st.loc[others, 'z'].values)
    if method.startswith('nn'):
        order = np.argsort(d)
        out = np.full(len(P), np.nan)
        for j in order[::-1]:
            col = T[:, j]; out = np.where(~np.isnan(col), col, out)
        return out
    w = 1 / d ** p
    if k: w = np.where(np.argsort(np.argsort(d)) < k, w, 0)
    W = np.where(np.isnan(T), 0, w)
    return np.nansum(np.nan_to_num(T) * W, axis=1) / W.sum(axis=1)

res = {}
for meth in ['nn', 'nn_lapse', 'idw', 'idw_lapse', 'idw5_lapse']:
    err, herr = [], []
    for c in P.columns:
        k = 5 if meth == 'idw5_lapse' else None
        pr = interp(P, st, c, meth.replace('idw5', 'idw'), k=k)
        obs = P[c].values; ok = ~np.isnan(obs) & ~np.isnan(pr)
        err.append(pd.DataFrame({'cod': c, 'e': pr[ok] - obs[ok]}))
        herr.append((c, (obs[ok] >= 27).sum(), (pr[ok] >= 27).sum(), np.clip(obs[ok] - 25, 0, None).sum(), np.clip(pr[ok] - 25, 0, None).sum()))
    E = pd.concat(err); H = pd.DataFrame(herr, columns=['cod', 'obs27', 'pred27', 'obsGH25', 'predGH25'])
    by = E.groupby('cod')['e'].apply(lambda s: np.sqrt((s ** 2).mean()))
    by_noR = by.drop('28120001', errors='ignore')
    Hn = H[H.cod != '28120001']
    res[meth] = dict(rmse_all=np.sqrt((E.e ** 2).mean()), rmse_med_est=by.median(), rmse_sinRascafria=np.sqrt((E[E.cod != '28120001'].e ** 2).mean()),
                     sesgo=E.e.mean(), mae_horas27=(Hn.pred27 - Hn.obs27).abs().median(),
                     spearman_h27=Hn[['obs27', 'pred27']].corr('spearman').iloc[0, 1],
                     spearman_gh25=Hn[['obsGH25', 'predGH25']].corr('spearman').iloc[0, 1],
                     spearman_gh25_sinMajad=Hn[Hn.cod != '28080003'][['obsGH25', 'predGH25']].corr('spearman').iloc[0, 1])
    if meth == 'idw_lapse':
        keep = H.merge(by.rename('rmse').reset_index(), on='cod').merge(st[['estacion_municipio', 'z']].reset_index().rename(columns={'index': 'cod', 'estacion_codigo': 'cod'}), on='cod')
print('\nValidación dejando fuera una estación (28 estaciones, horas 9-14 h lectivas 2025/26):')
print(pd.DataFrame(res).T.round(2).to_string())
print('\nDetalle idw_lapse por estación (horas >=27 ºC observadas vs predichas, RMSE ºC):')
print(keep.sort_values('rmse', ascending=False).round(2).to_string(index=False))

# --- centros
c = pd.read_csv(fc, sep=';', dtype=str, encoding='utf-8-sig')
print('\nCentros en el fichero:', len(c), '| ALTA:', (c['SITUACIÓN'] == 'ALTA').sum())
a = c[c['SITUACIÓN'] == 'ALTA'].copy()
a['X'] = num(a['UTM_X']); a['Y'] = num(a['UTM_Y'])
print('ALTA con UTM válida:', a['X'].between(350000, 520000).sum(), 'de', len(a))
print('ALTA por titularidad:', a['TITULARIDAD'].value_counts().to_dict())
pub = a[a['TITULARIDAD'].str.startswith('PÚB', na=False)]
print('\nPúblicos ALTA por tipo (top 12):'); print(pub['TIPO_ABRV'].value_counts().head(12).to_string())
fc_ = pd.to_datetime(pub['FECHA CONSTITUCIÓN'].str[:10], errors='coerce')
print('Públicos con FECHA CONSTITUCIÓN:', fc_.notna().sum(), 'de', len(pub), '| antes de 2006:', (fc_ < '2006-01-01').sum())
for t in ['CP INF-PRI', 'IES', 'EEI']:
    s = pub[pub['TIPO_ABRV'] == t]; ft = pd.to_datetime(s['FECHA CONSTITUCIÓN'].str[:10], errors='coerce')
    print(f'  {t}: {len(s)} | con fecha {ft.notna().sum()} | <2006 {(ft < "2006-01-01").sum()} | Madrid capital {(s["MUNICIPIO"] == "Madrid").sum()}')
g = pub[pub['X'].between(350000, 520000)]
D = np.hypot(g['X'].values[:, None] - st['x'].values[None, :], g['Y'].values[:, None] - st['y'].values[None, :]) / 1000
g = g.assign(dkm=D.min(axis=1))
print('\nDistancia (km) de centros públicos ALTA a la estación con temperatura más cercana:')
print(g.groupby(g['MUNICIPIO'] == 'Madrid')['dkm'].describe(percentiles=[.5, .9]).round(1).to_string())
print('Centros públicos en Madrid capital:', (pub['MUNICIPIO'] == 'Madrid').sum(), 'de', len(pub))
