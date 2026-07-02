"""
backend_c.py — C バックエンド (IR → 可搬な C ソース)
====================================================

IR を 1 個の C ソースファイルへ変換する。出力は runtime/nbrt.h を
include し、runtime/nbrt.c と一緒にホストの C コンパイラでビルドする:

    cc -O2 out.c runtime/nbrt.c -lm -o program

IR と C の対応は素直そのもの:

    値スロット (VReg / VarSlot) → C のローカル変数 / static 変数
    label / jmp / jz / jnz      → C のラベルと goto
    call                        → C の関数呼び出し
    算術・比較                  → C の式

注意が必要なのは 1 点だけ — **符号付き整数のオーバーフローは C では
未定義動作**なので、加減乗算と符号反転は uint64_t で計算してから
int64_t へ戻す。これにより仕様書 §5.2 の「64bit ラップアラウンド」が
どの C コンパイラでも保証される (2 の補数表現での折り返し)。

型の対応 (nbrt.h の契約と同じ):
    INTEGER → int64_t   DOUBLE → double   STRING → nb_str*
"""

from __future__ import annotations

from .ast_nodes import Type
from .ir import (IRProgram, IRFunc, Ins, VReg, VarSlot,
                 IntConst, FloatConst, StrConst, Value, value_type)

I, D, S = Type.INTEGER, Type.DOUBLE, Type.STRING

# IR の型 → C の型名
_CTYPE = {I: "int64_t", D: "double", S: "nb_str *"}

# 比較種別 → C の演算子
_CMP_OP = {"EQ": "==", "NE": "!=", "LT": "<", "LE": "<=",
           "GT": ">", "GE": ">="}


def _c_escape(s: str) -> str:
    """Python 文字列 (UTF-8 で出力される) を C 文字列リテラルへ。

    印字可能 ASCII はそのまま、それ以外は 8 進エスケープ (\\ooo) を使う。
    16 進エスケープ (\\xNN) は後続の 16 進数字と癒着する罠があるため
    使わない。非 ASCII は UTF-8 バイト列として 8 進で埋め込む。
    """
    out = []
    for b in s.encode("utf-8"):
        c = chr(b)
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif 0x20 <= b < 0x7F:
            out.append(c)
        else:
            out.append(f"\\{b:03o}")
    return '"' + "".join(out) + '"'


def _c_float(v: float) -> str:
    """double を値を失わずに C リテラル化する。repr は往復可能な最短
    表現を返すが、'inf' などは C に無いので特別扱いする。"""
    if v != v:                       # NaN
        return "(0.0/0.0)"
    if v == float("inf"):
        return "(1.0/0.0)"
    if v == float("-inf"):
        return "(-1.0/0.0)"
    text = repr(v)
    # "1.0" はそのまま double リテラル。"1e+300" も OK。
    return text


