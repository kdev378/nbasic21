"""
backend_x64.py — x86-64 バックエンド共通部 + Windows x64 (Microsoft ABI)
========================================================================

IR を NASM 構文の x86-64 アセンブリへ変換する。x86-64 のバックエンドは
2 つある:

    backend_x64.py       : このファイル。共通のコード生成基盤
                           (X64Backend) と Windows x64 版 (Win64Backend)
    backend_x64_linux.py : Linux 版 (SysVBackend)。System V AMD64 ABI

**命令選択・データ生成・フレーム構成は 2 つの OS で完全に共通**であり、
違いは「関数の呼び出し規約 (引数をどのレジスタ/スタック位置で渡すか)」
と ELF/COFF 固有のセクション指定だけである。そこで共通部を基底クラス
X64Backend に置き、ABI 依存箇所を 4 つのフックに分離した:

    _header_lines()     : 冒頭コメントとアセンブル手順
    _out_area_bytes(f)  : フレーム下端に確保する呼び出し引数領域の大きさ
    _spill_params(f)    : 関数入口で受け取った引数を自分のスロットへ退避
    _emit_call(ins)     : call 命令 1 個の引数搬送と呼び出し
    _emit_footer()      : ファイル末尾の OS 固有セクション

コード生成戦略 — 「スタックマシン式」の素朴なコード生成
--------------------------------------------------------
レジスタ割り付けは行わない。すべての値スロット (仮想レジスタ VReg と
ローカル変数 VarSlot) にスタックフレーム上の 8 バイトスロットを割り当て、
各 IR 命令は

    (1) オペランドをスクラッチレジスタへロード
    (2) 演算
    (3) 結果をスロットへストア

という 3 手で実装する。生成コードの速度は最適とは言えないが、
**正しさの検証が容易**で、どの命令も独立して読める。速度が必要なら
C バックエンド + 最適化コンパイラを使えばよい、という役割分担である
(docs/ARCHITECTURE.md §6)。

スクラッチレジスタの取り決め (両 ABI で揮発なものだけを使う):
    rax, r10, r11 — 整数/ポインタ演算用
    xmm0, xmm1    — 浮動小数演算用

スタックフレームのレイアウト (prologue 後、両 ABI 共通):

        [rbp+16+8i]   ← 呼び出し側が積んだ自分のスタック渡し引数
        [rbp+8]       ← 戻り番地
        [rbp]         ← 保存された旧 rbp
        [rbp-8n]      ← 値スロット (VReg / ローカル VarSlot)
        ...
        [rsp+..]      ← 呼び出し先へ渡す引数領域 (ABI 依存)

`push rbp` の直後は rsp ≡ 0 (mod 16) なので、フレームサイズを
16 の倍数にすれば call 時の整列条件 (両 ABI とも rsp ≡ 0 mod 16)
が常に満たされる。

Microsoft x64 呼び出し規約 (Win64Backend が実装):
    - 整数/ポインタ引数: rcx, rdx, r8, r9 (第 1〜4)、以降スタック
    - 浮動小数引数     : xmm0〜xmm3 (**位置対応**。第 2 引数が double
                         なら xmm1 を使い rdx は使わない)
    - 第 5 引数以降    : call 時の [rsp+32] から 8 バイト刻み
    - シャドウ空間     : 呼び出し側が [rsp+0..31] に 32 バイト確保
    - 戻り値           : 整数/ポインタ → rax、double → xmm0
"""

from __future__ import annotations

import struct

from .ast_nodes import Type
from .ir import (IRProgram, IRFunc, Ins, VReg, VarSlot,
                 IntConst, FloatConst, StrConst, Value, value_type)

I, D, S = Type.INTEGER, Type.DOUBLE, Type.STRING

# 比較種別 → setcc 命令 (整数は符号付き、浮動小数は comisd の
# フラグ規約に合わせて符号なし系を使う)
_SETCC_INT = {"EQ": "sete", "NE": "setne", "LT": "setl",
              "LE": "setle", "GT": "setg", "GE": "setge"}
_SETCC_FLT = {"EQ": "sete", "NE": "setne", "LT": "setb",
              "LE": "setbe", "GT": "seta", "GE": "setae"}


