#!/usr/bin/env python3
"""bmz-player のスコア/ライブラリと BMS-IR のリコメンド推定難易度から、個人用難易度表(header.json/data.json)を作る。
使い方: python3 -I build_table.py <01_Playerのパス> <BMS-IRのdata.json> <出力フォルダ>
BMS-IR のデータは「リコメンド推定 発狂BMS難易度表」の data.json(月1回更新)。
"""
import sqlite3, json, sys, shutil, tempfile, os, collections, datetime, re, random

# ランプの重み(得意レベルの判定用)。FAILED は 0、NOPLAY は数えない
WEIGHT = {"Failed": 0, "LightAssistEasy": 0.25, "Easy": 0.5, "Normal": 0.75, "Hard": 1, "ExHard": 1, "FullCombo": 1, "Perfect": 1, "Max": 1}
MIN_AVG = 0.3        # 平均点がこの値以上の最も高い★を「得意レベル」とする
MAX_PER_LEVEL = 100  # 各レベルの最大曲数
EXCLUDE_CONFIDENCE = {"低"}   # 除外する信頼度
# 得意レベル a に対する★の範囲
WARM = (-3.0, -0.5); FIT = (-0.5, 0.5); CHAL = (0.5, 1.5)

# 表示順。up_* は「今のクリアランプから、1段階上を狙える曲」
LAB = {"warm": "0 ウォーミングアップ", "fit": "1 適正", "chal": "2 挑戦",
       "up_lae": "3 ASSIST EASY→EASY", "up_easy": "4 EASY→NORMAL", "up_normal": "5 NORMAL→HARD"}
UP = {"LightAssistEasy": "up_lae", "Easy": "up_easy", "Normal": "up_normal"}
LAMP_NAME = {None: "未プレイ", "NoPlay": "未プレイ", "Failed": "FAILED", "LightAssistEasy": "ASSIST EASY", "Easy": "EASY", "Normal": "NORMAL"}
# 100件に絞るときの優先順: 未プレイ → FAILED → ASSIST EASY → EASY → NORMAL
LAMP_ORDER = {None: 0, "NoPlay": 0, "Failed": 1, "LightAssistEasy": 2, "Easy": 3, "Normal": 4}

PLAYER, IRFILE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
PAT = re.compile(r"精密推定 ★(-?[\d.]+) / (.+?) / 信頼度 (.+?) / (表内|表外)")

# --- BMS-IR の推定難易度を読む: md5 -> (★, 信頼度) ---
est, skipped = {}, collections.Counter()
for e in json.load(open(IRFILE, encoding="utf-8")):
    m = PAT.search(e.get("comment", ""))
    if m:
        conf = m.group(3)
        if conf in EXCLUDE_CONFIDENCE: skipped["信頼度低"] += 1; continue
        est[e["md5"]] = (float(m.group(1)), conf, e.get("title", ""), e.get("artist", ""))
    else:   # 元の発狂BMS難易度表の譜面: 元のレベルをそのまま★として使う
        try: est[e["md5"]] = (float(e["level"]), "元表", e.get("title", ""), e.get("artist", ""))
        except (ValueError, KeyError): skipped["レベル不明"] += 1

# --- ライブラリとスコアを読む(一時コピーは必ず削除) ---
DATA = os.path.join(PLAYER, "data"); tmp = tempfile.mkdtemp()
try:
    shutil.copy(os.path.join(DATA, "library.db"), tmp)
    sd = os.path.join(DATA, "profiles", "default")
    for f in ("score.db", "score.db-wal", "score.db-shm"):
        if os.path.exists(os.path.join(sd, f)): shutil.copy(os.path.join(sd, f), tmp)
    l = sqlite3.connect(os.path.join(tmp, "library.db")); s = sqlite3.connect(os.path.join(tmp, "score.db"))
    best = dict(s.execute("select chart_sha256, clear_type from score_best"))
    chart = {}   # md5 -> (sha256, title, artist)
    for sh, m, t, a in l.execute("select sha256, md5, title, artist from charts"): chart.setdefault(m, (sh, t, a))
    l.close(); s.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- 得意レベル: 平均点(重み付きクリアランプ)を★に対して単調減少の曲線(等張回帰)で当てはめ、MIN_AVG を下回る手前の★ ---
