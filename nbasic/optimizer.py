"""
optimizer.py — IR レベルの最適化器
==================================

-O オプションで有効になる、教科書的だが効果の大きい最適化を IR に施す。
すべて関数単位で動作し、次の 4 つを不動点まで繰り返す:

1. **定数畳み込み (constant folding)**
   オペランドがすべて定数の算術・比較・変換命令を、結果の定数の
   mov に置き換える。IR の仮想レジスタ (VReg) は生成器の構成により
   「一度しか代入されない」ので、VReg の値が定数だと分かれば
   その後の使用箇所すべてに安全に伝播できる。

2. **コピー伝播 (copy propagation)**
   `mov %t, 定数` と `mov %t, %u` (VReg どうし) を追跡し、%t の使用を
   元の値で置き換える。**VarSlot (変数) が源のコピーは伝播しない** —
   変数は途中の call や mov で書き換わる可能性があり、素朴な伝播は
   評価順序のセマンティクス (仕様書 §5.1) を壊すため。

3. **死コード除去 (dead code elimination)**
   (a) 結果がどこからも使われない副作用なし命令の削除。
       call は入出力や実行時エラーの可能性があるため常に残す。
   (b) 到達不能コードの削除: 無条件ジャンプ・ret の直後から次のラベル
       までは実行されない。

4. **ジャンプ簡約 (jump simplification)**
   直後のラベルへの jmp の削除、条件が定数の jz/jnz の無条件化/削除、
   どこからも参照されないラベルの削除 (これが (3b) をさらに誘発する)。

これらは互いに機会を生み合うので、変化がなくなるまで繰り返す。
BASIC の真理値規約 (真 = -1、偽 = 0) は比較の畳み込みでも維持する。
"""

from __future__ import annotations

from .ast_nodes import Type
from .ir import (IRProgram, IRFunc, Ins, VReg, VarSlot,
                 IntConst, FloatConst, StrConst, Value)

I, D = Type.INTEGER, Type.DOUBLE

# 64bit 整数のラップアラウンド (C の int64_t と同じ振る舞いに揃える)
_MASK = (1 << 64) - 1


def _wrap64(v: int) -> int:
    """Python の任意精度整数を 64bit 符号付きへ折り返す。"""
    v &= _MASK
    return v - (1 << 64) if v >= (1 << 63) else v


def optimize(ir: IRProgram) -> IRProgram:
    """モジュールの公開エントリポイント。ir を破壊的に最適化して返す。"""
    for func in ir.funcs:
        _optimize_func(func)
    return ir


def _optimize_func(func: IRFunc) -> None:
    # 各パスは「変更したか」を返す。何も変わらなくなるまで回す。
    # パス数はプログラムサイズに比例して抑えられる (通常 2〜4 回で収束)。
    for _ in range(50):
        changed = False
        changed |= _fold_and_propagate(func)
        changed |= _remove_dead_temps(func)
        changed |= _simplify_jumps(func)
        changed |= _remove_unreachable(func)
        if not changed:
            break


# --------------------------------------------------------------------------
# パス 1: 定数畳み込み + コピー伝播
# --------------------------------------------------------------------------

def _fold_and_propagate(func: IRFunc) -> bool:
    """VReg → 既知の値 (定数 or 別の VReg) の表を作りながら 1 パス走査。

    VReg は一度しか代入されず、しかも IR 生成器は「定義より後ろ」でしか
    使わないため、制御フローを解析しなくても表は常に正しい
    (定義に到達していないパスでは使用にも到達しない)。
    """
    known: dict[VReg, Value] = {}
    changed = False

    def subst(v: Value) -> Value:
        # 使用箇所を既知の値で置き換える (連鎖をたどる)
        while isinstance(v, VReg) and v in known:
            v = known[v]
        return v

    for idx, ins in enumerate(func.body):
        # ---- まずオペランドに伝播 ----
        new_args = tuple(subst(a) for a in ins.args)
        if new_args != ins.args:
            ins.args = new_args
            changed = True

        dest = ins.dest
        a = ins.args[0] if ins.args else None
        b = ins.args[1] if len(ins.args) > 1 else None

        # ---- mov の記録 (伝播できるのは定数と VReg 源のみ) ----
        if ins.op == "mov" and isinstance(dest, VReg):
            if isinstance(a, (IntConst, FloatConst, StrConst, VReg)):
                known[dest] = a
            continue

        # ---- 定数畳み込み ----
        if not isinstance(dest, VReg):
            continue
        folded = _fold(ins, a, b)
        if folded is not None:
            # 命令ごと mov に置き換える
            func.body[idx] = Ins(op="mov", ty=ins.ty, dest=dest,
                                 args=(folded,))
            # 伝播してよいのは定数と VReg のみ。代数的簡約 (x+0 → x) が
            # VarSlot を返すことがあるが、変数は後続の命令で書き換わり
            # うるので、使用箇所への伝播は行わない (mov のまま残す)。
            if isinstance(folded, (IntConst, FloatConst, StrConst, VReg)):
                known[dest] = folded
            changed = True

    return changed