def _asm_bytes(data: bytes) -> str:
    """バイト列を NASM の db 疑似命令のオペランドに変換する。

    印字可能 ASCII の連続は 'quoted' でまとめ、それ以外は 10 進の
    バイト値で出す。NASM のシングルクォート文字列にはエスケープが
    無いため、' 自体は数値で出す。
    """
    parts: list[str] = []
    run: list[str] = []

    def flush_run() -> None:
        if run:
            parts.append("'" + "".join(run) + "'")
            run.clear()

    for b in data:
        if 0x20 <= b < 0x7F and b != 0x27:      # 印字可能で ' でない
            run.append(chr(b))
        else:
            flush_run()
            parts.append(str(b))
    flush_run()
    return ", ".join(parts) if parts else "0"


class X64Backend:
    """ABI 非依存の共通コード生成。サブクラスがフックを実装する。"""

    def __init__(self, ir: IRProgram):
        self.ir = ir
        self.lines: list[str] = []
        # 浮動小数リテラル → データ領域ラベル (値のビットパターンで共有)
        self.float_pool: dict[int, str] = {}
        # 現在の関数のスロット割り付け: Value → rbp からのオフセット (負)
        self.slot_off: dict[object, int] = {}
        self.frame_size = 0

    def _w(self, line: str = "") -> None:
        self.lines.append(line)

    # ------------------------------------------------------------------
    # ABI フック (サブクラスが実装)
    # ------------------------------------------------------------------

    def _header_lines(self) -> list[str]:
        raise NotImplementedError

    def _out_area_bytes(self, f: IRFunc) -> int:
        """フレーム下端に確保する「呼び出し先へ渡す引数」領域のバイト数。
        16 の倍数で返すこと。"""
        raise NotImplementedError

    def _spill_params(self, f: IRFunc) -> None:
        """関数入口: 受け取った引数を自分の値スロットへ退避する。"""
        raise NotImplementedError

    def _emit_call(self, ins: Ins) -> None:
        raise NotImplementedError

    def _emit_footer(self) -> None:
        """ファイル末尾の OS 固有セクション (無ければ何もしない)。"""

    # ------------------------------------------------------------------
    # 出力全体
    # ------------------------------------------------------------------

    def generate(self) -> str:
        for line in self._header_lines():
            self._w(line)
        self._w("bits 64")
        self._w("default rel                 ; メモリ参照は既定で RIP 相対")
        self._w()

        # ---- シンボルの輸出入 ----
        for f in self.ir.funcs:
            self._w(f"global {f.name}")
        self._w("global nb_data_items")
        self._w("global nb_data_count")
        externs = self._collect_externs()
        for sym in sorted(externs):
            self._w(f"extern {sym}")
        self._w()

        # ---- コード ----
        self._w("section .text")
        self._w()
        for func in self.ir.funcs:
            self._emit_func(func)

        # ---- データ ----
        self._emit_data_section()
        self._emit_footer()
        return "\n".join(self.lines) + "\n"

    def _collect_externs(self) -> set[str]:
        """呼び出すが自分では定義しないシンボル = ランタイム関数。"""
        defined = {f.name for f in self.ir.funcs}
        out: set[str] = set()
        for f in self.ir.funcs:
            for ins in f.body:
                if ins.op == "call" and ins.extra not in defined:
                    out.add(ins.extra)
        return out

    def _emit_data_section(self) -> None:
        self._w("section .data")
        self._w()

        # 文字列リテラル: 本体バイト列 + nb_str 記述子 {len, ptr}
        if self.ir.strings:
            self._w("; ---- 文字列リテラルプール ----")
            for i, s in enumerate(self.ir.strings):
                data = s.encode("utf-8")
                if data:
                    self._w(f"nbs_data_{i}: db {_asm_bytes(data)}, 0")
                else:
                    self._w(f"nbs_data_{i}: db 0")
                self._w("align 8")
                self._w(f"nbs_{i}: dq {len(data)}, nbs_data_{i}"
                        f"    ; {s[:40]!r}")
            self._w()

        # DATA 文の項目表 (ランタイムとの契約シンボル)
        self._w("; ---- DATA 文の項目表 ----")
        for i, d in enumerate(self.ir.data_items):
            self._w(f"nbd_{i}: db {_asm_bytes(d.encode('utf-8'))}, 0")
        self._w("align 8")
        if self.ir.data_items:
            ptrs = ", ".join(f"nbd_{i}"
                             for i in range(len(self.ir.data_items)))
            self._w(f"nb_data_items: dq {ptrs}")
        else:
            self._w("nb_data_items: dq 0")
        self._w(f"nb_data_count: dq {len(self.ir.data_items)}")
        self._w()

        # 大域変数 (すべて 8 バイト。初期値はメイン先頭の IR が入れる)
        if self.ir.globals:
            self._w("; ---- 大域変数 ----")
            for g in self.ir.globals:
                self._w(f"{g.name}: dq 0")
            self._w()

        # 浮動小数リテラル (IEEE754 のビットパターンで格納)
        if self.float_pool:
            self._w("; ---- 浮動小数リテラルプール ----")
            for bits, label in self.float_pool.items():
                as_float = struct.unpack("<d", struct.pack("<Q", bits))[0]
                self._w(f"{label}: dq 0x{bits:016X}    ; {as_float!r}")
            self._w()

        # 浮動小数の符号反転用マスク (xorpd で符号ビットだけ反転する)
        self._w("; ---- 定数マスク ----")
        self._w("nb_negmask: dq 0x8000000000000000")

    # ------------------------------------------------------------------
    # オペランドのアドレッシング
    # ------------------------------------------------------------------

    def _float_label(self, v: float) -> str:
        bits = struct.unpack("<Q", struct.pack("<d", v))[0]
        if bits not in self.float_pool:
            self.float_pool[bits] = f"nbf_{len(self.float_pool)}"
        return self.float_pool[bits]

    def _slot_addr(self, v: Value) -> str:
        """値スロット (VReg / VarSlot) のメモリオペランドを返す。"""
        if isinstance(v, VarSlot) and v.is_global:
            return f"[{v.name}]"                 # RIP 相対 (default rel)
        return f"[rbp{self.slot_off[self._slot_key(v)]:+d}]"

    @staticmethod
    def _slot_key(v: Value) -> object:
        """スロット割り付け表のキー。VReg は id、VarSlot は名前で引く。"""
        if isinstance(v, VReg):
            return ("r", v.id)
        if isinstance(v, VarSlot):
            return ("v", v.name)
        raise AssertionError(f"not a slot: {v!r}")

    def _load_int(self, reg: str, v: Value) -> None:
        """整数/ポインタ値をレジスタへロードする。

        FloatConst もビットパターンとしてロードできる (スタック引数の
        搬送に使う)。"""
        if isinstance(v, IntConst):
            self._w(f"    mov {reg}, {v.v}")
        elif isinstance(v, FloatConst):
            bits = struct.unpack("<Q", struct.pack("<d", v.v))[0]
            self._w(f"    mov {reg}, 0x{bits:016X}")
        elif isinstance(v, StrConst):
            self._w(f"    lea {reg}, [nbs_{v.index}]")
        else:
            self._w(f"    mov {reg}, {self._slot_addr(v)}")

    def _load_flt(self, xmm: str, v: Value) -> None:
        """浮動小数値を XMM レジスタへロードする。"""
        if isinstance(v, FloatConst):
            self._w(f"    movsd {xmm}, [{self._float_label(v.v)}]")
        else:
            self._w(f"    movsd {xmm}, {self._slot_addr(v)}")

    def _store_int(self, dest: Value, reg: str) -> None:
        self._w(f"    mov {self._slot_addr(dest)}, {reg}")

    def _store_flt(self, dest: Value, xmm: str) -> None:
        self._w(f"    movsd {self._slot_addr(dest)}, {xmm}")

    # ------------------------------------------------------------------
    # 関数 1 個
    # ------------------------------------------------------------------

    def _emit_func(self, f: IRFunc) -> None:
        # ---- スロット割り付け ----
        # 仮引数・ローカル変数・仮想レジスタに [rbp-8], [rbp-16], ... を
        # 順に割り当てる。すべて 8 バイトなので詰め物は不要。
        self.slot_off = {}
        off = 0
        for slot in (*f.params, *f.local_slots()):
            off -= 8
            self.slot_off[self._slot_key(slot)] = off
        for r in f.vregs():
            off -= 8
            self.slot_off[self._slot_key(r)] = off
        locals_bytes = -off

        # フレーム = ローカル領域 + 引数領域、16 バイト整列 (冒頭コメント)
        out_bytes = self._out_area_bytes(f)
        self.frame_size = (locals_bytes + out_bytes + 15) & ~15

        # ---- プロローグ ----
        self._w(f"{f.name}:")
        self._w("    push rbp")
        self._w("    mov rbp, rsp")
        self._w(f"    sub rsp, {self.frame_size}")
        self._spill_params(f)
        self._w()

        for ins in f.body:
            self._emit_ins(f, ins)

        # ret 命令が必ず出力されているので、ここには落ちてこない。
        self._w()

    # ------------------------------------------------------------------
    # 命令 1 個 (ABI 非依存)
    # ------------------------------------------------------------------

    def _emit_ins(self, f: IRFunc, ins: Ins) -> None:
        op = ins.op
        w = self._w
        a = ins.args[0] if ins.args else None
        b = ins.args[1] if len(ins.args) > 1 else None

        # NASM のローカルラベル (先頭が .) は直前の通常ラベル (= 関数名)
        # ごとにスコープが切れるため、IR のラベル名に . を付けるだけで
        # 関数間の衝突を避けられる。
        if op == "label":
            w(f".{ins.extra}:")
            return
        if op == "jmp":
            w(f"    jmp .{ins.extra}")
            return
        if op in ("jz", "jnz"):
            self._load_int("rax", a)
            w("    test rax, rax")
            w(f"    {'jz' if op == 'jz' else 'jnz'} .{ins.extra}")
            return

        if op == "mov":
            if ins.ty == D:
                self._load_flt("xmm0", a)
                self._store_flt(ins.dest, "xmm0")
            else:
                self._load_int("rax", a)
                self._store_int(ins.dest, "rax")
            return

        if op in ("add", "sub", "mul"):
            if ins.ty == I:
                self._load_int("rax", a)
                self._load_int("r10", b)
                asm = {"add": "add rax, r10", "sub": "sub rax, r10",
                       "mul": "imul rax, r10"}[op]
                w(f"    {asm}")
                self._store_int(ins.dest, "rax")
            else:
                self._load_flt("xmm0", a)
                self._load_flt("xmm1", b)
                asm = {"add": "addsd", "sub": "subsd", "mul": "mulsd"}[op]
                w(f"    {asm} xmm0, xmm1")
                self._store_flt(ins.dest, "xmm0")
            return

        if op == "fdiv":
            self._load_flt("xmm0", a)
            self._load_flt("xmm1", b)
            w("    divsd xmm0, xmm1")
            self._store_flt(ins.dest, "xmm0")
            return

        if op in ("and", "or", "xor"):
            self._load_int("rax", a)
            self._load_int("r10", b)
            w(f"    {op} rax, r10")
            self._store_int(ins.dest, "rax")
            return

        if op == "neg":
            if ins.ty == I:
                self._load_int("rax", a)
                w("    neg rax")
                self._store_int(ins.dest, "rax")
            else:
                # 浮動小数の符号反転は符号ビットの XOR (-0.0 も正しく扱う)
                self._load_flt("xmm0", a)
                w("    movsd xmm1, [nb_negmask]")
                w("    xorpd xmm0, xmm1")
                self._store_flt(ins.dest, "xmm0")
            return

        if op == "not":
            self._load_int("rax", a)
            w("    not rax")
            self._store_int(ins.dest, "rax")
            return

        if op == "itof":
            self._load_int("rax", a)
            w("    cvtsi2sd xmm0, rax")
            self._store_flt(ins.dest, "xmm0")
            return

        if op == "ftoi":
            # cvtsd2si は MXCSR の丸めモード (既定: 最近接偶数丸め) を
            # 使う。C バックエンドの llrint と同じ結果になる。
            self._load_flt("xmm0", a)
            w("    cvtsd2si rax, xmm0")
            self._store_int(ins.dest, "rax")
            return

        if op == "cmp":
            if ins.ty == D:
                self._load_flt("xmm0", a)
                self._load_flt("xmm1", b)
                w("    comisd xmm0, xmm1")
                setcc = _SETCC_FLT[ins.extra]
            else:
                self._load_int("rax", a)
                self._load_int("r10", b)
                w("    cmp rax, r10")
                setcc = _SETCC_INT[ins.extra]
            # setcc は 0/1 を作るので、符号反転して BASIC の真理値
            # (真 = -1) に変換する。
            w(f"    {setcc} al")
            w("    movzx eax, al")
            w("    neg rax")
            self._store_int(ins.dest, "rax")
            return

        if op == "call":
            self._emit_call(ins)
            return

        if op == "ret":
            if ins.args:
                if value_type(a) == D:
                    self._load_flt("xmm0", a)
                else:
                    self._load_int("rax", a)
            w("    leave                    ; mov rsp,rbp / pop rbp")
            w("    ret")
            return

        raise AssertionError(f"unknown IR op {op}")

    def _store_call_result(self, ins: Ins) -> None:
        """call の戻り値 (rax / xmm0) を格納する。両 ABI 共通。"""
        if ins.dest is not None:
            if value_type(ins.dest) == D:
                self._store_flt(ins.dest, "xmm0")
            else:
                self._store_int(ins.dest, "rax")


