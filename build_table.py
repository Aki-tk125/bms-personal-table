#!/usr/bin/env python3
"""bmz-player のスコア/ライブラリから個人用難易度表(header.json/data.json)を作る。
使い方: python3 -I build_table.py <01_Playerのパス> <出力フォルダ>
"""
import sqlite3, json, sys, shutil, tempfile, os, collections
DATA = os.path.join(sys.argv[1], "data"); OUT = sys.argv[2]
SRC = {"Satellite": 7, "発狂BMS": 2, "NG発狂": 3}   # 基準にする表(名前, library.db の table id)
FOLLOW = {"Stella": "Satellite"}   # 自分でレベル判定できない表は、指定の表の得意レベル値を目安にする
CLEARED = {"LightAssistEasy","Easy","Normal","Hard","ExHard","FullCombo","Perfect","Max"}
tmp = tempfile.mkdtemp()
for f in ("library.db",):
    shutil.copy(os.path.join(DATA, f), tmp)
sd = os.path.join(DATA, "profiles", "default")
for f in ("score.db", "score.db-wal", "score.db-shm"):
    if os.path.exists(os.path.join(sd, f)): shutil.copy(os.path.join(sd, f), tmp)
l = sqlite3.connect(os.path.join(tmp, "library.db")); s = sqlite3.connect(os.path.join(tmp, "score.db"))

best = {}
for sh, ct in s.execute("select chart_sha256, clear_type from score_best"):
    best[sh] = ct
chart = {}   # md5 -> (sha256, title, artist)
for sh, m, t, a in l.execute("select sha256, md5, title, artist from charts"):
    chart.setdefault(m, (sh, t, a))

LAB = {"fit": "1 適正", "chal": "2 挑戦"}
abil = {}
cands = {}   # md5 -> (rank, entry)
report = []
for name, tid in SRC.items():
    sym, lo = l.execute("select symbol, level_order from difficulty_tables where id=?", (tid,)).fetchone()
    order = json.loads(lo); idx = {v: i for i, v in enumerate(order)}
    ents = l.execute("select level, md5, sha256, title, artist, url from difficulty_table_entries where table_id=?", (tid,)).fetchall()
    st = collections.defaultdict(lambda: [0, 0])   # idx -> [played, cleared]
    for lv, m, _, _, _, _ in ents:
        if m in chart and chart[m][0] in best and best[chart[m][0]] != "NoPlay" and lv in idx:
            st[idx[lv]][0] += 1; st[idx[lv]][1] += best[chart[m][0]] in CLEARED
    ab = max([i for i, (p, c) in st.items() if p >= 5 and c / p >= 0.5], default=None)
    if ab is None and name in FOLLOW and FOLLOW[name] in abil and abil[FOLLOW[name]] in order:
        ab = idx[abil[FOLLOW[name]]]; report.append(f"{name}: 判定不可のため {FOLLOW[name]} の得意レベル値を使用")
    if ab is not None: abil[name] = order[ab]
    report.append(f"{name}: 得意レベル = {order[ab] if ab is not None else '判定不可'}")
    if ab is None: continue
    for lv, m, sh, t, a, url in ents:
        if m not in chart or lv not in idx: continue
        d = idx[lv] - ab
        ct = best.get(chart[m][0])
        if ct in CLEARED: continue
        kind = "fit" if d == 0 else "chal" if d == 1 else None   # 未プレイ・失敗済みの区別なく、適正と挑戦のみ
        if not kind: continue
        rank = (list(LAB).index(kind), abs(d))
        e = {"md5": m, "sha256": chart[m][0], "title": t or chart[m][1], "artist": a or chart[m][2],
             "level": LAB[kind], "comment": f"{sym}{lv}", "url": url or ""}
        if m not in cands or rank < cands[m][0]: cands[m] = (rank, e)

data = [e for _, e in sorted(cands.values(), key=lambda x: (x[0], x[1]["comment"]))]
os.makedirs(OUT, exist_ok=True)
json.dump(data, open(os.path.join(OUT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"name": "個人用難易度表", "symbol": "me", "data_url": "data.json", "level_order": list(LAB.values())},
          open(os.path.join(OUT, "header.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(report)); print("件数:", {LAB[k]: sum(e['level'] == LAB[k] for e in data) for k in LAB}, "計", len(data))
