"""Збирає index.html: шаблон + стиль + шрифти e-Ukraine + Leaflet + QR + data/data.json → один самодостатній файл.
python scripts/assemble.py        → новий дизайн (v2)
python scripts/assemble.py --v1   → попередній дизайн (v1) у index_v1.html"""
import os, sys, base64
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
r = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
v1 = '--v1' in sys.argv
tpl = r('web', 'template.html' if v1 else 'template_v2.html')
if not v1:
    faces = []
    for fam, f, w in [('e-Ukraine', 'e-Ukraine-Light', 300), ('e-Ukraine', 'e-Ukraine-Regular', 400), ('e-Ukraine', 'e-Ukraine-Medium', 500),
                      ('e-Ukraine', 'e-Ukraine-Bold', 700), ('e-Ukraine Head', 'e-UkraineHead-Medium', 500), ('e-Ukraine Head', 'e-UkraineHead-Bold', 700)]:
        b64 = base64.b64encode(open(os.path.join(ROOT, 'web', 'fonts', f + '.woff2'), 'rb').read()).decode()
        faces.append(f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{b64}) format('woff2');font-weight:{w};font-style:normal;font-display:swap}}")
    tpl = tpl.replace('/*__STYLE__*/', r('web', 'style_v2.css').replace('/*__FONTS__*/', '\n'.join(faces)))
    img = lambda f: 'data:image/png;base64,' + base64.b64encode(open(os.path.join(ROOT, 'web', 'img', f), 'rb').read()).decode()
    tpl = tpl.replace('/*__GERB__*/', img('gerb.png')).replace('/*__FAVICON__*/', img('favicon.png'))
html = tpl.replace('/*__LEAFLET_CSS__*/', r('web', 'leaflet.css')) \
    .replace('/*__LEAFLET_JS__*/', r('web', 'leaflet.js')).replace('/*__QR_JS__*/', r('web', 'qrcode.js')) \
    .replace('/*__DATA__*/', r('data', 'data.json').replace('</', '<\\/'))
out = os.path.join(ROOT, 'index_v1.html' if v1 else 'index.html')
open(out, 'w', encoding='utf-8').write(html)
print(os.path.basename(out), len(html), 'chars')