def _fold(ins: Ins, a: Value, b: Value) -> Value | None:
    """畳み込み可能なら結果の定数 Value を、不可能なら None を返す。"""
    op = ins.op

    # ---- 単項 ----
    if op == "neg":
        if isinstance(a, IntConst):
            return IntConst(_wrap64(-a.v))
        if isinstance(a, FloatConst):
            return FloatConst(-a.v)
        return None
    if op == "not" and isinstance(a, IntConst):
        return IntConst(_wrap64(~a.v))
    if op == "itof" and isinstance(a, IntConst):
        return FloatConst(float(a.v))
    if op == "ftoi" and isinstance(a, FloatConst):
        # 実行時 (llrint / cvtsd2si) と同じ最近接偶数丸め。
        # Python の round() も偶数丸めなので一致する。
        return IntConst(_wrap64(round(a.v)))

    # ---- 二項算術 ----
    if op in ("add", "sub", "mul"):
        if isinstance(a, IntConst) and isinstance(b, IntConst):
            r = {"add": a.v + b.v, "sub": a.v - b.v,
                 "mul": a.v * b.v}[op]
            return IntConst(_wrap64(r))
        if isinstance(a, FloatConst) and isinstance(b, FloatConst):
            r = {"add": a.v + b.v, "sub": a.v - b.v,
                 "mul": a.v * b.v}[op]
            return FloatConst(r)
        # 代数的簡約: x+0, x-0, x*1 は x そのもの (x*0 は x の評価が
        # 済んでいるので 0 に置き換えてよいが、浮動小数の -0.0/NaN の
        # 事情があるため整数のみ)
        if op in ("add", "sub") and isinstance(b, IntConst) and b.v == 0:
            return a
        if op == "mul" and isinstance(b, IntConst) and b.v == 1:
            return a
        if op == "mul" and isinstance(a, IntConst) and a.v == 1:
            return b
        return None
    if op == "fdiv":
        if isinstance(a, FloatConst) and isinstance(b, FloatConst) \
           and b.v != 0.0:
            return FloatConst(a.v / b.v)
        return None

    # ---- ビット演算 ----
    if op in ("and", "or", "xor"):
        if isinstance(a, IntConst) and isinstance(b, IntConst):
            r = {"and": a.v & b.v, "or": a.v | b.v,
                 "xor": a.v ^ b.v}[op]
            return IntConst(_wrap64(r))
        return None

    # ---- 比較 (結果は BASIC 真理値: 真 = -1, 偽 = 0) ----
    if op == "cmp":
        if isinstance(a, (IntConst, FloatConst)) \
           and isinstance(b, (IntConst, FloatConst)):
            av, bv = a.v, b.v
            res = {"EQ": av == bv, "NE": av != bv, "LT": av < bv,
                   "LE": av <= bv, "GT": av > bv, "GE": av >= bv}[ins.extra]
            return IntConst(-1 if res else 0)
        return None

    return None


# --------------------------------------------------------------------------
# パス 2: 使われない一時レジスタの除去
# --------------------------------------------------------------------------

# 副作用が無く、結果が使われなければ丸ごと消してよい命令
_PURE_OPS = frozenset({"mov", "add", "sub", "mul", "fdiv", "and", "or",
                       "xor", "neg", "not", "itof", "ftoi", "cmp"})


def _remove_dead_temps(func: IRFunc) -> bool:
    """どこからも読まれない VReg を定義する純粋命令を削除する。
    VarSlot への mov は (他の文から読まれるかもしれないので) 残す。"""
    used: set[VReg] = set()
    for ins in func.body:
        for v in ins.args:
            if isinstance(v, VReg):
                used.add(v)

    new_body: list[Ins] = []
    changed = False
    for ins in func.body:
        if (ins.op in _PURE_OPS and isinstance(ins.dest, VReg)
                and ins.dest not in used):
            changed = True
            continue
        new_body.append(ins)
    func.body = new_body
    return changed


# --------------------------------------------------------------------------
# パス 3: ジャンプ簡約
# --------------------------------------------------------------------------

def _simplify_jumps(func: IRFunc) -> bool:
    changed = False
    body = func.body

    # (a) 条件が定数の jz/jnz を無条件化または削除
    new_body: list[Ins] = []
    for ins in body:
        if ins.op in ("jz", "jnz") and isinstance(ins.args[0], IntConst):
            taken = (ins.args[0].v == 0) == (ins.op == "jz")
            changed = True
            if taken:
                new_body.append(Ins(op="jmp", extra=ins.extra))
            # 不成立なら命令ごと消える
            continue
        new_body.append(ins)
    body = new_body

    # (b) 直後のラベルへの jmp/jz/jnz を削除 (間のラベルは跨いでよい)
    def next_labels(i: int) -> set[str]:
        """命令 i の直後に (実行を挟まず) 並ぶラベル名の集合。"""
        out: set[str] = set()
        j = i + 1
        while j < len(body) and body[j].op == "label":
            out.add(body[j].extra)
            j += 1
        return out

    new_body = []
    for i, ins in enumerate(body):
        if ins.op in ("jmp", "jz", "jnz") and ins.extra in next_labels(i):
            changed = True
            continue   # 飛び先が直後なのでジャンプ不要
        new_body.append(ins)
    body = new_body

    # (c) 参照されないラベルの削除 (到達不能コード除去の機会を作る)
    referenced = {ins.extra for ins in body if ins.op in ("jmp", "jz", "jnz")}
    # __gosub_dispatch はディスパッチャ生成の都合で必ず残す
    referenced.add("__gosub_dispatch")
    new_body = []
    for ins in body:
        if ins.op == "label" and ins.extra not in referenced \
           and not ins.extra.startswith("L_"):
            # ユーザーラベル (L_) はデバッグの目印として残す
            changed = True
            continue
        new_body.append(ins)

    func.body = new_body
    return changed


# --------------------------------------------------------------------------
# パス 4: 到達不能コードの除去
# --------------------------------------------------------------------------

def _remove_unreachable(func: IRFunc) -> bool:
    """無条件制御移動 (jmp / ret) の直後から次のラベルまでは
    どの実行経路からも到達できないので削除する。"""
    new_body: list[Ins] = []
    dead = False
    changed = False
    for ins in func.body:
        if ins.op == "label":
            dead = False
        if dead:
            changed = True
            continue
        new_body.append(ins)
        if ins.op in ("jmp", "ret"):
            dead = True
    func.body = new_body
    return changed
