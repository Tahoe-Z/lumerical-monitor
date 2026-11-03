"""Build icon.ico (the sidebar logo: a pulse line on a rounded accent square). Needs Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

S = 1024  # draw large, downsample for smooth edges
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([40, 40, S-40, S-40], radius=230, fill='#D97757')
u = (S-80)/36
pts = [(7, 19), (13, 19), (16, 11), (21, 26), (24, 17), (29, 17)]
d.line([(40+x*u, 40+y*u) for x, y in pts], fill='#FFFFFF', width=int(2.8*u), joint='curve')
for x, y in (pts[0], pts[-1]):
    r = 1.4*u
    d.ellipse([40+x*u-r, 40+y*u-r, 40+x*u+r, 40+y*u+r], fill='#FFFFFF')
img.resize((256, 256), Image.LANCZOS).save(Path(__file__).with_name('icon.ico'),
                                           sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('icon.ico written')
