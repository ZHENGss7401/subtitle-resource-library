#!/usr/bin/env python3
"""字幕资源库 · 生成器

把 2. 半成品 里各包的「定版字幕」裁定出来、收进 0. 字幕资源库\定版\，
并产出给人看的 总览.png / index.html 和给 agent 看的 INDEX.json。

三个不可回避的事实（2026-10-08 实测）：
  1. 同一版本编号跨批次用的是同一张图（Q29/Q01/B14-3/Q25-3 在 10.7、10.8 哈希相同）→ 编号可作主键
  2. 「定版」在文件海里认不出来：18 个包有 6 种命名写法，且与效果图混放
  3. 18 个包有 8 个没有核对 JSON → 那些「定版」只能是推断，不是证实

用法：
    python build_index.py                     # 重建全库（10.7 + 10.8）
    python build_index.py --find "Q30-1"      # 给 agent：返回定版路径 + 哈希
    python build_index.py --days 10.7 10.8    # 指定批次
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = r"Y:\足贴视频素材\BOREAC淋巴滴剂"
SEMI = os.path.join(ROOT, "2. 半成品")
FIN = os.path.join(ROOT, "1. 成品入口")
LIB = os.path.join(ROOT, "0. 字幕资源库")
STAGE = os.path.join(LIB, "定版")
DEFAULT_DAYS = ("10.7", "10.8", "9月/国庆五日视频")

CANVAS = (720, 1280)
BACKDROP = (74, 74, 74)          # 深灰：白字和白框都看得清
LOCKED_KEYS = ("locked_sha256", "original_png_sha256", "SHA256",
               "subtitle_sha256", "locked_subtitle_sha256")
FONT_CANDIDATES = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf")
FFMPEG = r"C:\Users\111\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
BACKFILL_NAME = "_字幕定版锁定.json"


# ---------- 基础 ----------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def alpha_span(path):
    """返回 alpha 的 (min,max)；没有 alpha 通道返回 None。"""
    try:
        im = Image.open(path)
    except Exception:                                              # noqa: BLE001
        return None
    if im.mode not in ("RGBA", "LA") and "transparency" not in im.info:
        return None
    return im.convert("RGBA").split()[3].getextrema()


def font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:                                      # noqa: BLE001
                pass
    return ImageFont.load_default()


# ---------- 半成品包解析 ----------

CODE_RE = re.compile(r"^(\d{3})-([A-Za-z]+\d+(?:-\d+)?)(?:-(加做))?-")


def package_code(name):
    m = CODE_RE.match(name)
    if not m:
        return None
    return m.group(2).upper() + (" 加做" if m.group(3) else "")


def bare_code(name):
    """不带「加做」标记的版本编号，作为主键。"""
    m = CODE_RE.match(name)
    return m.group(2).upper() if m else None


FILE_CODE_RE = re.compile(r"^([A-Za-z]+\d+(?:-\d+)?)_")


def code_from_file(name):
    """从定版文件名里取版本编号——那张字幕自己的编号。

    2026-10-08 惠跃纠正：「Q25_用户定版原图.png」这张就是 Q25，不是包名上的 Q25-3。
    包名是工序编号，文件名才是这张字幕的版本号。全库核对过，只此一例两者不同。
    """
    m = FILE_CODE_RE.match(name)
    return m.group(1).upper() if m else None


def recorded_hash(folder):
    """包内核对 JSON 里记的定版哈希。返回 (哈希, 文件名)。

    原始记录优先于本工具回填的那份——用户当次确认 > 复盘推断。
    """
    if not os.path.isdir(folder):
        return None, None
    found = []
    for n in sorted(os.listdir(folder)):
        if not n.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:                                          # noqa: BLE001
            continue
        for k in LOCKED_KEYS:
            v = data.get(k)
            if isinstance(v, str) and len(v) == 64:
                found.append((v.lower(), n))
                break
    if not found:
        return None, None
    native = [x for x in found if x[1] != BACKFILL_NAME]
    return native[0] if native else found[0]


def name_score(fn):
    """没有哈希凭据时的定版判定打分。已知对 Q27 有效：
    用户指定的 940x1672 原图(a4f5cab1) 胜出 Agent 重排的 720x1280 图。"""
    s = 0
    if "用户指定" in fn or "用户定版" in fn:
        s += 100
    elif "定版字幕" in fn or "定版原图" in fn:
        s += 80
    elif "定版参考" in fn:
        s += 60
    elif "定版" in fn:
        s += 50
    elif "透明字幕" in fn:
        s += 30
    if re.search(r"941|原尺寸|原图", fn):
        s += 10
    if re.search(r"720|适配", fn):
        s -= 5
    return s


def scan_package(pkg):
    """列出一个半成品包字幕夹里的全部 PNG，标出透明层与效果图。"""
    folder = os.path.join(pkg, "字幕夹")
    if not os.path.isdir(folder):
        return None
    locked, locked_file = recorded_hash(folder)
    items = []
    for n in sorted(os.listdir(folder)):
        if not n.lower().endswith(".png"):
            continue
        fp = os.path.join(folder, n)
        digest = sha256(fp)
        span = alpha_span(fp)
        im = Image.open(fp)
        items.append({
            "file": n, "path": fp, "sha256": digest,
            "bytes": os.path.getsize(fp), "size": list(im.size),
            "transparent": bool(span) and span[0] < 250,
            "is_locked": bool(locked) and digest == locked,
            "locked_file": locked_file,
            "score": name_score(n),
        })
    return {"pkg": pkg, "folder": folder, "locked": locked, "items": items}


def adjudicate(recs):
    """跨包裁定同一个版本编号的定版。

    必须在**同一编号的全部包之间**裁，不能只看单个包：Q27 就是跨两个同名包的
    例子——一个包只有 720x1280 的透明层（Agent 当初重排、被用户否掉的那版），
    另一个包放着用户指定的 940x1672 原图。只看包内会选中错的那张。

    优先级：① 核对 JSON 的哈希命中（最高权威）② 命名打分 ③ 认输
    """
    pool = [(r, c) for r in recs for c in r["candidates"]]
    locked = {c["sha256"]: (r, c) for r, c in pool if c["is_locked"]}
    if len(locked) == 1:
        r, c = next(iter(locked.values()))
        conf = "已回填" if c["locked_file"] == BACKFILL_NAME else "已证实"
        return r, c, "核对JSON哈希", conf, [(x, y) for x, y in pool if y["sha256"] != c["sha256"]]
    if len(locked) > 1:
        return None, None, "同编号下有多份互相矛盾的哈希记录", "冲突", list(locked.values())

    top = sorted(pool, key=lambda rc: -rc[1]["score"])
    best = top[0][1]["score"]
    winners = {c["sha256"] for _, c in top if c["score"] == best}
    if len(winners) > 1:
        return None, None, "两张候选并列，无可依据", "冲突", [rc for rc in top if rc[1]["score"] == best]
    r, c = top[0]
    losers = [(x, y) for x, y in top[1:] if y["sha256"] != c["sha256"]]
    return r, c, "命名推断", "推断", losers


def is_derivative(a, b):
    """b 是不是 a 的等比衍生（同一设计缩到别的画布）。

    一个版本常同时躺着 941x1672 母本和 720x1280 适配版——那是衍生物，不是冲突。
    真冲突长这样：Q27 的包 A 里是 Agent 重排、被用户否掉的那版，
    和用户指定的原图像素对不上。所以这里真的比一遍像素。
    实测标定（2026-10-08）：真衍生版均值差 4.2 / 6.8 / 8.6 / 8.8，
    真冲突（Q27 被否的重排版）55.1。取 20 居中——上不碰冲突，下容得下衍生。
    """
    try:
        A, B = Image.open(a).convert("RGBA"), Image.open(b).convert("RGBA")
    except Exception:                                              # noqa: BLE001
        return False
    if A.size == B.size:
        return False
    base, other = (B, A) if B.width <= A.width else (A, B)
    diff = ImageChops.difference(base, other.resize(base.size, Image.LANCZOS))
    hist = diff.convert("L").histogram()
    mean = sum(i * c for i, c in enumerate(hist)) / max(1, sum(hist))
    return mean < 20


def read_docx(path):
    """按段落取文本。段内的 <w:br/>（软换行）必须切成两行——不切的话
    「文案」和紧跟的标题会粘成一行。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    out = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        for chunk in re.split(r"<w:br[^>]*/>", para):
            t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", chunk, re.S))
            t = re.sub(r"<[^>]+>", "", t).strip()
            if t:
                out.append(t)
    return out


