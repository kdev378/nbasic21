"""
driver.py — コンパイラドライバ (パイプラインの結線と CLI)
=========================================================

各ステージ (lexer → parser → analyzer → irgen → optimizer → backend)
を順に呼び出すだけの薄い層。エラー処理と入出力もここで行う。

使い方 (README.md にも記載):

    python3 -m nbasic プログラム.bas                # → プログラム.c
    python3 -m nbasic -t x64 プログラム.bas          # → プログラム.asm
    python3 -m nbasic -O -o out.c プログラム.bas     # 最適化 + 出力名指定
    python3 -m nbasic --emit-ir プログラム.bas       # IR を標準出力へ

その後のビルド:

    C 出力     : cc -O2 プログラム.c runtime/nbrt.c -lm -o プログラム
    x64 出力   : nasm -f win64 プログラム.asm -o プログラム.obj
                 x86_64-w64-mingw32-gcc プログラム.obj runtime/nbrt.c \\
                     -o プログラム.exe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import CompileError
from . import parser as parser_mod
from . import analyzer as analyzer_mod
from . import irgen as irgen_mod
from . import optimizer as optimizer_mod
from . import backend_c
from . import backend_x64
from .ir import IRProgram


def compile_to_ir(source: str, optimize: bool = False) -> IRProgram:
    """フロントエンド + IR 生成 (+ 最適化)。バックエンドの手前まで。"""
    ast = parser_mod.parse(source)          # 字句解析 + 構文解析
    info = analyzer_mod.analyze(ast)        # 意味解析 (AST に型注釈)
    ir = irgen_mod.generate(ast, info)      # 三番地コードへ変換
    if optimize:
        ir = optimizer_mod.optimize(ir)
    return ir


def compile_source(source: str, target: str = "c",
                   optimize: bool = False) -> str:
    """ソース文字列を指定ターゲットのコードに変換する (ライブラリ API)。"""
    ir = compile_to_ir(source, optimize)
    if target == "c":
        return backend_c.generate(ir)
    if target == "x64":
        return backend_x64.generate(ir)
    raise ValueError(f"unknown target: {target}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nbasic",
        description="NBASIC-21 コンパイラ — 行番号付き BASIC を "
                    "C または Windows x64 アセンブリへコンパイルする")
    ap.add_argument("input", help="入力の BASIC ソースファイル (.bas)")
    ap.add_argument("-t", "--target", choices=("c", "x64"), default="c",
                    help="出力ターゲット (既定: c)")
    ap.add_argument("-o", "--output",
                    help="出力ファイル名 (既定: 入力名の拡張子を差し替え)")
    ap.add_argument("-O", "--optimize", action="store_true",
                    help="IR 最適化 (定数畳み込み・死コード除去など) を行う")
    ap.add_argument("--emit-ir", action="store_true",
                    help="コード生成の代わりに IR ダンプを標準出力へ")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    try:
        source = in_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"nbasic: 入力を読めません: {e}", file=sys.stderr)
        return 1

    try:
        if args.emit_ir:
            ir = compile_to_ir(source, args.optimize)
            sys.stdout.write(ir.dump())
            return 0
        code = compile_source(source, args.target, args.optimize)
    except CompileError as e:
        # すべてのユーザー起因エラーは「ファイル:行:桁: メッセージ」形式
        print(e.format(str(in_path)), file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else \
        in_path.with_suffix(".c" if args.target == "c" else ".asm")
    out_path.write_text(code, encoding="utf-8")
    print(f"nbasic: {in_path} -> {out_path} (target={args.target}"
          f"{', optimized' if args.optimize else ''})")
    return 0
