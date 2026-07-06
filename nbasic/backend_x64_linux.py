"""
backend_x64_linux.py — x86-64 Linux バックエンド (System V AMD64 ABI)
=====================================================================

backend_x64.py の共通基盤 (X64Backend) の上に、Linux (ELF) 用の
呼び出し規約だけを実装したバックエンド。ターゲットは x86-64 の
Linux (glibc / カーネル 6.x 以降で動作確認。ABI は昔から同じなので
実際にはもっと古いカーネルでも動く)。

ビルド手順:

    nasm -f elf64 out.asm -o out.o
    gcc out.o runtime/nbrt.c -lm -o program

System V AMD64 呼び出し規約 (Microsoft x64 との違いに注目):

    - 整数/ポインタ引数: rdi, rsi, rdx, rcx, r8, r9 (第 1〜6)
    - 浮動小数引数     : xmm0〜xmm7 (第 1〜8)
    - **整数と浮動小数は別々に数える**。Microsoft の「位置対応」と
      違い、(int, double, int) は rdi, xmm0, rsi に載る。
    - レジスタに収まらない引数だけがスタックへ ([rsp+0] から昇順)。
      シャドウ空間は無い。
    - スタック整列     : call 命令の時点で rsp ≡ 0 (mod 16) (同じ)
    - 戻り値           : 整数/ポインタ → rax、double → xmm0 (同じ)
    - 可変引数関数を呼ぶときは AL に使用したベクタレジスタ数を入れる
      規則があるが、生成コードが呼ぶのはすべてプロトタイプ付きの
      ランタイム関数なので不要。

ELF 固有の注意:

    - シンボルに接頭辞は付かない (Win64 と同じ名前がそのまま使える)。
    - GNU ld の「実行可能スタック」警告を避けるため、末尾に
      .note.GNU-stack セクションを置く (_emit_footer)。
    - 生成コードは RIP 相対アドレッシングだけを使うので、既定で
      PIE (位置独立実行形式) としてリンクできる。データ領域の
      `dq ラベル` (文字列記述子など) は R_X86_64_64 再配置になるが、
      これはローダの RELATIVE 再配置で処理される。
"""

from __future__ import annotations

from .ast_nodes import Type
from .ir import IRFunc, Ins, IRProgram, value_type
from .backend_x64 import X64Backend

D = Type.DOUBLE

# System V の引数レジスタ (整数系と浮動小数系は独立に消費される)
_SYSV_ARG_GPR = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
_SYSV_ARG_XMM = ("xmm0", "xmm1", "xmm2", "xmm3",
                 "xmm4", "xmm5", "xmm6", "xmm7")


def _classify(args) -> tuple[list, list, list]:
    """引数列を (整数レジスタ渡し, 浮動小数レジスタ渡し, スタック渡し) に
    分類する。各要素は (引数位置, 値, レジスタ番号 or スタック順) のタプル。
    System V では整数系と浮動小数系のレジスタを別々に数え、
    あふれた引数だけが元の並び順でスタックに積まれる。
    """
    int_regs: list = []
    flt_regs: list = []
    stack: list = []
    n_int = n_flt = 0
    for i, v in enumerate(args):
        if value_type(v) == D:
            if n_flt < len(_SYSV_ARG_XMM):
                flt_regs.append((i, v, n_flt))
                n_flt += 1
            else:
                stack.append((i, v, len(stack)))
        else:
            if n_int < len(_SYSV_ARG_GPR):
                int_regs.append((i, v, n_int))
                n_int += 1
            else:
                stack.append((i, v, len(stack)))
    return int_regs, flt_regs, stack


class SysVBackend(X64Backend):
    """System V AMD64 ABI (Linux)。"""

    def _header_lines(self) -> list[str]:
        return [
            "; NBASIC-21 コンパイラが生成した Linux x86-64 アセンブリ",
            "; アセンブル: nasm -f elf64 このファイル",
            "; リンク    : gcc out.o nbrt.c -lm -o program",
        ]

    def _out_area_bytes(self, f: IRFunc) -> int:
        # スタック渡しになる引数の最大個数分だけ確保する
        # (シャドウ空間は無い)。
        max_stack = 0
        for ins in f.body:
            if ins.op == "call":
                _, _, stack = _classify(ins.args)
                max_stack = max(max_stack, len(stack))
        return (max_stack * 8 + 15) & ~15

    def _spill_params(self, f: IRFunc) -> None:
        # 受け取った引数を自分のスロットへ退避する。
        # どのレジスタ/スタック位置で届いているかは呼び出し側と対称に
        # _classify と同じ規則で決まる (仮引数スロット VarSlot は
        # value_type() で型を判定できるのでそのまま分類に掛けられる)。
        int_regs, flt_regs, stack = _classify(f.params)
        for _i, slot, reg_no in int_regs:
            self._store_int(slot, _SYSV_ARG_GPR[reg_no])
        for _i, slot, reg_no in flt_regs:
            self._store_flt(slot, _SYSV_ARG_XMM[reg_no])
        for _i, slot, stk_no in stack:
            # スタック渡し引数は [rbp+16] から昇順に並んでいる
            # (+16 = 旧 rbp と戻り番地の分。シャドウ空間は無い)。
            self._w(f"    mov rax, [rbp+{16 + 8 * stk_no}]")
            self._store_int(slot, "rax")

    def _emit_call(self, ins: Ins) -> None:
        """System V 規約での関数呼び出し。

        Win64 版と同じく、スクラッチ (rax) を使うスタック渡し引数を
        先に積み、その後でレジスタ引数を直接ロードする。
        """
        w = self._w
        int_regs, flt_regs, stack = _classify(ins.args)

        # ---- スタック渡し引数 (レジスタからあふれた分) ----
        for _i, v, stk_no in stack:
            # 値の型を問わず 8 バイトのビットパターンとして搬送すればよい
            self._load_int("rax", v)
            w(f"    mov [rsp+{8 * stk_no}], rax")

        # ---- レジスタ引数 ----
        # 各引数は自分の最終レジスタへ直接ロードする (スロット/定数から
        # のロードは他の引数レジスタを壊さない)。
        for _i, v, reg_no in int_regs:
            self._load_int(_SYSV_ARG_GPR[reg_no], v)
        for _i, v, reg_no in flt_regs:
            self._load_flt(_SYSV_ARG_XMM[reg_no], v)

        w(f"    call {ins.extra}")
        self._store_call_result(ins)

    def _emit_footer(self) -> None:
        # GNU ld は .note.GNU-stack が無いオブジェクトを「実行可能
        # スタックを要求している」とみなして警告する (新しいツール
        # チェーンではエラー)。空のノートを置いて明示する。
        self._w()
        self._w("; ELF: スタックは実行不可であることを明示")
        self._w("section .note.GNU-stack noalloc noexec nowrite progbits")


def generate(ir: IRProgram) -> str:
    """モジュールの公開エントリポイント: IR → NASM (Linux x86-64)。"""
    return SysVBackend(ir).generate()
