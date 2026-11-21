#!/usr/bin/env python3
"""README.md の「得意レベルの履歴」に、build_table.py が出した history.json の内容を1行追記する。
同じ日付の行が既にあれば置き換える。
使い方: python3 update_readme.py <history.json> [README.md]
"""
import json, sys, re
hist = json.load(open(sys.argv[1], encoding="utf-8"))
path = sys.argv[2] if len(sys.argv) > 2 else "README.md"
text = open(path, encoding="utf-8").read()
HEAD = "## 得意レベルの履歴"
extra = (hist["note"] + "、") if hist.get("note") else ""
line = "- {}: {}（{}掲載 {}件）".format(hist["date"], " / ".join(f"{k} {v}" for k, v in hist["levels"].items()), extra, hist["total"])
if HEAD not in text:
    text = text.rstrip("\n") + f"\n\n{HEAD}\n\n更新するたびに、そのときの得意レベルを記録しています。\n\n"
lines = [x for x in text.rstrip("\n").split("\n") if not x.startswith(f"- {hist['date']}:")]
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n" + line + "\n")