def isotonic_decreasing(points):
    pts = sorted(points); xs = [x for x, _ in pts]; blocks = []
    for i, (_, y) in enumerate(pts):
        blocks.append([y, 1, [i]])
        while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
            a, b = blocks[-2], blocks[-1]; n = a[1] + b[1]
            blocks[-2:] = [[(a[0] * a[1] + b[0] * b[1]) / n, n, a[2] + b[2]]]
    fit = [0.0] * len(pts)
    for v, _, ix in blocks:
        for i in ix: fit[i] = v
    return xs, fit
def ability(points):
    """曲線が MIN_AVG を下回る境目の★(条件を満たす最後の点と、次の点の中間)"""
    xs, fit = isotonic_decreasing(points)
    last = max((i for i, f in enumerate(fit) if f >= MIN_AVG), default=None)
    if last is None: return None
    return (xs[last] + xs[last + 1]) / 2 if last + 1 < len(xs) else xs[last]
played = [(est[m][0], WEIGHT[best[chart[m][0]]]) for m in est if m in chart and best.get(chart[m][0]) in WEIGHT]
a = ability(played)
random.seed(1); boots = sorted(r for r in (ability([random.choice(played) for _ in played]) for _ in range(300)) if r is not None)
lo, hi = boots[int(len(boots) * .05)], boots[int(len(boots) * .95)]

# --- 譜面の振り分け ---
by_level = collections.defaultdict(list); n_owned = 0
for m, (star, conf, t0, a0) in est.items():
    if m not in chart: continue
    n_owned += 1
    sha, t1, a1 = chart[m]; ct = best.get(sha); d = star - a
    if ct in (None, "NoPlay", "Failed"):
        kind = "warm" if WARM[0] <= d < WARM[1] else "fit" if FIT[0] <= d < FIT[1] else "chal" if CHAL[0] <= d < CHAL[1] else None
    elif ct in UP:
        kind = UP[ct] if d < FIT[1] else None   # クリア済み: 適正の上限までなら、ランプ更新を狙える
    else: kind = None
    if not kind: continue
    e = {"md5": m, "sha256": sha, "title": t0 or t1, "artist": a0 or a1, "level": LAB[kind],
         "comment": f"推定★{star:.1f} / 現在:{LAMP_NAME[ct]}", "url": ""}
    by_level[LAB[kind]].append(((LAMP_ORDER.get(ct, 9), abs(d), e["title"]), e))

data, counts = [], {}
for lab in LAB.values():
    items = sorted(by_level[lab], key=lambda x: x[0])
    counts[lab] = f"{min(len(items), MAX_PER_LEVEL)}/{len(items)}"
    data += [e for _, e in items[:MAX_PER_LEVEL]]
os.makedirs(OUT, exist_ok=True)
json.dump(data, open(os.path.join(OUT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"name": "個人用難易度表", "symbol": "me", "data_url": "data.json", "level_order": list(LAB.values())},
          open(os.path.join(OUT, "header.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# README の「得意レベルの履歴」に追記するための記録(update_readme.py が読む)
jst = datetime.timezone(datetime.timedelta(hours=9))
json.dump({"date": datetime.datetime.now(jst).strftime("%Y-%m-%d"), "levels": {"得意レベル(★)": f"{a:.1f}"},
           "note": f"90%区間 ★{lo:.1f}〜{hi:.1f}", "total": len(data)},
          open(os.path.join(OUT, "history.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"推定付き {len(est)} 譜面(除外 {dict(skipped)})、所持 {n_owned}、プレイ済み {len(played)}")
print(f"得意レベル ★{a:.2f}(90%区間 ★{lo:.2f}〜{hi:.2f})")
print("掲載件数/候補件数:", counts, "計", len(data))