def read_copy(pkg):
    """文案来自半成品包：优先中英文 txt，其次 docx。~$ 开头的是 Word 锁文件，跳过。"""
    if not os.path.isdir(pkg):
        return None

    def rank(n):
        low = n.lower()
        if "中英文文案" in n and low.endswith(".txt"):
            return 0
        if "文案" in n and low.endswith(".txt"):
            return 1
        if "文案" in n and low.endswith(".docx"):
            return 2
        return 9

    names = sorted((n for n in os.listdir(pkg)
                    if not n.startswith("~$") and rank(n) < 9), key=rank)
    if not names:
        return None
    fn = names[0]
    try:
        if fn.lower().endswith(".docx"):
            lines = read_docx(os.path.join(pkg, fn))
        else:
            with open(os.path.join(pkg, fn), encoding="utf-8-sig", errors="replace") as f:
                lines = f.read().splitlines()
    except Exception as exc:                                       # noqa: BLE001
        return {"source": fn, "lines": [], "error": str(exc)}
    lines = [x for x in (l.strip() for l in lines) if x]
    return {"source": fn, "lines": lines}


PREVIEW_RANKS = ("定版预览", "叠加预览", "成品预览", "成品首帧预览", "今日成品预览", "字幕预览")


def preview_rank(name):
    for i, key in enumerate(PREVIEW_RANKS):
        if key in name:
            return i
    return 9


