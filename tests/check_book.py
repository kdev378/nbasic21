#!/usr/bin/env python3
"""
check_book.py — 教科書 (docs/book/) のコード例を全数検査する
=============================================================

教科書の信頼性はコード例が「本当に動く」ことにかかっている。
このスクリプトは全章の Markdown から ```basic フェンスのコード
ブロックを抽出し、コンパイラの --check (エラー検査) にかける。

規約:
- ```basic ブロックは「完全なプログラム」— そのままコンパイルが
  通らなければならない。
- 意図的な断片・エラー例は、ブロックの最初の行に
  「これは断片です」または「わざと間違えている」を含むコメントを
  置く。それらは検査対象から除外される (読者への表示も兼ねる)。

使い方:
    python3 tests/check_book.py          # 全章検査
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "docs" / "book"

# 検査から除外するブロックの目印 (ブロック先頭行に含まれる文言)
SKIP_MARKERS = ("これは断片", "わざと間違えている")

FENCE_RE = re.compile(r"^```basic\s*$(.*?)^```\s*$",
                      re.MULTILINE | re.DOTALL)


def extract_blocks(md_path: Path) -> list[tuple[int, str]]:
    """(開始行番号, コード) のリストを返す。"""
    text = md_path.read_text(encoding="utf-8")
    blocks = []
    for m in FENCE_RE.finditer(text):
        line_no = text[:m.start()].count("\n") + 2  # コードの先頭行
        blocks.append((line_no, m.group(1)))
    return blocks


def main() -> int:
    n_checked = 0
    n_skipped = 0
    failures: list[str] = []

    md_files = sorted(BOOK.glob("*.md"))
    if not md_files:
        print("docs/book/ に Markdown がありません", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "block.bas"
        for md in md_files:
            for line_no, code in extract_blocks(md):
                first = code.strip().splitlines()[0] if code.strip() else ""
                if any(mark in first for mark in SKIP_MARKERS):
                    n_skipped += 1
                    continue
                src.write_text(code, encoding="utf-8")
                p = subprocess.run(
                    [sys.executable, "-m", "nbasic", "--check", str(src)],
                    capture_output=True, text=True, cwd=ROOT)
                n_checked += 1
                if p.returncode != 0:
                    failures.append(
                        f"{md.name}:{line_no}: {p.stderr.strip()}\n"
                        f"    先頭行: {first[:60]}")

    print(f"教科書コード検査: {n_checked} ブロック検査 / "
          f"{n_skipped} ブロック除外 (断片)")
    if failures:
        print(f"\n{len(failures)} 個のブロックが不合格:")
        for f in failures:
            print("  " + f)
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    sys.exit(main())
