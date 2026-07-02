"""
ast_nodes.py — 抽象構文木 (AST) のノード定義
============================================

構文解析器 (parser.py) が生成し、意味解析器 (analyzer.py) が型注釈を
書き込み、IR 生成器 (irgen.py) が消費するデータ構造。

設計方針:
- すべて dataclass。ノードは基本的にイミュータブルに使うが、
  意味解析器だけは式ノードの `ty` フィールド (推論された型) を書き込む。
- 各ノードは `pos` (SourcePos) を持ち、後段のエラー報告に使う。
- 「文」(Stmt) と「式」(Expr) を分ける。BASIC には式文がほぼ無く
  (CALL 文のみ)、文は行構造に強く結び付いている。

型の表現 (Type) もここで定義する。NBASIC-21 の型は 3 つだけ:
    INTEGER (64bit 符号付き整数) / DOUBLE (IEEE754 倍精度) / STRING
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from .errors import SourcePos


# --------------------------------------------------------------------------
# 型
# --------------------------------------------------------------------------

class Type(Enum):
    """NBASIC-21 のスカラー型。IR とバックエンドでも同じ列挙を使い回す。"""
    INTEGER = "INTEGER"   # 64bit 符号付き整数 (C の int64_t)
    DOUBLE = "DOUBLE"     # IEEE754 倍精度 (C の double)
    STRING = "STRING"     # イミュータブルなヒープ文字列 (ランタイム管理)

    def __str__(self) -> str:
        return self.value


# 型サフィックス文字 → 型 の対応 (仕様書 §3.2)。
# `!` は古典 BASIC の単精度だが、NBASIC-21 では倍精度に統合している。
SUFFIX_TYPES = {
    "%": Type.INTEGER,
    "#": Type.DOUBLE,
    "!": Type.DOUBLE,
    "$": Type.STRING,
}


def type_from_name(name: str) -> Type | None:
    """変数名の型サフィックスから型を決める。サフィックスが無ければ None。"""
    return SUFFIX_TYPES.get(name[-1]) if name else None


# --------------------------------------------------------------------------
# 式ノード
# --------------------------------------------------------------------------

@dataclass
class Expr:
    """全ての式ノードの基底。

    ty は意味解析器が書き込む「この式の評価結果の型」。
    構文解析直後は None であり、意味解析を通った AST では必ず埋まっている。
    """
    pos: SourcePos
    ty: Type | None = field(default=None, init=False, compare=False)


@dataclass
class NumLit(Expr):
    """数値リテラル。value が int なら INTEGER、float なら DOUBLE。"""
    value: object = 0


@dataclass
class StrLit(Expr):
    """文字列リテラル。"""
    value: str = ""


@dataclass
class VarRef(Expr):
    """スカラー変数の参照。name は大文字正規化済み・サフィックス込み。"""
    name: str = ""


@dataclass
class IndexOrCall(Expr):
    """`名前(引数, ...)` の形。

    BASIC では配列アクセス A(3) と関数呼び出し F(3) が構文上区別できない。
    構文解析器はこの曖昧なノードを作り、意味解析器が記号表を引いて
    ArrayRef か FuncCall に置き換える (analyzer.py 参照)。
    """
    name: str = ""
    args: list[Expr] = field(default_factory=list)


@dataclass
class ArrayRef(Expr):
    """配列要素の参照 (意味解析後)。indices は 1 個または 2 個。"""
    name: str = ""
    indices: list[Expr] = field(default_factory=list)


@dataclass
class FuncCall(Expr):
    """関数呼び出し (意味解析後)。

    builtin=True なら組込関数 (LEN, SQR, ...) で、name は組込関数表のキー。
    builtin=False ならユーザー定義 FUNCTION。
    """
    name: str = ""
    args: list[Expr] = field(default_factory=list)
    builtin: bool = False


@dataclass
class BinOp(Expr):
    """二項演算。op は正規化された演算子文字列:
       ^  *  /  \\  MOD  +  -  &  =  <>  <  <=  >  >=  AND  OR  XOR
    """
    op: str = ""
    left: Expr | None = None
    right: Expr | None = None


@dataclass
class UnOp(Expr):
    """単項演算。op は "-" (符号反転) または "NOT" (ビット否定)。"""
    op: str = ""
    operand: Expr | None = None


# --------------------------------------------------------------------------
# 文ノード
# --------------------------------------------------------------------------

@dataclass
class Stmt:
    """全ての文ノードの基底。"""
    pos: SourcePos


@dataclass
class LabelStmt(Stmt):
    """ラベル定義。行番号 (`100 PRINT ...` の 100) と
    名前ラベル (`RETRY:`) を統一的に表す。name は行番号なら "100" のような
    数字列、名前ラベルならその識別子。
    """
    name: str = ""
    is_line_number: bool = False


@dataclass
class AssignStmt(Stmt):
    """代入。target は VarRef / IndexOrCall (→意味解析で ArrayRef になる)。
    LET キーワードの有無は AST では区別しない。
    FUNCTION 内での `関数名 = 式` による戻り値設定もこのノードで表し、
    意味解析器が判別する。
    """
    target: Expr | None = None
    value: Expr | None = None


@dataclass
class PrintItem:
    """PRINT の 1 項目。expr の後ろに続く区切りが sep:
       ";" → 続けて出力 / "," → 次の 14 桁ゾーンへタブ / "" → 項目列の終端
    """
    expr: Expr
    sep: str


@dataclass
class PrintStmt(Stmt):
    """PRINT 文。items が空なら空行を出力。
    trailing_sep が True なら最後の項目に ; か , が付いており、
    改行を出力しない (古典 BASIC のセミコロン継続)。
    """
    items: list[PrintItem] = field(default_factory=list)
    trailing_sep: bool = False


@dataclass
class InputStmt(Stmt):
    """INPUT ["プロンプト" (";"|",")] 変数 [, 変数 ...]
    prompt が None のときは既定のプロンプト "? " を表示する。
    """
    prompt: str | None = None
    targets: list[Expr] = field(default_factory=list)


@dataclass
class IfStmt(Stmt):
    """IF 文。単一行形式もブロック形式も同じノードで表す。

    branches は (条件式, 本体文リスト) の列。先頭が IF、以降が ELSEIF。
    else_body は ELSE 節 (無ければ None)。
    """
    branches: list[tuple[Expr, list[Stmt]]] = field(default_factory=list)
    else_body: list[Stmt] | None = None


@dataclass
class WhileStmt(Stmt):
    """WHILE 条件 ... WEND"""
    cond: Expr | None = None
    body: list[Stmt] = field(default_factory=list)


@dataclass
class DoLoopStmt(Stmt):
    """DO [WHILE|UNTIL 条件] ... LOOP [WHILE|UNTIL 条件]

    pre_cond / post_cond はそれぞれ DO 側 / LOOP 側の条件 (無ければ None)。
    pre_negate / post_negate は UNTIL のとき True (条件を否定して継続判定)。
    両方 None なら無限ループで、EXIT DO で抜ける。
    """
    pre_cond: Expr | None = None
    pre_negate: bool = False
    body: list[Stmt] = field(default_factory=list)
    post_cond: Expr | None = None
    post_negate: bool = False


@dataclass
class ForStmt(Stmt):
    """FOR 変数 = 開始 TO 終了 [STEP 増分] ... NEXT [変数]

    step が None のときは増分 1。NEXT に付いた変数名の一致検査は
    構文解析器が行うので AST には残さない。
    """
    var: VarRef | None = None
    start: Expr | None = None
    end: Expr | None = None
    step: Expr | None = None
    body: list[Stmt] = field(default_factory=list)


@dataclass
class ExitStmt(Stmt):
    """EXIT FOR / EXIT WHILE / EXIT DO / EXIT SUB / EXIT FUNCTION。
    kind は "FOR" / "WHILE" / "DO" / "SUB" / "FUNCTION"。
    """
    kind: str = ""


@dataclass
class GotoStmt(Stmt):
    """GOTO ターゲット。target は行番号文字列またはラベル名。"""
    target: str = ""


@dataclass
class GosubStmt(Stmt):
    """GOSUB ターゲット。"""
    target: str = ""


@dataclass
class ReturnStmt(Stmt):
    """RETURN [式]。

    式なし: GOSUB からの復帰。
    式あり: FUNCTION の戻り値を設定して脱出 (現代的拡張、仕様書 §7.3)。
    """
    value: Expr | None = None


@dataclass
class EndStmt(Stmt):
    """END / STOP。プログラムを終了する。"""


@dataclass
class DimStmt(Stmt):
    """DIM 宣言 1 個分。

    - スカラー宣言 `DIM X AS INTEGER` : dims が空。
    - 配列宣言 `DIM A(10)` `DIM B(N, M) AS STRING` : dims が上限の式リスト。
    elem_type は AS 句で指定された型 (無ければ None → サフィックス/既定で決定)。
    1 つの DIM 文に複数の宣言があれば構文解析器が DimStmt を複数個に分解する。
    """
    name: str = ""
    dims: list[Expr] = field(default_factory=list)
    elem_type: Type | None = None


@dataclass
class ConstStmt(Stmt):
    """CONST 名前 = 定数式。値は意味解析時に畳み込まれる。"""
    name: str = ""
    value: Expr | None = None


@dataclass
class CaseClause:
    """SELECT CASE の 1 節。tests は「照合条件」のリストで、
    各要素は次のいずれかのタプル:
       ("EQ", 式)          — CASE 10        (値の一致)
       ("RANGE", 下限, 上限) — CASE 1 TO 5    (両端を含む範囲)
       ("REL", 演算子, 式)  — CASE IS >= 100 (比較)
    tests が空リストなら CASE ELSE を表す。
    """
    tests: list[tuple]
    body: list["Stmt"]
    pos: SourcePos


@dataclass
class SelectStmt(Stmt):
    """SELECT CASE 式 ... END SELECT"""
    subject: Expr | None = None
    clauses: list[CaseClause] = field(default_factory=list)


@dataclass
class Param:
    """SUB/FUNCTION の仮引数。ty は AS 句 / サフィックス / 既定から決まる。"""
    name: str
    ty: Type
    pos: SourcePos


@dataclass
class ProcDef(Stmt):
    """SUB または FUNCTION の定義。

    is_function : True なら FUNCTION (戻り値あり)
    ret_type    : FUNCTION の戻り値型 (SUB では None)
    プログラム先頭レベルにのみ書ける (入れ子定義は不可)。
    """
    name: str = ""
    params: list[Param] = field(default_factory=list)
    is_function: bool = False
    ret_type: Type | None = None
    body: list[Stmt] = field(default_factory=list)


@dataclass
class CallStmt(Stmt):
    """SUB の呼び出し文。`CALL Foo(1, 2)` と `Foo 1, 2` の両形式。"""
    name: str = ""
    args: list[Expr] = field(default_factory=list)


@dataclass
class DataStmt(Stmt):
    """DATA 定数 [, 定数 ...]。items は文字列化された定数値のリスト。
    (数値も文字列として保持し、READ 側の変数型に応じて実行時に変換する。)
    """
    items: list[str] = field(default_factory=list)


@dataclass
class ReadStmt(Stmt):
    """READ 変数 [, 変数 ...]"""
    targets: list[Expr] = field(default_factory=list)


@dataclass
class RestoreStmt(Stmt):
    """RESTORE [ターゲット]。target が None なら先頭の DATA へ戻す。"""
    target: str | None = None


@dataclass
class RandomizeStmt(Stmt):
    """RANDOMIZE [式]。式が None なら TIMER で種を初期化。"""
    seed: Expr | None = None


@dataclass
class SwapStmt(Stmt):
    """SWAP a, b — 2 つの変数(または配列要素)の値を交換する。"""
    a: Expr | None = None
    b: Expr | None = None


# --------------------------------------------------------------------------
# プログラム全体
# --------------------------------------------------------------------------

@dataclass
class Program:
    """構文解析の最終結果。

    main_body : プログラム先頭レベルの文列 (メインプログラム)
    procs     : SUB/FUNCTION 定義のリスト (出現順)
    構文解析器が先頭レベルの ProcDef を procs へ分離する。
    """
    main_body: list[Stmt]
    procs: list[ProcDef]
