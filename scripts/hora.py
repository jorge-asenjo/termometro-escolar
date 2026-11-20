"""Comprueba el huso horario de calidad_aire_datos_meteo_historico: hora media del pico de
radiación solar (magnitud 88) por mes. Si el pico no se mueve 1 h entre invierno y verano, la
hora es fija (UTC o similar), no la oficial de Madrid.
Uso: python -I scripts/hora.py <carpeta_meteo>"""
import sys,glob,os,pandas as pd,numpy as np
sys.stdout.reconfigure(encoding='utf-8')
d=sys.argv[1]
hs=[f'h{i:02d}' for i in range(1,25)]
out=[]
for f in sorted(glob.glob(os.path.join(d,'20*.csv'))):
    x=pd.read_csv(f,sep=';',dtype=str,encoding='utf-8-sig')
    x=x[x['magnitud']=='88']
    v=x[hs].apply(lambda s:pd.to_numeric(s.str.replace(',','.'),errors='coerce'))
    w=v.values; w=np.where(np.isnan(w),0,w); w=np.clip(w,0,None)
    # centroide de la curva de radiación (hora fin) -> centro del intervalo = hora-0.5
    cen=(w*np.arange(1,25)).sum(axis=1)/np.where(w.sum(axis=1)>0,w.sum(axis=1),np.nan)-0.5
    out.append(pd.DataFrame({'ano':x['ano'].values,'mes':x['mes'].astype(int).values,'cen':cen}))
o=pd.concat(out)
print('Centroide medio de la radiación (hora del reloj del fichero; mediodía solar en Madrid ~12:15 UTC):')
print(o.groupby('mes')['cen'].median().round(2).to_string())
