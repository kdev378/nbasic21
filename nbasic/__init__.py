"""
NBASIC-21 コンパイラパッケージ
==============================

行番号付きの古典 BASIC に現代的な構造化機能を加えた言語「NBASIC-21」の
コンパイラ実装。コンパイルは次のパイプラインで行う:

    ソースコード (.bas)
        │  lexer.py      : 字句解析 (文字列 → トークン列)
        ▼
    トークン列
        │  parser.py     : 構文解析 (トークン列 → 抽象構文木 AST)
        ▼
    AST (ast_nodes.py)
        │  analyzer.py   : 意味解析 (記号表構築・型検査・ラベル解決)
        ▼
    型注釈付き AST
        │  irgen.py      : IR 生成 (AST → 三番地コード)
        ▼
    IR (ir.py)
        │  optimizer.py  : 最適化 (定数畳み込み・コピー伝播・死コード除去)
        ▼
    最適化済み IR
        │  backend_c.py    : C ソース生成      (可搬ターゲット)
        │  backend_x64.py  : x86-64 NASM 生成  (Windows x64 ABI)
        ▼
    出力 (.c / .asm)

各ステージは前段の出力だけに依存する純粋な変換であり、
`driver.py` がこれらを順に呼び出す。
"""

__version__ = "1.0.0"
