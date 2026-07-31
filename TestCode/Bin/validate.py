"""在合成資料上量測誤報率與各類缺陷的偵測率。"""
import os, random, shutil
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import print_qc as P

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]
CH = "0123456789ABCDEFGHJKLMNPRSTUVWXY"

def render(text, fp, size=44):
    img = Image.new("L", (420, 90), 235)
    ImageDraw.Draw(img).text((20, 18), text, font=ImageFont.truetype(fp, size), fill=30)
    a = cv2.GaussianBlur(np.array(img), (3, 3), 0.6)
    return np.clip(a.astype(np.int16) + np.random.normal(0, 3, a.shape), 0, 255).astype(np.uint8)

def rand_img():
    return render("".join(random.choice(CH) for _ in range(6)), random.choice(FONTS))

def boxes_of(img):
    cfg = dict(P.CFG)
    b = P.binarize(img, cfg)
    return P.segment_chars(b, cfg), b

# ---- 缺陷注入（都作用在隨機挑中的一個字元上）----
def d_break(img):                      # 斷筆：在骨架上挖掉一小段，確保筆畫真的斷開
    from skimage.morphology import skeletonize
    bx, b = boxes_of(img)
    x, y, w, h = random.choice(bx)
    sub = b[y:y+h, x:x+w]
    sw = max(2.0, float(np.median(2 * cv2.distanceTransform(sub, cv2.DIST_L2, 5)[skeletonize(sub > 0)])))
    ys, xs = np.nonzero(skeletonize(sub > 0))
    if len(ys) == 0:
        return img
    i = random.randrange(len(ys))
    cv2.circle(img, (x + xs[i], y + ys[i]), max(2, int(round(0.7 * sw))), 235, -1)
    return img

def d_speckle(img):                    # 噴濺：字元附近的背景上加墨點
    bx, b = boxes_of(img)
    x, y, w, h = random.choice(bx)
    for _ in range(200):
        px, py = random.randint(x, x+w), random.randint(y, y+h)
        if b[max(0,py-5):py+6, max(0,px-5):px+6].sum() == 0:
            cv2.circle(img, (px, py), 2, 25, -1); break
    return img

def d_blur(img):                       # 暈染/離焦
    bx, _ = boxes_of(img)
    x, y, w, h = random.choice(bx)
    r = img[y-6:y+h+6, x-6:x+w+6]
    img[y-6:y+h+6, x-6:x+w+6] = cv2.GaussianBlur(r, (11, 11), 4.5)
    return img

def d_bold(img):                       # 墨量過多 → 筆畫變粗
    bx, _ = boxes_of(img)
    x, y, w, h = random.choice(bx)
    r = img[y-4:y+h+4, x-4:x+w+4]
    img[y-4:y+h+4, x-4:x+w+4] = cv2.erode(r, np.ones((3, 3), np.uint8))
    return img

def d_faint(img):                       # 淡墨 → 對比不足
    bx, _ = boxes_of(img)
    x, y, w, h = random.choice(bx)
    r = img[y-4:y+h+4, x-4:x+w+4].astype(np.float32)
    img[y-4:y+h+4, x-4:x+w+4] = np.clip(235 - (235 - r) * 0.32, 0, 255).astype(np.uint8)
    return img

DEFECTS = {"斷筆": d_break, "噴濺點": d_speckle, "暈染/離焦": d_blur,
           "墨量過多": d_bold, "淡墨": d_faint}

random.seed(1); np.random.seed(1)
shutil.rmtree("v_good", ignore_errors=True); os.makedirs("v_good")
for i in range(60):
    cv2.imwrite(f"v_good/{i:03d}.png", rand_img())

cfg = dict(P.CFG)
samples = []
for f in sorted(os.listdir("v_good")):
    _, _, res = P.inspect(f"v_good/{f}", cfg)
    samples += [r.metrics for r in res if r.metrics]
bl = P.Baseline.fit(samples, cfg)
print(f"基準：60 張良品 / {len(samples)} 個字元\n")

def injected(a, b, name=""):
    """確認缺陷真的落在字上。斷筆另外要求連通域數量真的增加。"""
    ba, bb = P.binarize(a, cfg), P.binarize(b, cfg)
    if int(np.abs(ba.astype(int) - bb.astype(int)).sum() // 255) < 8:
        return False
    if name == "斷筆":
        return cv2.connectedComponentsWithStats(bb, 8)[0] > \
               cv2.connectedComponentsWithStats(ba, 8)[0]
    return True

N = 120
fp_img = fp_ch = tot_ch = 0
for _ in range(N):
    img = rand_img(); cv2.imwrite("_t.png", img)
    _, _, res = P.inspect("_t.png", cfg, bl)
    tot_ch += len(res); n = sum(r.ng for r in res)
    fp_ch += n; fp_img += (n > 0)
print(f"誤報（獨立良品 {N} 張 / {tot_ch} 字元）")
print(f"  字元層級 {fp_ch}/{tot_ch} = {fp_ch/tot_ch*100:.2f}%")
print(f"  整張判 NG {fp_img}/{N} = {fp_img/N*100:.2f}%\n")

print("偵測率（每類 120 張；只統計「缺陷確實注入成功」的樣本）")
for name, fn in DEFECTS.items():
    hit = tried = 0
    for _ in range(N):
        clean = rand_img(); img = fn(clean.copy())
        if not injected(clean, img, name):
            continue
        tried += 1
        cv2.imwrite("_t.png", img)
        _, _, res = P.inspect("_t.png", cfg, bl)
        hit += any(r.ng for r in res)
    r = hit / tried * 100 if tried else 0
    print(f"  {name:10s} {hit}/{tried} = {r:5.1f}%")
os.remove("_t.png")


# --- 混字型 vs 單一字型：筆畫粗細指標的敏感度差異 ---
print("\n筆畫粗細 (stroke_ratio) 的基準寬度")
for tag, fonts in (("混 3 種字型", FONTS), ("單一字型", FONTS[:1])):
    ss = []
    for _ in range(60):
        cv2.imwrite("_f.png", render("".join(random.choice(CH) for _ in range(6)), random.choice(fonts)))
        _, _, rr = P.inspect("_f.png", cfg)
        ss += [x.metrics for x in rr if x.metrics]
    b2 = P.Baseline.fit(ss, cfg)
    hit = tried = 0
    for _ in range(80):
        c = render("".join(random.choice(CH) for _ in range(6)), random.choice(fonts))
        im = d_bold(c.copy())
        if not injected(c, im):
            continue
        tried += 1
        cv2.imwrite("_f.png", im); _, _, rr = P.inspect("_f.png", cfg, b2)
        hit += any(x.ng for x in rr)
    print(f"  {tag}: mad={b2.mad['stroke_ratio']:.4f}  墨量過多偵測率 {hit}/{tried} = {hit/max(tried,1)*100:.0f}%")
os.remove("_f.png")
