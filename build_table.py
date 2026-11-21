#!/usr/bin/env python3
"""bmz-player のスコア/ライブラリから個人用難易度表(header.json/data.json)を作る。
使い方: python3 -I build_table.py <01_Playerのパス> <出力フォルダ>
"""
import sqlite3, json, sys, shutil, tempfile, os, collections, datetime

SRC = {"Satellite": 7, "発狂BMS": 2, "NG発狂": 3}   # 基準にする表(名前, library.db の table id)
FOLLOW = {}   # 自分でレベル判定できない表を、他の表の得意レベルで代用する場合に指定
# ランプの重み(得意レベルの判定用)。FAILED は 0、NOPLAY は数えない
WEIGHT = {"Failed": 0, "LightAssistEasy": 0.25, "Easy": 0.5, "Normal": 0.75, "Hard": 1, "ExHard": 1, "FullCombo": 1, "Perfect": 1, "Max": 1}
MIN_PLAYED = 5      # 判定に必要なプレイ数(レベルごと)
MIN_AVG = 0.3       # このレベルの平均点がこの値以上なら「得意」
MAX_PER_LEVEL = 100 # 各レベルの最大曲数
CLEARED = {"LightAssistEasy", "Easy", "Normal", "Hard", "ExHard", "FullCombo", "Perfect", "Max"}

# 表示順。up_* は「今のクリアランプから、1段階上を狙える曲」
LAB = {"warm": "0 ウォーミングアップ", "fit": "1 適正", "chal": "2 挑戦",
       "up_lae": "3 ASSIST EASY→EASY", "up_easy": "4 EASY→NORMAL", "up_normal": "5 NORMAL→HARD"}
UP = {"LightAssistEasy": "up_lae", "Easy": "up_easy", "Normal": "up_normal"}
PRIORITY = {"fit": 0, "chal": 1, "warm": 2, "up_lae": 3, "up_easy": 3, "up_normal": 3}   # 同じ譜面が複数の表にある場合の優先順
LAMP_NAME = {None: "未プレイ", "NoPlay": "未プレイ", "Failed": "FAILED", "LightAssistEasy": "ASSIST EASY", "Easy": "EASY", "Normal": "NORMAL"}
# 100件に絞るときの優先順: 未プレイ → FAILED → ASSIST EASY → EASY → NORMAL
LAMP_ORDER = {None: 0, "NoPlay": 0, "Failed": 1, "LightAssistEasy": 2, "Easy": 3, "Normal": 4}

DATA = os.path.join(sys.argv[1], "data"); OUT = sys.argv[2]
tmp = tempfile.mkdtemp()
shutil.copy(os.path.join(DATA, "library.db"), tmp)
sd = os.path.join(DATA, "profiles", "default")
for f in ("score.db", "score.db-wal", "score.db-shm"):
    if os.path.exists(os.path.join(sd, f)): shutil.copy(os.path.join(sd, f), tmp)
l = sqlite3.connect(os.path.join(tmp, "library.db")); s = sqlite3.connect(os.path.join(tmp, "score.db"))

best = dict(s.execute("select chart_sha256, clear_type from score_best"))
chart = {}   # md5 -> (sha256, title, artist)
for sh, m, t, a in l.execute("select sha256, md5, title, artist from charts"):
    chart.setdefault(m, (sh, t, a))

cands = {}   # md5 -> (rank, sortkey, entry)
abil = {}
report = []
for name, tid in SRC.items():
    sym, lo = l.execute("select symbol, level_order from difficulty_tables where id=?", (tid,)).fetchone()
    order = json.loads(lo); idx = {v: i for i, v in enumerate(order)}
    ents = l.execute("select level, md5, sha256, title, artist, url from difficulty_table_entries where table_id=?", (tid,)).fetchall()
    st = collections.defaultdict(lambda: [0, 0.0])   # idx -> [played, weight_sum]
    for lv, m, _, _, _, _ in ents:
        if m in chart and chart[m][0] in best and best[chart[m][0]] != "NoPlay" and lv in idx:
            st[idx[lv]][0] += 1; st[idx[lv]][1] += WEIGHT.get(best[chart[m][0]], 0)
    ab = max([i for i, (p, w) in st.items() if p >= MIN_PLAYED and w / p >= MIN_AVG], default=None)
    if ab is None and name in FOLLOW and FOLLOW[name] in abil and abil[FOLLOW[name]] in order:
        ab = idx[abil[FOLLOW[name]]]; report.append(f"{name}: 判定不可のため {FOLLOW[name]} の得意レベル値を使用")
    if ab is not None: abil[name] = order[ab]
    report.append(f"{name}: 得意レベル = {order[ab] if ab is not None else '判定不可'}")
    if ab is None: continue
    for lv, m, sh, t, a, url in ents:
        if m not in chart or lv not in idx: continue
        d = idx[lv] - ab
        ct = best.get(chart[m][0])
        if ct in (None, "NoPlay", "Failed"):      # 未プレイ・失敗済み
            kind = "warm" if -3 <= d <= -1 else "fit" if d == 0 else "chal" if d == 1 else None
        elif ct in UP:                             # クリア済み: 得意レベル以下ならランプ更新を狙える
            kind = UP[ct] if d <= 0 else None
        else:
            kind = None
        if not kind: continue
        rank = (PRIORITY[kind], abs(d))
        e = {"md5": m, "sha256": chart[m][0], "title": t or chart[m][1], "artist": a or chart[m][2],
             "level": LAB[kind], "comment": f"{sym}{lv} / 現在:{LAMP_NAME[ct]}", "url": url or ""}
        sortkey = (LAMP_ORDER.get(ct, 9), abs(d), e["title"])
        if m not in cands or rank < cands[m][0]: cands[m] = (rank, sortkey, e)

by_level = collections.defaultdict(list)
for _, sk, e in cands.values(): by_level[e["level"]].append((sk, e))
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
json.dump({"date": datetime.datetime.now(jst).strftime("%Y-%m-%d"), "levels": abil, "total": len(data)},
          open(os.path.join(OUT, "history.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(report)); print("掲載件数/候補件数:", counts, "計", len(data))
