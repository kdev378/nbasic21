"""
ir.py — 中間表現 (IR) の定義
============================

NBASIC-21 の IR は「型付き三番地コード (three-address code)」である。
1 命令は高々 1 つの演算しか行わず、結果は必ず「値スロット」に格納される。
制御フローはラベルと (条件付き) ジャンプだけで表現する。

IR の設計方針 (docs/ARCHITECTURE.md §3 に詳細):

1. **値 (Value)** は 5 種類:
     - VReg     : 仮想レジスタ。式の中間結果。**一度しか代入されない**
                  (SSA 風)。この不変条件により最適化器は安全に
                  定数伝播・コピー伝播ができる。
     - VarSlot  : 名前付き変数 (BASIC の変数)。何度でも代入される。
     - IntConst / FloatConst : 数値即値。
     - StrConst : 文字列プール (IRProgram.strings) への添字。

2. **複雑な操作はすべてランタイム呼び出し (call) に落とす**。
   文字列操作・配列アクセス・入出力・べき乗・整数除算 (ゼロ除算検査つき)
   は runtime/nbrt.c の関数を呼ぶ。これによりバックエンドが実装すべき
   命令は「ロード・ストア・整数/浮動小数の四則・比較・分岐・呼び出し」
   だけになり、x86-64 バックエンドが素朴でも正しくなる。

3. **配列はランタイム管理のハンドル (int64 の ID)**。IR とバックエンドは
   配列をただの整数として扱い、確保・添字検査・要素アクセスはすべて
   ランタイム関数が行う。

命令一覧 (op フィールド):
    mov   dest, a          : コピー (型は dest と a で一致済み)
    add   dest, a, b       : 加算   (ty=INTEGER なら整数、DOUBLE なら浮動小数)
    sub   dest, a, b       : 減算
    mul   dest, a, b       : 乗算
    fdiv  dest, a, b       : 浮動小数除算 (整数除算はランタイム呼び出し)
    and/or/xor dest, a, b  : 64bit ビット演算 (BASIC の論理演算子)
    neg   dest, a          : 符号反転 (ty で整数/浮動小数を区別)
    not   dest, a          : ビット否定 (整数のみ)
    itof  dest, a          : INTEGER → DOUBLE 変換
    ftoi  dest, a          : DOUBLE → INTEGER 変換 (最近接偶数丸め)
    cmp   dest, a, b       : 比較。extra に "EQ"/"NE"/"LT"/"LE"/"GT"/"GE"。
                             ty は比較する型 (INTEGER/DOUBLE)。
                             結果は BASIC の真理値 (真=-1, 偽=0) の INTEGER。
    label                  : ジャンプ先。extra にラベル名。
    jmp                    : 無条件ジャンプ。extra にラベル名。
    jz    a                : a == 0 ならジャンプ。extra にラベル名。
    jnz   a                : a != 0 ならジャンプ。extra にラベル名。
    call  [dest], a...     : 関数呼び出し。extra に呼び先シンボル名。
                             dest が None なら戻り値を捨てる。
    ret   [a]              : 関数からの復帰。

ここで「文字列比較」が cmp に無いことに注意 — IR 生成器が
`call nb_str_cmp` + 整数 cmp に分解するので、IR 段階で文字列比較は
存在しない。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from .ast_nodes import Type


# --------------------------------------------------------------------------
# 値
# --------------------------------------------------------------------------

class Value:
    """IR 命令のオペランドになれるものの基底クラス。"""
    __slots__ = ()


@dataclass(frozen=True)
class VReg(Value):
    """仮想レジスタ。IR 生成器が連番で払い出す。一度しか代入されない。"""
    id: int
    ty: Type

    def __str__(self) -> str:
        return f"%{self.id}:{self.ty.value[0]}"


@dataclass(frozen=True)
class VarSlot(Value):
    """名前付き変数スロット。

    name      : 一意化済みの内部名 (バックエンドがそのままシンボル/
                スロット名に使える形。英数字とアンダースコアのみ)
    ty        : スロットの型
    is_global : True ならプログラム全域で共有 (データ領域に置かれる)。
                False なら関数ローカル (スタックフレームに置かれる)。
    """
    name: str
    ty: Type
    is_global: bool = False

    def __str__(self) -> str:
        g = "@" if self.is_global else "$"
        return f"{g}{self.name}:{self.ty.value[0]}"


@dataclass(frozen=True)
class IntConst(Value):
    v: int

    def __str__(self) -> str:
        return str(self.v)


@dataclass(frozen=True)
class FloatConst(Value):
    v: float

    def __str__(self) -> str:
        return repr(self.v)


@dataclass(frozen=True)
class StrConst(Value):
    """文字列プール (IRProgram.strings) の添字。"""
    index: int

    def __str__(self) -> str:
        return f"str#{self.index}"


def value_type(v: Value) -> Type:
    """任意の Value の型を返す。バックエンドが多用するヘルパ。"""
    if isinstance(v, (VReg, VarSlot)):
        return v.ty
    if isinstance(v, IntConst):
        return Type.INTEGER
    if isinstance(v, FloatConst):
        return Type.DOUBLE
    if isinstance(v, StrConst):
        return Type.STRING
    raise AssertionError(f"unknown value {v!r}")


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------

@dataclass
class Ins:
    """IR 命令 1 個。

    op    : 命令名 (モジュール先頭のコメント参照)
    ty    : 演算の型 (算術・比較・変換で使用。それ以外は None)
    dest  : 結果の格納先 (VReg または VarSlot)。結果が無い命令は None
    args  : オペランドのタプル
    extra : 命令ごとの追加情報 —
              label/jmp/jz/jnz : ラベル名 (str)
              call             : 呼び先シンボル名 (str)
              cmp              : 比較の種類 "EQ"|"NE"|"LT"|"LE"|"GT"|"GE"
    """
    op: str
    ty: Type | None = None
    dest: Value | None = None
    args: tuple = ()
    extra: object = None

    def __str__(self) -> str:
        """人間が読むためのダンプ形式 (--emit-ir で使用)。"""
        if self.op == "label":
            return f"{self.extra}:"
        parts = [self.op]
        if self.ty is not None:
            parts.append(f".{self.ty.value[0].lower()}")
        head = "".join(parts)
        if self.op == "cmp":
            head += f".{str(self.extra).lower()}"
        operands = []
        if self.dest is not None:
            operands.append(str(self.dest))
        operands.extend(str(a) for a in self.args)
        s = f"    {head} " + ", ".join(operands)
        if self.op in ("jmp", "jz", "jnz"):
            s += f" -> {self.extra}"
        if self.op == "call":
            s += f" [{self.extra}]"
        return s


# --------------------------------------------------------------------------
# 関数とプログラム
# --------------------------------------------------------------------------

@dataclass
class IRFunc:
    """IR レベルの関数。メインプログラムも 1 個の関数 (nb_basic_main)。

    name    : 出力シンボル名 (マングリング済み。irgen.mangle 参照)
    params  : 仮引数のスロット列 (関数ローカル)
    ret_ty  : 戻り値型 (無ければ None)
    body    : 命令列
    """
    name: str
    params: list[VarSlot] = field(default_factory=list)
    ret_ty: Type | None = None
    body: list[Ins] = field(default_factory=list)

    def local_slots(self) -> list[VarSlot]:
        """本体に現れるローカル VarSlot を出現順・重複なしで列挙する。
        バックエンドがフレーム割り付け/ローカル宣言に使う。
        仮引数は含まない。"""
        seen: dict[VarSlot, None] = {}
        params = set(self.params)
        for ins in self.body:
            for v in (ins.dest, *ins.args):
                if isinstance(v, VarSlot) and not v.is_global and v not in params:
                    seen.setdefault(v, None)
        return list(seen)

    def vregs(self) -> list[VReg]:
        """本体に現れる仮想レジスタを列挙する (スロット割り付け用)。"""
        seen: dict[VReg, None] = {}
        for ins in self.body:
            for v in (ins.dest, *ins.args):
                if isinstance(v, VReg):
                    seen.setdefault(v, None)
        return list(seen)


@dataclass
class IRProgram:
    """コンパイル単位全体の IR。

    strings    : 文字列プール。StrConst.index が指す実体。
    data_items : DATA 文の項目 (文字列表現)。実行時に nb_read_* が消費する。
    globals    : 大域変数スロットの一覧 (初期化はコード側で行う)。
    funcs      : 関数リスト。先頭は必ずメイン (nb_basic_main)。
    """
    strings: list[str] = field(default_factory=list)
    data_items: list[str] = field(default_factory=list)
    globals: list[VarSlot] = field(default_factory=list)
    funcs: list[IRFunc] = field(default_factory=list)

    def intern_string(self, s: str) -> StrConst:
        """文字列をプールに登録して StrConst を返す。同じ内容は共有する。"""
        try:
            return StrConst(self.strings.index(s))
        except ValueError:
            self.strings.append(s)
            return StrConst(len(self.strings) - 1)

    def dump(self) -> str:
        """--emit-ir 用の人間可読ダンプ。"""
        lines: list[str] = []
        for i, s in enumerate(self.strings):
            lines.append(f"str#{i} = {s!r}")
        for i, d in enumerate(self.data_items):
            lines.append(f"data#{i} = {d!r}")
        for g in self.globals:
            lines.append(f"global {g}")
        for f in self.funcs:
            params = ", ".join(str(p) for p in f.params)
            ret = f" -> {f.ret_ty}" if f.ret_ty else ""
            lines.append(f"\nfunc {f.name}({params}){ret} {{")
            lines.extend(str(ins) for ins in f.body)
            lines.append("}")
        return "\n".join(lines) + "\n"