def find_finished(codes, days):
    """成品入口里这些编号的成品包（同编号可能出现在多个日期；成品包名可能用的是别名）。"""
    hits = []
    for day in days:
        d = os.path.join(FIN, day)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if os.path.isdir(p) and bare_code(n) in codes:
                hits.append(p)
    return hits


def pick_preview(code, pkg_code, pkgs, days):
    """定版预览图从哪来（用户 2026-10-08 定的链）：

      1. 半成品包里的 `<编号>_定版预览` —— 用户点名的那张合成图
      2. 成品包里套成品时留下的预览
      3. 半成品包里其他成品类预览（「字幕预览」是设计稿，不算）
      都没有 → 返回 None，由调用方拿素材首帧自己合成

    返回 (源路径, 类型, 来源包)。
    """
    for pkg in pkgs:
        folder = os.path.join(pkg, "字幕夹")
        if not os.path.isdir(folder):
            continue
        for n in sorted(os.listdir(folder)):
            if n.lower().endswith(".png") and "定版预览" in n:
                return os.path.join(folder, n), "定版预览", pkg
    for fin in find_finished({code, pkg_code}, days):
        for n in sorted(os.listdir(fin)):
            if n.lower().endswith(".png") and "预览" in n:
                return os.path.join(fin, n), "成品包留下", fin
    for pkg in pkgs:
        folder = os.path.join(pkg, "字幕夹")
        if not os.path.isdir(folder):
            continue
        for n in sorted(os.listdir(folder)):
            if n.lower().endswith(".png") and 1 <= preview_rank(n) <= len(PREVIEW_RANKS) - 2:
                return os.path.join(folder, n), "包内成品预览", pkg
    return None, None, None


def videos_in(folder):
    found = []
    for root, _, files in os.walk(folder):
        for n in files:
            if os.path.splitext(n)[1].lower() in VIDEO_EXT:
                found.append(os.path.join(root, n))
    return sorted(found)


def material_dir(pkg):
    """包内 `flow素材*` 里视频最多的那个目录。"""
    best, best_n = None, 0
    for name in sorted(os.listdir(pkg)):
        p = os.path.join(pkg, name)
        if os.path.isdir(p) and (name.lower().startswith("flow") or "素材" in name):
            n = len(videos_in(p))
            if n > best_n:
                best, best_n = p, n
    return best


def pick_material_video(pkgs):
    """取一条素材视频当合成预览的底（按文件名排序取第一条，保证可复算）。"""
    for pkg in pkgs:
        d = material_dir(pkg)
        if d:
            vids = videos_in(d)
            if vids:
                return vids[0]
    return None