# ======================================================================
# Windows x64 (Microsoft ABI)
# ======================================================================

# 整数引数レジスタ (Microsoft x64、位置対応)
_WIN_ARG_GPR = ("rcx", "rdx", "r8", "r9")
_WIN_ARG_XMM = ("xmm0", "xmm1", "xmm2", "xmm3")


class Win64Backend(X64Backend):
    """Microsoft x64 呼び出し規約 (モジュール冒頭コメント参照)。"""

    def _header_lines(self) -> list[str]:
        return [
            "; NBASIC-21 コンパイラが生成した Windows x64 アセンブリ",
            "; アセンブル: nasm -f win64 このファイル",
            "; リンク    : x86_64-w64-mingw32-gcc out.obj nbrt.c -o out.exe",
        ]

    def _out_area_bytes(self, f: IRFunc) -> int:
        # シャドウ空間 32 バイト + 第 5 引数以降。関数内の全 call の最大。
        # 呼び出しが 1 つも無くても 32 バイト確保しておく (無害で単純)。
        max_args = 0
        for ins in f.body:
            if ins.op == "call":
                max_args = max(max_args, len(ins.args))
        out = 32 + max(0, max_args - 4) * 8
        return (out + 15) & ~15

    def _spill_params(self, f: IRFunc) -> None:
        # 受け取った引数を自分のスロットへ退避する。
        # 第 1〜4 引数はレジスタ (double なら xmm 側)、以降は
        # 呼び出し側のスタック [rbp+16+32+8(i-4)] にある
        # (+16 = 旧 rbp と戻り番地、+32 = シャドウ空間)。
        for i, p in enumerate(f.params):
            if i < 4:
                if p.ty == D:
                    self._store_flt(p, _WIN_ARG_XMM[i])
                else:
                    self._store_int(p, _WIN_ARG_GPR[i])
            else:
                self._w(f"    mov rax, [rbp+{16 + 32 + 8 * (i - 4)}]")
                self._store_int(p, "rax")

    def _emit_call(self, ins: Ins) -> None:
        """Microsoft x64 規約での関数呼び出し。

        すべての引数値はスロットか定数にあるので、好きな順に搬送できる。
        スクラッチ (rax) を使う第 5 引数以降を先に積み、その後で
        引数レジスタを埋める (逆順だと搬送でレジスタを壊しかねない)。
        """
        w = self._w
        # ---- 第 5 引数以降をスタックの引数領域へ ----
        for i, v in enumerate(ins.args):
            if i < 4:
                continue
            # 値の型を問わず 8 バイトのビットパターンとして搬送すればよい
            self._load_int("rax", v)
            w(f"    mov [rsp+{32 + 8 * (i - 4)}], rax")

        # ---- 第 1〜4 引数をレジスタへ ----
        # 位置 i の引数は double なら xmm_i、それ以外は GPR_i を使う
        # (Microsoft 規約はレジスタが位置で対応する)。
        for i, v in enumerate(ins.args):
            if i >= 4:
                break
            if value_type(v) == D:
                self._load_flt(_WIN_ARG_XMM[i], v)
            else:
                self._load_int(_WIN_ARG_GPR[i], v)

        w(f"    call {ins.extra}")
        self._store_call_result(ins)


def generate(ir: IRProgram) -> str:
    """モジュールの公開エントリポイント: IR → NASM (Windows x64)。"""
    return Win64Backend(ir).generate()