class CBackend:
    def __init__(self, ir: IRProgram):
        self.ir = ir
        self.lines: list[str] = []

    def _w(self, line: str = "") -> None:
        self.lines.append(line)

    # ------------------------------------------------------------------
    # オペランドの C 式化
    # ------------------------------------------------------------------

    def _val(self, v: Value) -> str:
        if isinstance(v, VReg):
            return f"t{v.id}"
        if isinstance(v, VarSlot):
            return v.name
        if isinstance(v, IntConst):
            # INT64_MIN はリテラルとして直接書けない (9223372036854775808
            # に単項マイナスが付いた式と解釈されるため) ので定数名を使う
            if v.v == -(2 ** 63):
                return "INT64_MIN"
            return f"INT64_C({v.v})"
        if isinstance(v, FloatConst):
            return _c_float(v.v)
        if isinstance(v, StrConst):
            return f"(&nbs_{v.index})"
        raise AssertionError(f"bad value {v!r}")

    # ------------------------------------------------------------------
    # 出力全体
    # ------------------------------------------------------------------

    def generate(self) -> str:
        self._w("/* NBASIC-21 コンパイラが生成した C ソース。手で編集しない */")
        self._w('#include "nbrt.h"')
        self._w("#include <math.h>    /* llrint (DOUBLE→INTEGER 変換) */")
        self._w()

        self._emit_string_pool()
        self._emit_data_table()
        self._emit_globals()
        self._emit_prototypes()
        for func in self.ir.funcs:
            self._emit_func(func)
        return "\n".join(self.lines) + "\n"

    def _emit_string_pool(self) -> None:
        """文字列リテラルは「本体バイト列」と「nb_str 記述子」の対で
        static に置く。記述子のアドレス (&nbs_N) が StrConst の値。"""
        if not self.ir.strings:
            return
        self._w("/* ---- 文字列リテラルプール ---- */")
        for i, s in enumerate(self.ir.strings):
            data = s.encode("utf-8")
            self._w(f"static const char nbs_data_{i}[] = {_c_escape(s)};")
            self._w(f"static nb_str nbs_{i} = "
                    f"{{ {len(data)}, nbs_data_{i} }};")
        self._w()

    def _emit_data_table(self) -> None:
        """DATA 文の項目表。ランタイムが extern 参照する契約シンボル
        (nbrt.h 参照) なので、項目が無くても必ず定義する。"""
        self._w("/* ---- DATA 文の項目表 ---- */")
        if self.ir.data_items:
            items = ", ".join(_c_escape(d) for d in self.ir.data_items)
            self._w(f"const char *const nb_data_items[] = {{ {items} }};")
        else:
            self._w("const char *const nb_data_items[] = { 0 };")
        self._w(f"const int64_t nb_data_count = {len(self.ir.data_items)};")
        self._w()

    def _emit_globals(self) -> None:
        if not self.ir.globals:
            return
        self._w("/* ---- 大域変数 (明示 DIM された変数と配列ハンドル) ---- */")
        for g in self.ir.globals:
            init = "0" if g.ty != S else "0 /* メイン先頭で空文字列化 */"
            self._w(f"static {_CTYPE[g.ty]}{g.name} = {init};"
                    if g.ty == S else
                    f"static {_CTYPE[g.ty]} {g.name} = {init};")
        self._w()

    def _emit_prototypes(self) -> None:
        """相互再帰や後方参照に備えて全関数のプロトタイプを先に出す。"""
        self._w("/* ---- プロトタイプ ---- */")
        for f in self.ir.funcs:
            self._w(self._signature(f) + ";")
        self._w()

    def _signature(self, f: IRFunc) -> str:
        ret = "void" if f.ret_ty is None else _CTYPE[f.ret_ty].strip()
        if not f.params:
            return f"{ret} {f.name}(void)"
        ps = ", ".join(f"{_CTYPE[p.ty].strip()} {p.name}" for p in f.params)
        return f"{ret} {f.name}({ps})"

    # ------------------------------------------------------------------
    # 関数 1 個
    # ------------------------------------------------------------------

    def _emit_func(self, f: IRFunc) -> None:
        self._w(self._signature(f))
        self._w("{")

        # ローカル変数と仮想レジスタの宣言。初期値は防御的に 0/NULL
        # (名前付き変数の言語仕様上の初期化は IR 側の mov が行う)。
        for slot in f.local_slots():
            init = "0" if slot.ty != S else "0"
            self._w(f"    {_CTYPE[slot.ty].strip()} {slot.name} = {init};")
        for r in f.vregs():
            self._w(f"    {_CTYPE[r.ty].strip()} t{r.id} = 0;")
        if f.local_slots() or f.vregs():
            self._w()

        for ins in f.body:
            self._emit_ins(ins)

        self._w("}")
        self._w()

    def _emit_ins(self, ins: Ins) -> None:
        op = ins.op
        w = self._w
        v = self._val
        a = ins.args[0] if ins.args else None
        b = ins.args[1] if len(ins.args) > 1 else None
        d = v(ins.dest) if ins.dest is not None else None

        if op == "label":
            # C のラベルには文が続く必要があるので空文 ; を添える
            w(f"{ins.extra}: ;")
        elif op == "jmp":
            w(f"    goto {ins.extra};")
        elif op == "jz":
            w(f"    if ({v(a)} == 0) goto {ins.extra};")
        elif op == "jnz":
            w(f"    if ({v(a)} != 0) goto {ins.extra};")
        elif op == "mov":
            w(f"    {d} = {v(a)};")
        elif op in ("add", "sub", "mul"):
            c_op = {"add": "+", "sub": "-", "mul": "*"}[op]
            if ins.ty == I:
                # 符号付きオーバーフローの未定義動作を避けるため
                # uint64_t で計算する (2 の補数ラップアラウンド)
                w(f"    {d} = (int64_t)((uint64_t){v(a)} {c_op} "
                  f"(uint64_t){v(b)});")
            else:
                w(f"    {d} = {v(a)} {c_op} {v(b)};")
        elif op == "fdiv":
            w(f"    {d} = {v(a)} / {v(b)};")
        elif op in ("and", "or", "xor"):
            c_op = {"and": "&", "or": "|", "xor": "^"}[op]
            w(f"    {d} = {v(a)} {c_op} {v(b)};")
        elif op == "neg":
            if ins.ty == I:
                w(f"    {d} = (int64_t)(0u - (uint64_t){v(a)});")
            else:
                w(f"    {d} = -{v(a)};")
        elif op == "not":
            w(f"    {d} = ~{v(a)};")
        elif op == "itof":
            w(f"    {d} = (double){v(a)};")
        elif op == "ftoi":
            # llrint は現在の丸めモード (既定: 最近接偶数丸め) で変換する。
            # x86-64 バックエンドの cvtsd2si と同じ結果になる。
            w(f"    {d} = llrint({v(a)});")
        elif op == "cmp":
            w(f"    {d} = ({v(a)} {_CMP_OP[ins.extra]} {v(b)}) ? -1 : 0;")
        elif op == "call":
            args = ", ".join(self._val(x) for x in ins.args)
            if d is None:
                w(f"    {ins.extra}({args});")
            else:
                w(f"    {d} = {ins.extra}({args});")
        elif op == "ret":
            if ins.args:
                w(f"    return {v(a)};")
            else:
                w("    return;")
        else:
            raise AssertionError(f"unknown IR op {op}")


def generate(ir: IRProgram) -> str:
    """モジュールの公開エントリポイント: IR → C ソース文字列。"""
    return CBackend(ir).generate()
