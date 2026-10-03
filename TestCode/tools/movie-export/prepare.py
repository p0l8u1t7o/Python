"""建立錄影用的網站副本（TEMP/movie-site），網址配置與 GitHub Pages 相同：/core/、/<專案>/。

錄影掛鉤已寫在各專案 main.js（網址加 ?movie 時呼叫 core/movie/movie.js），這裡只負責複製，不再修改程式。
    python tools/movie-export/prepare.py
"""
from pathlib import Path
import shutil, subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'TEMP' / 'movie-site'

if OUT.exists():
    shutil.rmtree(OUT)
subprocess.run(['node', str(ROOT / 'core' / 'tools' / 'build-site.mjs'), str(OUT)], check=True)
print(f'錄影網站：{OUT}')
