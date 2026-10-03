"""把舊的形狀介面改成 core/geom/shapes.js 的統一介面（只改有從 parts.js／primitives.js 匯入的檔案）。

    python core/tools/codemod-shapes.py <檔案或資料夾>…        # 直接改寫
    python core/tools/codemod-shapes.py --dry <檔案或資料夾>…  # 只列出會改的檔案

  box(p, w, h, d, mat, x, y, z)      → block(p, [w, h, d], [x, y, z], mat)
  cyl(p, r, h, mat, x, y, z, axis, seg, r2) → cylinder(p, r, h, [x, y, z], mat, axis, seg, r2)（未給 seg 時補 28，保持原外觀）
  boxAt(p, a, b, mat)                → blockBetween(p, a, b, mat)
  MAT → materials.js；smooth／lerp／clamp01 → anim/track.js；其餘 → shapes.js
"""
import re, sys
from pathlib import Path

RENAME = {'box': 'block', 'boxAt': 'blockBetween', 'cyl': 'cylinder'}
TRACK = {'smooth', 'lerp', 'clamp01'}
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*(['\"])([^'\"]*?)(parts|primitives)\.js\2;?")


def split_args(src, i):
    """src[i] 為 '('；回傳 (參數字串清單, 右括號位置)"""
    depth, args, cur, j, quote = 0, [], '', i + 1, None
    while j < len(src):
        c = src[j]
        if quote:
            cur += c
            if c == '\\':
                cur += src[j + 1]; j += 2; continue
            if c == quote: quote = None
        elif c in '\'"`':
            quote = c; cur += c
        elif c in '([{':
            depth += 1; cur += c
        elif c in ')]}':
            if depth == 0:
                if cur.strip(): args.append(cur.strip())
                return args, j
            depth -= 1; cur += c
        elif c == ',' and depth == 0:
            args.append(cur.strip()); cur = ''
        else:
            cur += c
        j += 1
    raise ValueError('括號不成對')


def rewrite_calls(src, name, fn):
    out, pos = [], 0
    for m in re.finditer(r'(?<![\w.$])' + name + r'\s*\(', src):
        if m.start() < pos: continue
        open_i = m.end() - 1
        args, close_i = split_args(src, open_i)
        out.append(src[pos:m.start()]); out.append(fn(args)); pos = close_i + 1
    out.append(src[pos:])
    return ''.join(out)


def conv_box(a):
    p, w, h, d, mat = a[:5]
    x, y, z = (a[5:8] + ['0', '0', '0'])[:3]
    return f'block({p}, [{w}, {h}, {d}], [{x}, {y}, {z}], {mat})'


def conv_cyl(a):
    p, r, h, mat = a[:4]
    x, y, z = (a[4:7] + ['0', '0', '0'])[:3]
    axis = a[7] if len(a) > 7 else "'y'"
    seg = a[8] if len(a) > 8 else '28'
    tail = f', {a[9]}' if len(a) > 9 else ''
    return f'cylinder({p}, {r}, {h}, [{x}, {y}, {z}], {mat}, {axis}, {seg}{tail})'


def conv_boxat(a):
    return 'blockBetween(' + ', '.join(a) + ')'


def convert(text):
    m_all = list(IMPORT_RE.finditer(text))
    if not m_all: return text
    names = set()
    for m in m_all:
        names |= {n.strip().split(' as ')[0].strip() for n in m.group(1).split(',') if n.strip()}
    prefix = m_all[0].group(3)                  # 例：'@core/geom/'、'../geom/'、'./'
    track_prefix = prefix.replace('geom/', 'anim/') if 'geom/' in prefix else '../anim/'   # './' 只出現在 core/geom 內
    shapes = sorted({RENAME.get(n, n) for n in names if n not in TRACK and n != 'MAT'})
    lines = []
    if shapes: lines.append(f"import {{ {', '.join(shapes)} }} from '{prefix}shapes.js';")
    if 'MAT' in names: lines.append(f"import {{ MAT }} from '{prefix}materials.js';")
    track = sorted(names & TRACK)
    if track: lines.append(f"import {{ {', '.join(track)} }} from '{track_prefix}track.js';")
    first = m_all[0]
    text = text[:first.start()] + '\n'.join(lines) + text[first.end():]
    for m in IMPORT_RE.finditer(text):         # 其餘的舊匯入行刪除（已合併到上面）
        text = text.replace(m.group(0) + '\n', '', 1)
    if 'boxAt' in names: text = rewrite_calls(text, 'boxAt', conv_boxat)
    if 'box' in names: text = rewrite_calls(text, 'box', conv_box)
    if 'cyl' in names: text = rewrite_calls(text, 'cyl', conv_cyl)
    return text


def main():
    args = sys.argv[1:]; dry = '--dry' in args; args = [a for a in args if a != '--dry']
    files = []
    for a in args:
        p = Path(a)
        files += sorted(p.rglob('*.js')) + sorted(p.rglob('*.mjs')) if p.is_dir() else [p]
    for f in files:
        src = f.read_text(encoding='utf-8')
        out = convert(src)
        if out != src:
            print(('會改：' if dry else '已改：') + str(f))
            if not dry: f.write_text(out, encoding='utf-8', newline='')


if __name__ == '__main__':
    main()
