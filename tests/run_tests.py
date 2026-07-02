#!/usr/bin/env python3
"""
run_tests.py — NBASIC-21 コンパイラの統合テストランナー
=======================================================

テスト戦略は docs/ARCHITECTURE.md §8 を参照。3 種類のテストを行う:

1. ゴールデンテスト
   examples/ と tests/cases/ の各 .bas を C バックエンドでビルド・実行し、
   tests/expected/<名前>.out と比較する。-O あり/なしの両方を走らせる。
   <名前>.in があれば標準入力として与える。

2. クロス検証 (ツールが揃っている場合のみ)
   同じプログラムを x64 バックエンド (NASM/Win64) でビルドし、wine で
   実行して同一の出力になることを確認する。Windows の改行 (CRLF) は
   比較前に LF へ正規化する。

3. エラーテスト
   コンパイルエラー・実行時エラーが正しく報告されることを、本ファイル
   内蔵のソース断片で確認する。

使い方:
    python3 tests/run_tests.py             # 全部 (ツールは自動検出)
    python3 tests/run_tests.py --no-x64    # x64 クロス検証を省略
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
EXPECTED = ROOT / "tests" / "expected"

# 統計
n_pass = 0
n_fail = 0


def report(name: str, ok: bool, detail: str = "") -> None:
    global n_pass, n_fail
    if ok:
        n_pass += 1
        print(f"  PASS  {name}")
    else:
        n_fail += 1
        print(f"  FAIL  {name}")
        if detail:
            for line in detail.splitlines()[:15]:
                print(f"        | {line}")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def compile_bas(src: Path, target: str, out: Path,
                optimize: bool) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "nbasic", "-t", target, "-o", str(out),
           str(src)]
    if optimize:
        cmd.insert(3, "-O")
    return run(cmd, cwd=ROOT)


def find_tools() -> dict[str, str | None]:
    return {
        "cc": shutil.which("cc") or shutil.which("gcc"),
        "nasm": shutil.which("nasm"),
        "mingw": shutil.which("x86_64-w64-mingw32-gcc"),
        "wine": shutil.which("wine"),
    }


# ----------------------------------------------------------------------
# 1 + 2: ゴールデンテストとクロス検証
# ----------------------------------------------------------------------

def golden_tests(tools: dict, do_x64: bool) -> None:
    cases = sorted((ROOT / "examples").glob("*.bas")) \
        + sorted((ROOT / "tests" / "cases").glob("*.bas"))
    print(f"== ゴールデンテスト ({len(cases)} ケース) ==")

    for src in cases:
        expected_file = EXPECTED / (src.stem + ".out")
        stdin_file = src.with_suffix(".in")
        stdin_text = stdin_file.read_text() if stdin_file.exists() else ""
        if not expected_file.exists():
            report(src.name, False, "期待出力ファイルがありません: "
                   f"{expected_file}")
            continue
        expected = expected_file.read_text()

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # ---- C バックエンド (-O なし / あり) ----
            for opt in (False, True):
                tag = f"{src.name} [c{'/-O' if opt else ''}]"
                c_file = tmp / f"{src.stem}{'_o' if opt else ''}.c"
                exe = tmp / f"{src.stem}{'_o' if opt else ''}"
                p = compile_bas(src, "c", c_file, opt)
                if p.returncode != 0:
                    report(tag, False, p.stderr)
                    continue
                p = run([tools["cc"], "-I", str(RUNTIME), str(c_file),
                         str(RUNTIME / "nbrt.c"), "-lm", "-o", str(exe)])
                if p.returncode != 0:
                    report(tag, False, p.stderr)
                    continue
                p = run([str(exe)], input=stdin_text)
                ok = p.stdout == expected and p.returncode == 0
                report(tag, ok,
                       f"--- expected ---\n{expected}--- actual ---\n"
                       f"{p.stdout}(exit={p.returncode})" if not ok else "")

            # ---- x64 バックエンド (クロス検証) ----
            if not do_x64:
                continue
            for opt in (False, True):
                tag = f"{src.name} [x64{'/-O' if opt else ''}]"
                asm = tmp / f"{src.stem}{'_o' if opt else ''}.asm"
                obj = asm.with_suffix(".obj")
                exe = asm.with_suffix(".exe")
                p = compile_bas(src, "x64", asm, opt)
                if p.returncode != 0:
                    report(tag, False, p.stderr)
                    continue
                p = run([tools["nasm"], "-f", "win64", str(asm),
                         "-o", str(obj)])
                if p.returncode != 0:
                    report(tag, False, p.stderr)
                    continue
                p = run([tools["mingw"], "-I", str(RUNTIME), str(obj),
                         str(RUNTIME / "nbrt.c"), "-o", str(exe)])
                if p.returncode != 0:
                    report(tag, False, p.stderr)
                    continue
                wine_env = dict(os.environ, WINEDEBUG="-all")
                p = run([tools["wine"], str(exe)], input=stdin_text,
                        env=wine_env)
                # Windows のテキスト出力は CRLF なので正規化して比較
                actual = p.stdout.replace("\r\n", "\n")
                ok = actual == expected and p.returncode == 0
                report(tag, ok,
                       f"--- expected ---\n{expected}--- actual ---\n"
                       f"{actual}(exit={p.returncode})" if not ok else "")


# ----------------------------------------------------------------------
# 3: エラーテスト
# ----------------------------------------------------------------------

# (名前, ソース, 期待するメッセージの部分文字列)
COMPILE_ERROR_CASES = [
    ("型不一致の代入", 'X$ = 5\n', "STRING に変換できません"),
    ("NEXT の欠落", 'FOR I = 1 TO 3\nPRINT I\n', "'NEXT' が必要"),
    ("NEXT 変数の不一致", 'FOR I = 1 TO 3\nNEXT J\n', "一致しません"),
    ("未定義ラベルへの GOTO", 'GOTO 999\n', "ありません"),
    ("スコープ外への GOTO",
     'SUB S1\nGOTO 10\nEND SUB\n10 PRINT\n', "ありません"),
    ("重複ラベル", '10 PRINT\n10 PRINT\n', "重複"),
    ("定数への代入", 'CONST K = 1\nK = 2\n', "代入できません"),
    ("CONST の非定数式", 'CONST K = X + 1\n', "定数式"),
    ("引数個数の不一致",
     'SUB P (A%)\nEND SUB\nCALL P(1, 2)\n', "個です"),
    ("SUB を式で呼ぶ",
     'SUB P\nEND SUB\nX = P()\n', "式の中では呼び出せません"),
    ("ループ外の EXIT FOR", 'EXIT FOR\n', "外にあります"),
    ("手続き内の DATA",
     'SUB S1\nDATA 1\nEND SUB\n', "メインプログラムにのみ"),
    ("配列の次元不一致",
     'DIM A(3)\nPRINT A(1, 2)\n', "次元"),
    ("文字列と数値の比較", 'PRINT "A" < 5\n', "比較します"),
    ("組込関数名の再定義",
     'FUNCTION LEN (X$)\nEND FUNCTION\n', "組込関数の名前"),
    ("閉じない文字列", 'PRINT "ABC\n', "閉じていません"),
    ("値付き RETURN が SUB 内",
     'SUB S1\nRETURN 5\nEND SUB\n', "FUNCTION の中でのみ"),
]

# (名前, ソース, 標準入力, 期待する実行時エラーメッセージ)
RUNTIME_ERROR_CASES = [
    ("ゼロ除算 (整数)", 'X% = 0\nPRINT 1 \\ X%\n', "", "Division by zero"),
    ("添字範囲外", 'DIM A(3)\nI% = 4\nA(I%) = 1\n', "",
     "Subscript out of range"),
    ("DIM 前のアクセス",
     'SUB S1\nDIM B(3)\nEND SUB\nDIM A(3)\nGOTO 20\nDIM C(3)\n'
     '20 PRINT C(0)\n', "", "Array used before DIM"),
    ("GOSUB なしの RETURN", 'RETURN\n', "", "RETURN without GOSUB"),
    ("DATA の枯渇", 'READ X\nDATA\n', "", "Out of DATA"),
    ("負数の SQR", 'PRINT SQR(0 - 1)\n', "", "Illegal function call"),
]


def error_tests(tools: dict) -> None:
    print(f"== コンパイルエラーテスト ({len(COMPILE_ERROR_CASES)} ケース) ==")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, source, needle in COMPILE_ERROR_CASES:
            src = tmp / "t.bas"
            src.write_text(source, encoding="utf-8")
            p = compile_bas(src, "c", tmp / "t.c", False)
            ok = p.returncode != 0 and needle in p.stderr
            report(name, ok, p.stderr if not ok else "")

    print(f"== 実行時エラーテスト ({len(RUNTIME_ERROR_CASES)} ケース) ==")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, source, stdin_text, needle in RUNTIME_ERROR_CASES:
            src = tmp / "t.bas"
            src.write_text(source, encoding="utf-8")
            c_file = tmp / "t.c"
            exe = tmp / "t"
            p = compile_bas(src, "c", c_file, False)
            if p.returncode != 0:
                report(name, False, "コンパイル失敗:\n" + p.stderr)
                continue
            p = run([tools["cc"], "-I", str(RUNTIME), str(c_file),
                     str(RUNTIME / "nbrt.c"), "-lm", "-o", str(exe)])
            if p.returncode != 0:
                report(name, False, p.stderr)
                continue
            p = run([str(exe)], input=stdin_text)
            ok = p.returncode == 1 and needle in p.stderr
            report(name, ok,
                   f"exit={p.returncode} stderr={p.stderr!r}"
                   if not ok else "")


# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-x64", action="store_true",
                    help="x64 クロス検証を省略する")
    args = ap.parse_args()

    tools = find_tools()
    if tools["cc"] is None:
        print("エラー: C コンパイラ (cc/gcc) が見つかりません", file=sys.stderr)
        return 2

    do_x64 = not args.no_x64 and all(
        tools[k] for k in ("nasm", "mingw", "wine"))
    if not do_x64:
        print("注意: nasm / x86_64-w64-mingw32-gcc / wine が揃っていないため"
              " x64 クロス検証を省略します")

    golden_tests(tools, do_x64)
    error_tests(tools)

    print()
    print(f"結果: {n_pass} passed, {n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
