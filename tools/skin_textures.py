#!/usr/bin/env python3
"""Текстуры тем оформления (ui/assets/skins/*.webp): мрамор (зерно grain.webp — случайный шум, см. skins.css). Рисуются из SVG
(feTurbulence) в Chromium и сохраняются картинками — в окне фон-картинка ничего не стоит процессору, а живой фильтр SVG
перерисовывался бы с каждым кадром облика. Поменяли рецепт — запустить и закоммитить картинки:

    python3 tools/skin_textures.py ui/assets/skins
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
W, H = 600, 840
SVG = {
 # чёрный мрамор с белыми прожилками
 "marble": f"""<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}'>
  <defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#202024'/><stop offset='1' stop-color='#0c0c0e'/></linearGradient>
  <filter id='v' x='0' y='0' width='100%' height='100%'><feTurbulence type='fractalNoise' baseFrequency='0.0016 0.011' numOctaves='6' seed='21'/>
   <feColorMatrix type='matrix' values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  2.2 0 0 0 -0.85'/>
   <feComponentTransfer><feFuncA type='table' tableValues='0 0 0 0 0 0.12 0.7 0.12 0 0 0 0 0'/></feComponentTransfer>
   <feGaussianBlur stdDeviation='0.7'/></filter>
  <filter id='c' x='0' y='0' width='100%' height='100%'><feTurbulence type='fractalNoise' baseFrequency='0.01' numOctaves='4' seed='4'/>
   <feColorMatrix type='matrix' values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.09 0'/></filter></defs>
  <rect width='100%' height='100%' fill='url(#g)'/><rect width='100%' height='100%' filter='url(#c)'/>
  <g transform='rotate(-32 {W/2} {H/2})'><rect x='-400' y='-400' width='{W+800}' height='{H+800}' filter='url(#v)' opacity='.55'/></g></svg>""",
}
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": W, "height": H})
    for k, svg in SVG.items():
        pg.set_content(f"<body style='margin:0'>{svg}</body>"); pg.wait_for_timeout(300)
        png = out / f"{k}.png"; pg.screenshot(path=str(png))
    b.close()
from PIL import Image
for k in SVG:
    im = Image.open(out / f"{k}.png").convert("RGB"); im.save(out / f"{k}.webp", quality=82, method=6); (out / f"{k}.png").unlink()
    print(k, (out / f"{k}.webp").stat().st_size)