def synth_preview(video, layer_path, dst):
    """预览图 ≈ 成品首帧：取素材 1 秒处那一帧当底，把定版字幕套上去。"""
    w, h = CANVAS
    tmp = dst + ".frame.png"
    subprocess.run(
        [FFMPEG, "-v", "error", "-ss", "1", "-i", video, "-frames:v", "1",
         "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (w, h, w, h),
         "-y", tmp], check=True)
    base = Image.open(tmp).convert("RGB")
    layer = Image.open(layer_path).convert("RGBA").resize(CANVAS, Image.LANCZOS)
    base.paste(layer, (0, 0), layer)
    base.save(dst, "PNG", optimize=True)
    os.remove(tmp)
    return dst


def collect(days):
    """扫批次 → 按版本编号聚合。同编号跨批次哈希相同则合并。"""
    versions = {}
    for day in days:
        d = os.path.join(SEMI, day)
        if not os.path.isdir(d):
            print("  跳过（不存在）：%s" % d)
            continue
        for pkgname in sorted(os.listdir(d)):
            pkg = os.path.join(d, pkgname)
            if not os.path.isdir(pkg) or "暂存" in pkgname or "中转" in pkgname:
                continue
            entry = scan_package(pkg)
            if not entry:
                continue
            code = bare_code(pkgname)
            if not code:
                print("  跳过（认不出编号）：%s" % pkgname[:40])
                continue
            versions.setdefault(code, []).append({
                "code": code, "day": day, "pkg": pkg, "pkgname": pkgname,
                "candidates": [i for i in entry["items"] if i["transparent"]],
                "effects": [i for i in entry["items"] if not i["transparent"]],
                "locked": entry["locked"],
                "has_json": entry["locked"] is not None,
            })
    return versions


# ---------- 出图 ----------

