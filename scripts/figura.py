"""Figura: días de clase con >= 27 °C en la calle entre las 9 y las 14 h, por estación.
Barra = rango entre cursos 2021/22-2025/26; punto = media de esos 5 cursos; rombo = 2025/26.
Uso: python -I scripts/figura.py <calor_lectivo.csv> <salida.png>"""
import sys
import pandas as pd, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')
g = pd.read_csv(sys.argv[1], dtype={'cod': str})
g = g[(g.cobertura >= 0.9) & (g.cod != '28120001') & g.curso.between(2021, 2025)]
P = g.pivot_table(index=['cod', 'muni'], columns='curso', values='d27')
P['media'] = P[[2021, 2022, 2023, 2024, 2025]].mean(axis=1)
P['mn'] = P[[2021, 2022, 2023, 2024, 2025]].min(axis=1)
P['mx'] = P[[2021, 2022, 2023, 2024, 2025]].max(axis=1)
P['n'] = P[[2021, 2022, 2023, 2024, 2025]].notna().sum(axis=1)
P = P.reset_index().sort_values('media')
SOSP = {'28092005': 'posible cambio de sensor: +2 °C frente a la red desde abr-2025',
        '28074007': 'posible cambio de sensor: +1,5 °C frente a la red en 2026'}
INK, MUTED, GRID, ACC = '#1f2328', '#6b7280', '#e5e7eb', '#1d5fbf'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10})
fig, ax = plt.subplots(figsize=(10, 9.2), dpi=200)
y = np.arange(len(P))
ax.hlines(y, P['mn'], P['mx'], color='#c7d4ea', lw=6, capstyle='round', zorder=1)
ax.scatter(P['media'], y, s=46, color=ACC, zorder=3, label='Media 2021/22-2025/26')
ax.scatter(P[2025], y, s=40, marker='D', facecolor='white', edgecolor=INK, lw=1.2, zorder=4,
           label='Curso 2025/26 (el más caluroso)')
labels = []
for _, r in P.iterrows():
    t = r['muni'].replace('San Sebastián de los Reyes', 'S. Sebastián de los Reyes') + ('' if r['n'] == 5 else f"  ({int(r['n'])} cursos)")
    if r['cod'] in SOSP:
        t += '  *'
    labels.append(t)
ax.set_yticks(y, labels, color=INK)
for i, (_, r) in enumerate(P.iterrows()):
    if r['cod'] in SOSP:
        ax.text(r[2025] + 0.9, i, '* ' + SOSP[r['cod']].replace(': ', ':\n'), va='center', fontsize=7.2, color=MUTED)
ax.axvline(20, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=0)
ax.text(20.4, 3.2, '«unos 20 días» de calor con alumnos\n(Gobierno regional, jun-2026)',
        fontsize=7.8, color=MUTED, va='center')
ax.set_xlim(-0.5, 50)
ax.set_ylim(-0.8, len(P) - 0.2)
ax.set_xlabel('Días lectivos al año con ≥ 27 °C exteriores entre las 9 y las 14 h (hora oficial)', color=INK)
ax.grid(axis='x', color=GRID, lw=0.8)
ax.set_axisbelow(True)
for s in ['top', 'right', 'left']:
    ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#9ca3af')
ax.tick_params(axis='y', length=0)
ax.tick_params(axis='x', colors=MUTED)
lo, hi = P['media'].min(), P['media'].max()
fig.suptitle('El calor en horas de clase va de 4 a 23 días al año según el municipio',
             x=0.02, ha='left', fontsize=15, fontweight='bold', color=INK, y=0.985)
fig.text(0.02, 0.945, 'Días de colegio con ≥ 27 °C en la calle entre las 9 y las 14 h, por estación de la Red de Calidad del Aire.\n'
         'Punto: media de 5 cursos · barra: del curso más fresco al más caluroso · rombo: 2025/26 (de 8 a 35 días).',
         ha='left', va='top', fontsize=9.5, color=MUTED)
ax.legend(loc='lower right', frameon=False, fontsize=8.8)
fig.text(0.02, 0.012,
         'Fuente: Comunidad de Madrid, datos abiertos · calidad_aire_datos_meteo_historico (id 7f3699fc-d646-4efa-9387-1f5aed4a45b6), temperatura horaria validada (V);\n'
         'calidad_aire_estaciones (id 4cd076a3-e602-48da-b834-58de39d3125c). Calendario escolar 2025/26 (8-sep a 19-jun, sin vacaciones ni días no lectivos regionales);\n'
         'cursos anteriores, ventana 8-sep a 19-jun. Temperatura EXTERIOR, no la del aula. Sin Puerto de Cotos (1.870 m). Cálculo: scripts/calor_lectivo.py.',
         fontsize=6.9, color=MUTED, ha='left', va='bottom')
fig.subplots_adjust(left=0.27, right=0.97, top=0.885, bottom=0.115)
fig.savefig(sys.argv[2], facecolor='white')
print('Guardada', sys.argv[2], '· estaciones:', len(P), '· media mín-máx:', round(lo, 1), round(hi, 1))
