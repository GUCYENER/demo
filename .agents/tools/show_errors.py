#!/usr/bin/env python3
"""VYRA hata görüntüleyici — logs/errors.jsonl'i okunaklı basar.

Ajanlar/dev için "TEK YERDEN BAK": son hatalar + TAM traceback + request_id.
DB gerekmez (yalnız dosya okur), backend kapalıyken bile çalışır.

Kullanım:
  python .agents/tools/show_errors.py                 # son 10 hata (özet)
  python .agents/tools/show_errors.py -n 30           # son 30
  python .agents/tools/show_errors.py --full          # her hatanın TAM traceback'i
  python .agents/tools/show_errors.py --grep permissions
  python .agents/tools/show_errors.py --request-id abc123def456   # tek kayıt + traceback
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ERRLOG = os.path.normpath(os.path.join(_HERE, "..", "..", "logs", "errors.jsonl"))


def _load(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def main():
    # Windows cp1252 konsolunda Türkçe/Unicode traceback basarken çökmesin
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="VYRA errors.jsonl görüntüleyici (tek yerden bak)")
    ap.add_argument("-n", "--num", type=int, default=10, help="kaç kayıt (varsayılan 10)")
    ap.add_argument("--grep", default=None, help="msg/path/traceback içinde ara")
    ap.add_argument("--request-id", default=None, help="X-Request-ID ile tek kayıt")
    ap.add_argument("--full", action="store_true", help="her kayıt için TAM traceback")
    ap.add_argument("--file", default=_ERRLOG, help=f"varsayılan: {_ERRLOG}")
    args = ap.parse_args()

    rows = _load(args.file)
    if args.request_id:
        rows = [r for r in rows if r.get("request_id") == args.request_id]
        args.full = True
    if args.grep:
        g = args.grep.lower()
        rows = [r for r in rows if g in json.dumps(r, ensure_ascii=False).lower()]
    rows = rows[-args.num:]

    if not rows:
        print(f"(hata kaydı yok — {args.file})")
        return

    print(f"== Son {len(rows)} hata ({args.file}) ==\n")
    for r in rows:
        ts = r.get("ts", "?")
        lvl = r.get("level", "?")
        method = r.get("request_method", "") or ""
        path = r.get("request_path", "") or ""
        status = r.get("response_status", "")
        rid = r.get("request_id", "") or "-"
        msg = r.get("msg", "")
        print(f"[{ts}] {lvl} {method} {path} {status}  req={rid}")
        print(f"    {msg}")
        if args.full:
            tb = r.get("error_detail") or r.get("traceback") or ""
            for ln in tb.splitlines():
                print(f"      {ln}")
        print()

    if not args.full:
        print("(tam traceback için: --full  ·  tek kayıt: --request-id <id>)")


if __name__ == "__main__":
    sys.exit(main())