def make_preview(src, dst):
    """定版叠在深灰底上，按 720x1280 成品画布等比适配。"""
    layer = Image.open(src).convert("RGBA")
    w, h = CANVAS
    sc = min(w / layer.width, h / layer.height)
    layer = layer.resize((max(1, round(layer.width * sc)),
                          max(1, round(layer.height * sc))), Image.LANCZOS)
    bg = Image.new("RGB", CANVAS, BACKDROP)
    bg.paste(layer, ((w - layer.width) // 2, (h - layer.height) // 2), layer)
    bg.save(dst, "PNG", optimize=True)


def make_sheet(entries, dst):
    """矩阵式接触印相：每格裁到字幕实际范围，否则字太小看不清。"""
    cols, cw, ch = 5, 240, 200
    pad, lab = 12, 46
    rows = (len(entries) + cols - 1) // cols
    W = pad + cols * (cw + pad)
    H = pad + rows * (ch + lab + pad)
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    f_code, f_meta = font(20), font(13)

    for i, e in enumerate(entries):
        r, c = divmod(i, cols)
        x = pad + c * (cw + pad)
        y = pad + r * (ch + lab + pad)
        dr.rectangle([x, y, x + cw, y + ch], fill=BACKDROP)
        layer = Image.open(e["definitive"]).convert("RGBA")
        bbox = layer.split()[3].getbbox()
        if bbox:
            layer = layer.crop(bbox)
        sc = min((cw - 16) / layer.width, (ch - 16) / layer.height, 1.0)
        thumb = layer.resize((max(1, round(layer.width * sc)),
                              max(1, round(layer.height * sc))), Image.LANCZOS)
        cell = Image.new("RGB", (cw, ch), BACKDROP)
        cell.paste(thumb, ((cw - thumb.width) // 2, (ch - thumb.height) // 2), thumb)
        sheet.paste(cell, (x, y))
        mark = {"已证实": "● 已证实", "已回填": "◐ 已回填"}.get(e["confidence"], "○ 推断")
        color = {"已证实": (140, 230, 160), "已回填": (150, 190, 240)}.get(
            e["confidence"], (240, 200, 120))
        dr.text((x + 2, y + ch + 4), e["code"], font=f_code, fill=(240, 240, 240))
        dr.text((x + 2, y + ch + 28), "%s · %s" % (mark, "/".join(e["dates"])),
                font=f_meta, fill=color)
    sheet.save(dst, "PNG", optimize=True)
    return W, H


def make_site(entries, lib, days=DEFAULT_DAYS):
    """data.js 用 script 标签加载——file:// 下 fetch 会被 CORS 挡，script 不会。

    页面模板独立成同目录的 page.html：改版只动它，不必碰生成器。
    """
    payload = {"built": _dt.datetime.now().isoformat(timespec="seconds"),
               "scope": list(days),
               "versions": {e["code"]: e for e in entries}}
    with open(os.path.join(lib, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.SUBLIB = " + json.dumps(payload, ensure_ascii=False) + ";")
    with open(os.path.join(lib, "page.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(lib, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


# ---------- 主流程 ----------

def find(code, index_path):
    if not os.path.exists(index_path):
        print("STOP 索引不存在，先跑一次不带参数的 build_index.py", file=sys.stderr)
        return 2
    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)
    want = code.strip().upper()
    hits = [v for k, v in idx["versions"].items()
            if k.upper() == want or want in [a.upper() for a in v.get("aliases", [])]]
    if not hits:
        near = [k for k in idx["versions"] if want in k.upper()]
        print("没找到 %s。%s" % (code, "相近的：" + "、".join(near) if near else ""))
        return 1
    for v in hits:
        print("版本  : %s" % v["code"])
        if v.get("aliases"):
            print("别名  : %s（半成品包名里的编号，也认）" % "、".join(v["aliases"]))
        print("定版  : %s" % v["definitive_abs"])
        print("哈希  : %s" % v["sha256"])
        print("尺寸  : %dx%d" % (v["size"][0], v["size"][1]))
        print("凭据  : %s（%s）" % (v["confidence"], v["basis"]))
        print("来源  : %s" % " | ".join(v["src_packages"]))
        print("预览  : %s" % v["preview_abs"])
        if v["contested"]:
            print("⚠ 注意: 同编号下还发现 %d 个不同哈希的候选（未采用）：%s"
                  % (len(v["discarded"]), "、".join(d["file"] for d in v["discarded"])))
    return 0


def backfill(entries):
    """把资源库裁定出的定版哈希回填进半成品包字幕夹。

    写进去的是**复盘结论**，不是用户当次确认——所以文件里带 Backfilled 标记，
    库读到它会标「已回填」而不是「已证实」。以后任何 Agent 都不用再猜，
    但也不会把推断当成事实。
    """
    n = 0
    for e in entries:
        if e["confidence"] != "推断":       # 已有原生记录的包不碰，免得给人家添乱
            continue
        payload = {
            "SHA256": e["sha256"],
            "Source": os.path.basename(e["src_file"]),
            "Size": "%dx%d" % (e["size"][0], e["size"][1]),
            "Basis": e["basis"],
            "Backfilled": True,
            "BackfilledBy": "0. 字幕资源库/build_index.py --backfill",
            "BackfilledAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "Note": "复盘回填：哈希取自字幕资源库的裁定结果，非用户当次确认",
        }
        for pkg in e["src_packages"]:
            folder = os.path.join(pkg, "字幕夹")
            if not os.path.isdir(folder):
                continue
            with open(os.path.join(folder, BACKFILL_NAME), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=list(DEFAULT_DAYS))
    ap.add_argument("--find", help="查一个版本编号，返回定版路径与哈希")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的库")
    ap.add_argument("--backfill", action="store_true",
                    help="把定版哈希回填进各半成品包字幕夹（写 %s）" % BACKFILL_NAME)
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")

    index_path = os.path.join(LIB, "INDEX.json")
    if args.find:
        return find(args.find, index_path)

    if os.path.exists(index_path) and not args.force:
        print("STOP 资源库已建过：%s\n     要重建加 --force（只会重写库内文件，不碰半成品包）" % LIB,
              file=sys.stderr)
        return 2

    print("扫描批次：%s" % "、".join(args.days))
    versions = collect(args.days)
    if not versions:
        print("STOP 没扫到任何带字幕夹的包", file=sys.stderr)
        return 2

    os.makedirs(STAGE, exist_ok=True)
    entries, problems = [], []
    used = set()
    for pkg_code in sorted(versions):
        recs = versions[pkg_code]
        r, c, basis, conf, losers = adjudicate(recs)
        if not c:
            problems.append((pkg_code, basis))
            continue
        code = code_from_file(os.path.basename(c["path"])) or pkg_code
        if code in used:                       # 撞号就退回包名，别让两张字幕同名
            code = pkg_code
        used.add(code)
        dst = os.path.join(STAGE, code + ".png")
        shutil.copy2(c["path"], dst)
        if sha256(dst) != c["sha256"]:
            print("STOP 拷贝后哈希不一致：%s" % dst, file=sys.stderr)
            return 2
        prev = os.path.join(STAGE, code + "_预览.png")
        real = [(x, y) for x, y in losers
                if not is_derivative(c["path"], y["path"])]
        pkgs = [rec["pkg"] for rec in recs
                if any(x["sha256"] == c["sha256"] for x in rec["candidates"])]
        pv_src, pv_kind, pv_from = pick_preview(code, pkg_code, pkgs, args.days)
        if pv_src:
            shutil.copy2(pv_src, prev)
        else:
            vid = pick_material_video(pkgs)
            if vid:
                synth_preview(vid, dst, prev)
                pv_kind, pv_from = "自制（素材首帧+定版）", vid
            else:
                make_preview(dst, prev)
                pv_kind, pv_from = "自制（深灰底兜底）", None
        copy_of = None
        for pk in pkgs:
            copy_of = read_copy(pk)
            if copy_of and copy_of.get("lines"):
                copy_of["pkg"] = pk
                break
        entries.append({
            "code": code,
            "pkg_code": pkg_code,
            "aliases": [pkg_code] if pkg_code != code else [],
            "dates": sorted({rec["day"] for rec in recs}),
            "src_packages": pkgs,
            "src_file": c["path"],
            "definitive": dst, "definitive_abs": dst,
            "layer_rel": "定版/" + code + ".png",
            "preview_rel": "定版/" + code + "_预览.png",
            "preview_abs": prev,
            "preview_kind": pv_kind,
            "preview_from": pv_from,
            "sha256": c["sha256"],
            "size": c["size"],
            "basis": basis,
            "confidence": conf,
            "contested": bool(real),
            "discarded": [{"sha256": y["sha256"], "file": y["file"],
                           "pkg": x["pkg"], "day": x["day"]} for x, y in real],
            "copy": copy_of,
        })

    if args.backfill:
        n = backfill(entries)
        for e in entries:
            if e["confidence"] == "推断":
                e["confidence"] = "已回填"
        print("回填  : 写入 %d 个半成品包字幕夹（%s）" % (n, BACKFILL_NAME))

    entries.sort(key=lambda e: e["code"])
    sheet = os.path.join(LIB, "总览.png")
    W, H = make_sheet(entries, sheet)
    make_site(entries, LIB, args.days)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"built": _dt.datetime.now().isoformat(timespec="seconds"),
                   "scope": args.days,
                   "versions": {e["code"]: e for e in entries}},
                  f, ensure_ascii=False, indent=1)

    tally = {}
    for e in entries:
        tally[e["confidence"]] = tally.get(e["confidence"], 0) + 1
    print("\n版本  : %d 个（%s）" % (len(entries),
          " / ".join("%s %d" % (k, tally[k]) for k in ("已证实", "已回填", "推断") if k in tally)))
    for e in entries:
        flag = " ⚠ 有被弃候选" if e["contested"] else ""
        print("   %-10s %-6s %-10s %s%s" % (e["code"], e["confidence"],
              "%dx%d" % (e["size"][0], e["size"][1]), e["sha256"][:12], flag))
    if problems:
        print("\n判不了定的包（未入库，需人工确认）：")
        for code, why in problems:
            print("   %s — %s" % (code, why))
    print("\n库    : %s" % LIB)
    print("总览  : %s  (%dx%d)" % (sheet, W, H))
    print("网页  : %s  （双击打开，每 15 秒自己刷新）" % os.path.join(LIB, "index.html"))
    ncopy = sum(1 for e in entries if e.get("copy") and e["copy"].get("lines"))
    print("文案  : %d/%d 个版本取到了文案" % (ncopy, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
