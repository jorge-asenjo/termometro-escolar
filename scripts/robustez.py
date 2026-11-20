"""Robustez del orden entre estaciones: estabilidad entre cursos (Spearman), media plurianual
y fecha del salto de sesgo de Móstoles (posible cambio de sensor o de emplazamiento).
Entrada: el CSV de calor_lectivo.py y la carpeta de meteo.
Uso: python -I scripts/robustez.py <calor_lectivo.csv> <carpeta_meteo>"""
import sys, glob, os, warnings
import pandas as pd, numpy as np
from scipy.stats import spearmanr
warnings.simplefilter('ignore')
sys.stdout.reconfigure(encoding='utf-8')
g = pd.read_csv(sys.argv[1], dtype={'cod': str})
g = g[(g.cobertura >= 0.9) & (g.cod != '28120001') & g.curso.between(2020, 2025)]
P = g.pivot_table(index=['cod', 'muni'], columns='curso', values='d27')
print('Spearman del orden de estaciones entre cursos consecutivos (días >= 27 °C):')
for a in range(2020, 2025):
    s = P[[a, a + 1]].dropna()
    r = spearmanr(s[a], s[a + 1]).statistic
    print(f'  {a}/{a+1-2000:02d} vs {a+1}/{a+2-2000:02d}: rho = {r:.2f} (n = {len(s)})')
s = P[[2024, 2025]].dropna()
pm = P[[2020, 2021, 2022, 2023, 2024]].mean(axis=1)
s2 = pd.concat([pm, P[2025]], axis=1).dropna()
print(f'  media 2020-2024 vs 2025/26: rho = {spearmanr(s2.iloc[:,0], s2.iloc[:,1]).statistic:.2f} (n = {len(s2)})')
P['media_5c'] = P[[2021, 2022, 2023, 2024, 2025]].mean(axis=1)
P['n_cursos'] = P[[2021, 2022, 2023, 2024, 2025]].notna().sum(axis=1)
print('\nDías lectivos >= 27 °C por curso y media 2021/22-2025/26:')
print(P.round(1).sort_values('media_5c', ascending=False).to_string())
# Móstoles: sesgo mensual frente a la mediana de la red (todas las horas lectivas 9-14 h oficiales, todo el año)
H = [f'h{i:02d}' for i in range(1, 25)]; V = [f'v{i:02d}' for i in range(1, 25)]
dfs = []
for f in sorted(glob.glob(os.path.join(sys.argv[2], '20*.csv'))):
    x = pd.read_csv(f, sep=';', dtype=str, encoding='utf-8-sig'); x = x[x['magnitud'] == '83'].copy()
    for h, v in zip(H, V):
        x[h] = pd.to_numeric(x[h].str.replace(',', '.'), errors='coerce').where(x[v] == 'V')
    dfs.append(x[['punto_muestreo', 'ano', 'mes', 'dia'] + H])
df = pd.concat(dfs, ignore_index=True)
df['cod'] = df['punto_muestreo'].str[:8]
df['tmed'] = df[H].mean(axis=1)
df['tmax'] = df[H].max(axis=1)
df['ym'] = df['ano'] + '-' + df['mes']
df['key'] = df['ano'] + df['mes'] + df['dia']
for k in ['tmed', 'tmax']:
    df['d_' + k] = df[k] - df.groupby('key')[k].transform('median')
print('\nSesgo mensual (°C) de la temperatura media y máxima diaria frente a la mediana de la red:')
for cod, nom in [('28092005', 'Móstoles'), ('28074007', 'Leganés'), ('28148004', 'Torrejón'), ('28058004', 'Fuenlabrada')]:
    z = df[df.cod == cod].groupby('ym')[['d_tmed', 'd_tmax']].mean().round(1)
    z['ano'] = z.index.str[:4]
    print(f'  {nom} (media anual de d_tmax):', z.groupby('ano')['d_tmax'].mean().round(2).to_dict())
    if cod == '28092005':
        print('   Móstoles mes a mes 2024-2026 (d_tmax):', z.loc[z.index >= '2024-01', 'd_tmax'].to_dict())
