"""Render a demo prescription with exact names and a machine-readable QR code.

Usage: node scripts/generate-demo-prescription.mjs | python scripts/render-demo-prescription.py
Requires Pillow. No patient data or dosage instructions are generated.
"""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

data = json.load(sys.stdin)
root = Path(__file__).resolve().parents[1]
font_root = Path('C:/Windows/Fonts')
def font(size, bold=False):
    return ImageFont.truetype(str(font_root / ('msjhbd.ttc' if bold else 'msjh.ttc')), size)

image = Image.new('RGB', (1440, 1800), 'white')
draw = ImageDraw.Draw(image)
green = '#16725c'
draw.rectangle((0, 0, 1440, 20), fill=green)
draw.text((100, 80), 'MediGuard', font=font(46, True), fill=green)
draw.text((100, 155), '模擬藥單', font=font(62, True), fill='#18392f')
draw.text((100, 248), '藥品辨識與核對測試用', font=font(28), fill='#667c73')
draw.text((100, 330), '藥單編號  RX-DEMO-004', font=font(26), fill='#38594b')
draw.line((100, 395, 1340, 395), fill='#dce6e0', width=2)
rows = data['rows']
qr = Image.new('RGB', (len(rows[0]), len(rows)), 'white')
qr.putdata([(0, 0, 0) if bit else (255, 255, 255) for row in rows for bit in row])
image.paste(qr, ((1440 - qr.width)//2, 425))
draw.text((720, 985), '啟動辨識後，使用相機掃描 QR code', anchor='mt', font=font(27), fill='#38594b')
draw.rounded_rectangle((100, 1075, 1340, 1145), radius=12, fill='#edf5f0')
draw.text((130, 1090), '核對藥品清單', font=font(29, True), fill=green)
for index, medicine in enumerate(data['prescription']['medicines']):
    y = 1190 + index * 104
    draw.text((130, y), f'{index+1:02d}', font=font(28, True), fill=green)
    draw.text((205, y), medicine['name'], font=font(28, True), fill='#203c30')
    draw.line((130, y+76, 1310, y+76), fill='#e6ece8', width=2)
draw.text((100, 1660), '僅供系統展示與掃碼測試，非醫療處方。', font=font(27, True), fill='#6b7f74')
draw.text((100, 1710), '掃碼取得藥單 → Cam1 辨識 → 逐項核對 → 核對成功', font=font(25), fill='#6b7f74')
output = root / 'public' / 'demo-prescription.png'
image.save(output)
print(output)
