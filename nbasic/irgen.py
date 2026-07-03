"""
irgen.py — IR 生成器 (型注釈付き AST → 三番地コード)
====================================================

意味解析済みの AST を ir.py の命令列へ変換する。ここで行う主な低水準化:

* **制御構造の分解** — IF/WHILE/DO/FOR/SELECT をラベルと条件ジャンプに
  展開する。FOR は STEP の符号を実行時に判定する古典的セマンティクス
  (仕様書 §6.5) に従う。

* **暗黙型変換の挿入** — 意味解析器は「数値どうしは代入・演算できる」と
  だけ判定しているので、実際の itof (整数→倍精度) / ftoi (倍精度→整数、
  最近接丸め) 命令はここで挿入する。

* **文字列・配列・入出力のランタイム呼び出し化** — 文字列連結や比較、
  配列アクセス、PRINT/INPUT はすべて runtime/nbrt.c の関数呼び出しに
  変換する。バックエンドはこれらをただの call として扱えばよい。

* **GOSUB/RETURN の実装** — 各 GOSUB 地点に一意な整数 ID を割り当て、
  ランタイムの整数スタックに push してからジャンプする。RETURN は
  関数末尾の「ディスパッチャ」へ跳び、そこで pop した ID を比較連鎖で
  照合して復帰先ラベルへ跳ぶ。コンパイル型 BASIC の伝統的な手法で、
  間接ジャンプ命令を持たない IR でも GOSUB を表現できる。

* **左から右への評価順の保証** — 変数をオペランドに使う前に必ず一時
  レジスタへコピーする。`A + F(A)` のように右辺の関数呼び出しが変数を
  書き換える場合でも、左辺は呼び出し前の値で評価される (仕様書 §5.1)。

シンボル名のマングリング
------------------------
BASIC の名前には型サフィックス (% # ! $) が付くため、C の識別子や
アセンブラのシンボルとしてそのままは使えない。次の規則で変換する:

    サフィックス:  %→"_i"  #→"_d"  !→"_f"  $→"_s"
    スカラー変数:  V_<名前>       (例: COUNT% → V_COUNT_i)
    配列ハンドル:  A_<名前>       (スカラーと別名前空間、仕様書 §3.6)
    ユーザー手続き: nbu_<名前>
    ユーザーラベル: L_<名前>      (行番号なら L_100 のように)
    内部ラベル:    Lbl<連番>_<用途>
"""

from __future__ import annotations

from . import ast_nodes as A
from .ast_nodes import Type
from .analyzer import ProgramInfo, ProcInfo, ArrayInfo
from .ir import (IRProgram, IRFunc, Ins, VReg, VarSlot,
                 IntConst, FloatConst, StrConst, Value, value_type)

I, D, S = Type.INTEGER, Type.DOUBLE, Type.STRING

# 型サフィックス → マングル文字列
_SUFFIX_MANGLE = {"%": "_i", "#": "_d", "!": "_f", "$": "_s"}

# 配列要素種別コード (ランタイムの nb_arr_new* と共有する規約)
_ARR_KIND = {I: 0, D: 1, S: 2}

# 型 → ランタイム関数名の型部分 ("i64" / "f64" / "str")
_TYSFX = {I: "i64", D: "f64", S: "str"}


def mangle(name: str) -> str:
    """BASIC の識別子を C/アセンブラで使える名前に変換する。"""
    if name and name[-1] in _SUFFIX_MANGLE:
        return name[:-1] + _SUFFIX_MANGLE[name[-1]]
    return name


class IRGen:
    def __init__(self, program: A.Program, info: ProgramInfo):
        self.prog = program
        self.info = info
        self.ir = IRProgram()

        # --- 生成中の状態 ---
        self.body: list[Ins] = []          # 現在の関数の命令列
        self.cur_proc: ProcInfo | None = None
        self.ret_slot: VarSlot | None = None
        self.temp_id = 0                   # 仮想レジスタの連番
        self.label_id = 0                  # 内部ラベルの連番
        self.gosub_id = 0                  # GOSUB 地点 ID (プログラム全体で一意)
        # ループスタック: EXIT FOR/WHILE/DO の飛び先。(種別, 脱出ラベル)
        self.loop_stack: list[tuple[str, str]] = []
        # 現在の関数の GOSUB 復帰点: (ID, 復帰ラベル)
        self.gosub_sites: list[tuple[int, str]] = []
        self.needs_dispatch = False        # 値なし RETURN があったか

    # ==================================================================
    # 低レベルヘルパ
    # ==================================================================

    def _emit(self, op: str, ty: Type | None = None, dest: Value | None = None,
              args: tuple = (), extra: object = None) -> None:
        self.body.append(Ins(op=op, ty=ty, dest=dest, args=args, extra=extra))

    def _temp(self, ty: Type) -> VReg:
        self.temp_id += 1
        return VReg(self.temp_id, ty)

    def _label(self, hint: str) -> str:
        self.label_id += 1
        return f"Lbl{self.label_id}_{hint}"

    def _call(self, sym: str, args: tuple, ret_ty: Type | None) -> Value | None:
        """ランタイム/ユーザー関数呼び出しを発行し、戻り値の VReg を返す。"""
        dest = self._temp(ret_ty) if ret_ty is not None else None
        self._emit("call", dest=dest, args=args, extra=sym)
        return dest

    def _coerce(self, v: Value, to_ty: Type) -> Value:
        """暗黙型変換 (仕様書 §3.4)。

        INTEGER → DOUBLE : 値を保存する変換 (itof)
        DOUBLE → INTEGER : 最近接丸め・偶数丸め (ftoi)。定数なら
                           コンパイル時に丸める (Python の round も偶数丸め)。
        """
        fr = value_type(v)
        if fr == to_ty:
            return v
        if fr == I and to_ty == D:
            if isinstance(v, IntConst):
                return FloatConst(float(v.v))
            t = self._temp(D)
            self._emit("itof", ty=D, dest=t, args=(v,))
            return t
        if fr == D and to_ty == I:
            if isinstance(v, FloatConst):
                return IntConst(round(v.v))
            t = self._temp(I)
            self._emit("ftoi", ty=I, dest=t, args=(v,))
            return t
        raise AssertionError(f"cannot coerce {fr} -> {to_ty}")

    # ---- 変数スロットの解決 -------------------------------------------------

    def _var_slot(self, node: A.VarRef) -> VarSlot:
        """解決済み VarRef から格納先スロットを得る。"""
        kind = node.resolved
        if kind == "ret":
            return self.ret_slot
        if kind == "global":
            return VarSlot("V_" + mangle(node.name), node.ty, is_global=True)
        if kind == "local":
            return VarSlot("V_" + mangle(node.name), node.ty, is_global=False)
        raise AssertionError(f"unexpected varref kind {kind}")

    def _arr_slot(self, info: ArrayInfo) -> VarSlot:
        """配列ハンドル (int64 の ID) を保持するスロット。"""
        return VarSlot("A_" + mangle(info.name), I, is_global=info.is_global)

    # ==================================================================
    # エントリポイント
    # ==================================================================

    def generate(self) -> IRProgram:
        # DATA 項目はプログラム定数としてそのまま IR に載せる。
        # バックエンドが nb_data_items / nb_data_count シンボルを定義し、
        # ランタイムの READ 実装が参照する。
        self.ir.data_items = list(self.info.data_items)

        # 大域変数スロットの一覧 (バックエンドがデータ領域を確保する)
        for name, ty in self.info.global_vars.items():
            self.ir.globals.append(VarSlot("V_" + mangle(name), ty, True))
        for name, ainfo in self.info.global_arrays.items():
            self.ir.globals.append(VarSlot("A_" + mangle(name), I, True))

        # メイン → 各手続き の順に関数を生成
        self.ir.funcs.append(self._gen_main())
        for proc in self.prog.procs:
            self.ir.funcs.append(self._gen_proc(proc))
        return self.ir

    def _gen_main(self) -> IRFunc:
        """メインプログラム → 関数 nb_basic_main()。"""
        self.body = []
        self.cur_proc = None
        self.ret_slot = None
        self.gosub_sites = []
        self.needs_dispatch = False

        # --- 大域変数とメインローカル変数のゼロ初期化 (仕様書 §3.3:
        #     数値は 0、文字列は ""、配列ハンドルは 0 = 未確保) ---
        for slot in self.ir.globals:
            self._emit_zero_init(slot)
        for name, ty in self.info.main_scope.vars.items():
            self._emit_zero_init(VarSlot("V_" + mangle(name), ty, False))

        self._gen_stmts(self.prog.main_body)
        self._emit("ret")
        self._gen_gosub_dispatcher()

        return IRFunc(name="nb_basic_main", params=[], ret_ty=None,
                      body=self.body)

    def _gen_proc(self, proc: A.ProcDef) -> IRFunc:
        """SUB/FUNCTION → 関数 nbu_<名前>。"""
        self.body = []
        pinfo = self.info.procs[proc.name]
        self.cur_proc = pinfo
        self.gosub_sites = []
        self.needs_dispatch = False
        self.loop_stack = []

        params = [VarSlot("V_" + mangle(p.name), p.ty, False)
                  for p in proc.params]
        param_names = {p.name for p in proc.params}

        # FUNCTION は戻り値スロット RET を持ち、末尾の共通脱出ラベル
        # __exit で `ret RET` する。EXIT FUNCTION / RETURN 式 はここへ跳ぶ。
        self.exit_label = self._label("exit")
        if proc.is_function:
            self.ret_slot = VarSlot("RET", proc.ret_type, False)
            self._emit_zero_init(self.ret_slot)
        else:
            self.ret_slot = None

        # ローカル変数のゼロ初期化 (仮引数は呼び出し側の値なので除く)
        scope = self.info.proc_scopes[proc.name]
        for name, ty in scope.vars.items():
            if name not in param_names:
                self._emit_zero_init(VarSlot("V_" + mangle(name), ty, False))
        for name in scope.arrays:
            self._emit_zero_init(VarSlot("A_" + mangle(name), I, False))

        self._gen_stmts(proc.body)

        self._emit("label", extra=self.exit_label)
        if proc.is_function:
            self._emit("ret", args=(self.ret_slot,))
        else:
            self._emit("ret")
        self._gen_gosub_dispatcher()

        return IRFunc(name="nbu_" + mangle(proc.name), params=params,
                      ret_ty=proc.ret_type if proc.is_function else None,
                      body=self.body)

    def _emit_zero_init(self, slot: VarSlot) -> None:
        if slot.ty == S:
            self._emit("mov", ty=S, dest=slot,
                       args=(self.ir.intern_string(""),))
        elif slot.ty == D:
            self._emit("mov", ty=D, dest=slot, args=(FloatConst(0.0),))
        else:
            self._emit("mov", ty=I, dest=slot, args=(IntConst(0),))

    def _gen_gosub_dispatcher(self) -> None:
        """関数末尾の GOSUB 復帰ディスパッチャ (モジュール先頭コメント参照)。

        __gosub_dispatch:
            id = nb_gosub_pop()          ; スタックが空なら実行時エラー
            if id == <ID1> goto <復帰1>
            if id == <ID2> goto <復帰2>
            ...
        """
        if not self.gosub_sites and not self.needs_dispatch:
            return
        self._emit("label", extra="__gosub_dispatch")
        rid = self._call("nb_gosub_pop", (), I)
        for site_id, ret_label in self.gosub_sites:
            t = self._temp(I)
            self._emit("cmp", ty=I, dest=t, args=(rid, IntConst(site_id)),
                       extra="EQ")
            self._emit("jnz", args=(t,), extra=ret_label)
        # ここに来るのは論理的に不可能 (ID は自分の関数の GOSUB しか積まれ
        # ない) だが、安全のためエラーで落とす。
        self._call("nb_fatal_bad_return", (), None)
        self._emit("ret")

    # ==================================================================
    # 文の生成
    # ==================================================================

    def _gen_stmts(self, body: list[A.Stmt]) -> None:
        for st in body:
            method = getattr(self, "_g_" + type(st).__name__)
            method(st)

    # ---- ラベル・ジャンプ ---------------------------------------------------

    def _g_LabelStmt(self, st: A.LabelStmt) -> None:
        self._emit("label", extra="L_" + st.name)

    def _g_GotoStmt(self, st: A.GotoStmt) -> None:
        self._emit("jmp", extra="L_" + st.target)

    def _g_GosubStmt(self, st: A.GosubStmt) -> None:
        # GOSUB 地点 ID を払い出し、復帰ラベルを直後に置く
        self.gosub_id += 1
        sid = self.gosub_id
        ret_label = self._label(f"gosub_ret{sid}")
        self._call("nb_gosub_push", (IntConst(sid),), None)
        self._emit("jmp", extra="L_" + st.target)
        self._emit("label", extra=ret_label)
        self.gosub_sites.append((sid, ret_label))

    def _g_ReturnStmt(self, st: A.ReturnStmt) -> None:
        if st.value is not None:
            # FUNCTION の値付き RETURN: RET に代入して共通脱出点へ
            v = self._coerce(self._expr(st.value), self.ret_slot.ty)
            self._emit("mov", ty=self.ret_slot.ty, dest=self.ret_slot,
                       args=(v,))
            self._emit("jmp", extra=self.exit_label)
        else:
            # GOSUB からの復帰: ディスパッチャへ
            self.needs_dispatch = True
            self._emit("jmp", extra="__gosub_dispatch")

    def _g_EndStmt(self, st: A.EndStmt) -> None:
        # ランタイム側で後始末して exit する (コード省略時は 0)
        if st.code is None:
            self._call("nb_end", (), None)
        else:
            v = self._coerce(self._expr(st.code), I)
            self._call("nb_end_code", (v,), None)

    # ---- 代入・宣言 ----------------------------------------------------------

    def _g_AssignStmt(self, st: A.AssignStmt) -> None:
        v = self._expr(st.value)
        self._store(st.target, v)

    def _store(self, target: A.Expr, v: Value) -> None:
        """値 v を代入先 (スカラー変数 or 配列要素) に格納する。"""
        if isinstance(target, A.VarRef):
            slot = self._var_slot(target)
            self._emit("mov", ty=slot.ty, dest=slot,
                       args=(self._coerce(v, slot.ty),))
            return
        if isinstance(target, A.ArrayRef):
            info: ArrayInfo = target.info
            handle = self._arr_slot(info)
            idx = tuple(self._coerce(self._expr(ix), I)
                        for ix in target.indices)
            elem = self._coerce(v, info.elem_ty)
            sym = f"nb_arr_set{info.ndims}_{_TYSFX[info.elem_ty]}"
            self._call(sym, (handle, *idx, elem), None)
            return
        raise AssertionError("bad store target")

    def _g_DimStmt(self, st: A.DimStmt) -> None:
        # スカラーの DIM は宣言だけ (初期化は関数先頭で済み)。
        # 配列の DIM は実行文: この位置で確保する (仕様書 §3.6)。
        if st.array_info is None:
            return
        info: ArrayInfo = st.array_info
        dims = tuple(self._coerce(self._expr(d), I) for d in st.dims)
        kind = IntConst(_ARR_KIND[info.elem_ty])
        handle = self._call(f"nb_arr_new{info.ndims}", (kind, *dims), I)
        slot = self._arr_slot(info)
        self._emit("mov", ty=I, dest=slot, args=(handle,))

    def _g_ConstStmt(self, st: A.ConstStmt) -> None:
        pass  # 定数は参照箇所で即値化される

    def _g_SwapStmt(self, st: A.SwapStmt) -> None:
        # 両方読んでから両方書く。配列添字の式も先に評価されるため、
        # SWAP A(I), A(J) も正しく動く。
        va = self._expr(st.a)
        vb = self._expr(st.b)
        self._store(st.a, vb)
        self._store(st.b, va)

    # ---- 入出力 ---------------------------------------------------------------

    def _g_PrintStmt(self, st: A.PrintStmt) -> None:
        # PRINT #n はランタイムの「現在の出力チャネル」を切り替えてから
        # 通常の print 関数群を使い、終わったら画面 (チャネル 0) へ戻す。
        # チャネルはコンパイル時ではなく実行時の状態なので、既存の
        # nb_print_* をファイル対応に一般化するだけで済む (nbrt.c 参照)。
        if st.channel is not None:
            ch = self._coerce(self._expr(st.channel), I)
            self._call("nb_set_channel", (ch,), None)
        for item in st.items:
            v = self._expr(item.expr)
            self._call(f"nb_print_{_TYSFX[value_type(v)]}", (v,), None)
            if item.sep == ",":
                self._call("nb_print_tab", (), None)   # 次の 14 桁ゾーンへ
        if not st.trailing_sep:
            self._call("nb_print_nl", (), None)
        if st.channel is not None:
            self._call("nb_set_channel", (IntConst(0),), None)

    def _g_InputStmt(self, st: A.InputStmt) -> None:
        if st.channel is not None:
            # ファイルからの INPUT #: 項目単位で読む (行の途中でもよい)
            ch = self._coerce(self._expr(st.channel), I)
            for tgt in st.targets:
                v = self._call(f"nb_finput_{_TYSFX[tgt.ty]}", (ch,), tgt.ty)
                self._store(tgt, v)
            return
        if st.prompt is not None:
            self._call("nb_print_str",
                       (self.ir.intern_string(st.prompt),), None)
        # nb_input_begin が "? " を出して新しい行を読み込む。
        # 複数変数はその行のカンマ区切り値から順に取り出す (仕様書 §9.2)。
        self._call("nb_input_begin", (), None)
        for tgt in st.targets:
            v = self._call(f"nb_input_{_TYSFX[tgt.ty]}", (), tgt.ty)
            self._store(tgt, v)

    def _g_LineInputStmt(self, st: A.LineInputStmt) -> None:
        if st.channel is not None:
            ch = self._coerce(self._expr(st.channel), I)
            v = self._call("nb_fline_input", (ch,), S)
        else:
            if st.prompt is not None:
                self._call("nb_print_str",
                           (self.ir.intern_string(st.prompt),), None)
            v = self._call("nb_line_input", (), S)
        self._store(st.target, v)

    def _g_OpenStmt(self, st: A.OpenStmt) -> None:
        # モードコードはランタイムとの規約: 0=INPUT, 1=OUTPUT, 2=APPEND
        mode = {"INPUT": 0, "OUTPUT": 1, "APPEND": 2}[st.mode]
        path = self._expr(st.path)
        num = self._coerce(self._expr(st.filenum), I)
        self._call("nb_open", (path, IntConst(mode), num), None)

    def _g_CloseStmt(self, st: A.CloseStmt) -> None:
        if not st.filenums:
            self._call("nb_close_all", (), None)
            return
        for e in st.filenums:
            self._call("nb_close", (self._coerce(self._expr(e), I),), None)

    def _g_ClsStmt(self, st: A.ClsStmt) -> None:
        self._call("nb_cls", (), None)

    def _g_LocateStmt(self, st: A.LocateStmt) -> None:
        row = self._coerce(self._expr(st.row), I)
        col = self._coerce(self._expr(st.col), I) if st.col is not None \
            else IntConst(1)
        self._call("nb_locate", (row, col), None)

    def _g_ColorStmt(self, st: A.ColorStmt) -> None:
        # 背景省略は -1 (変更しない) をランタイムへの規約とする
        fg = self._coerce(self._expr(st.fg), I)
        bg = self._coerce(self._expr(st.bg), I) if st.bg is not None \
            else IntConst(-1)
        self._call("nb_color", (fg, bg), None)

    def _g_SleepStmt(self, st: A.SleepStmt) -> None:
        if st.seconds is None:
            self._call("nb_waitkey", (), None)   # 古典の SLEEP = キー待ち
        else:
            v = self._coerce(self._expr(st.seconds), D)
            self._call("nb_sleep", (v,), None)

    def _g_ReadStmt(self, st: A.ReadStmt) -> None:
        for tgt in st.targets:
            v = self._call(f"nb_read_{_TYSFX[tgt.ty]}", (), tgt.ty)
            self._store(tgt, v)

    def _g_RestoreStmt(self, st: A.RestoreStmt) -> None:
        self._call("nb_restore", (IntConst(st.data_index),), None)

    def _g_DataStmt(self, st: A.DataStmt) -> None:
        pass  # 実行文ではない (項目は IRProgram.data_items に収集済み)

    def _g_RandomizeStmt(self, st: A.RandomizeStmt) -> None:
        if st.seed is None:
            self._call("nb_randomize_timer", (), None)
        else:
            v = self._coerce(self._expr(st.seed), D)
            self._call("nb_randomize", (v,), None)

    # ---- 制御構造 --------------------------------------------------------------

    def _cond_value(self, e: A.Expr) -> Value:
        """条件式を「0 か非 0 かで判定できる INTEGER 値」にする。
        DOUBLE の条件は `<> 0.0` の比較で真理値化する。"""
        v = self._expr(e)
        if value_type(v) == D:
            t = self._temp(I)
            self._emit("cmp", ty=D, dest=t, args=(v, FloatConst(0.0)),
                       extra="NE")
            return t
        return v

    def _g_IfStmt(self, st: A.IfStmt) -> None:
        """IF/ELSEIF/ELSE を条件ジャンプの連鎖に展開する:

            <c1> が偽なら next1 へ
            <then 本体> ; jmp end
        next1:
            <c2> が偽なら next2 へ ...
        nextN:
            <else 本体>
        end:
        """
        end = self._label("if_end")
        for cond, body in st.branches:
            nxt = self._label("if_next")
            c = self._cond_value(cond)
            self._emit("jz", args=(c,), extra=nxt)
            self._gen_stmts(body)
            self._emit("jmp", extra=end)
            self._emit("label", extra=nxt)
        if st.else_body:
            self._gen_stmts(st.else_body)
        self._emit("label", extra=end)

    def _g_WhileStmt(self, st: A.WhileStmt) -> None:
        top = self._label("while_top")
        exit_l = self._label("while_exit")
        self._emit("label", extra=top)
        c = self._cond_value(st.cond)
        self._emit("jz", args=(c,), extra=exit_l)
        self.loop_stack.append(("WHILE", exit_l))
        self._gen_stmts(st.body)
        self.loop_stack.pop()
        self._emit("jmp", extra=top)
        self._emit("label", extra=exit_l)

    def _g_DoLoopStmt(self, st: A.DoLoopStmt) -> None:
        top = self._label("do_top")
        exit_l = self._label("do_exit")
        self._emit("label", extra=top)
        if st.pre_cond is not None:
            c = self._cond_value(st.pre_cond)
            # WHILE: 偽なら脱出 / UNTIL: 真なら脱出
            self._emit("jnz" if st.pre_negate else "jz",
                       args=(c,), extra=exit_l)
        self.loop_stack.append(("DO", exit_l))
        self._gen_stmts(st.body)
        self.loop_stack.pop()
        if st.post_cond is not None:
            c = self._cond_value(st.post_cond)
            # LOOP WHILE: 真なら継続 / LOOP UNTIL: 偽なら継続
            self._emit("jz" if st.post_negate else "jnz",
                       args=(c,), extra=top)
        else:
            self._emit("jmp", extra=top)
        self._emit("label", extra=exit_l)

    def _g_ForStmt(self, st: A.ForStmt) -> None:
        """FOR の展開 (仕様書 §6.5)。終了値と STEP はループ突入時に
        一度だけ評価して隠しスロットに保存する (本体内での変更は無効)。
        STEP の符号で継続条件が変わるため毎回符号を判定する:

            var = start ; end' = end ; step' = step
        check:
            if step' >= 0:  var <= end' なら body へ、さもなくば exit へ
            else         :  var >= end' なら body へ、さもなくば exit へ
        body:
            <本体>
            var = var + step' ; jmp check
        exit:
        """
        var_slot = self._var_slot(st.var)
        vty = var_slot.ty          # ループ演算は変数の型で行う

        n = self.label_id + 1      # 隠しスロット名を一意にするための番号
        end_slot = VarSlot(f"T_for{n}_end", vty, False)
        step_slot = VarSlot(f"T_for{n}_step", vty, False)

        v = self._coerce(self._expr(st.start), vty)
        self._emit("mov", ty=vty, dest=var_slot, args=(v,))
        v = self._coerce(self._expr(st.end), vty)
        self._emit("mov", ty=vty, dest=end_slot, args=(v,))
        if st.step is None:
            one = IntConst(1) if vty == I else FloatConst(1.0)
            self._emit("mov", ty=vty, dest=step_slot, args=(one,))
        else:
            v = self._coerce(self._expr(st.step), vty)
            self._emit("mov", ty=vty, dest=step_slot, args=(v,))

        check = self._label("for_check")
        neg = self._label("for_neg")
        body_l = self._label("for_body")
        exit_l = self._label("for_exit")

        self._emit("label", extra=check)
        zero = IntConst(0) if vty == I else FloatConst(0.0)
        t = self._temp(I)
        self._emit("cmp", ty=vty, dest=t, args=(step_slot, zero), extra="GE")
        self._emit("jz", args=(t,), extra=neg)
        t2 = self._temp(I)
        self._emit("cmp", ty=vty, dest=t2, args=(var_slot, end_slot),
                   extra="LE")
        self._emit("jnz", args=(t2,), extra=body_l)
        self._emit("jmp", extra=exit_l)
        self._emit("label", extra=neg)
        t3 = self._temp(I)
        self._emit("cmp", ty=vty, dest=t3, args=(var_slot, end_slot),
                   extra="GE")
        self._emit("jz", args=(t3,), extra=exit_l)

        self._emit("label", extra=body_l)
        self.loop_stack.append(("FOR", exit_l))
        self._gen_stmts(st.body)
        self.loop_stack.pop()
        t4 = self._temp(vty)
        self._emit("add", ty=vty, dest=t4, args=(var_slot, step_slot))
        self._emit("mov", ty=vty, dest=var_slot, args=(t4,))
        self._emit("jmp", extra=check)
        self._emit("label", extra=exit_l)

    def _g_ExitStmt(self, st: A.ExitStmt) -> None:
        if st.kind in ("SUB", "FUNCTION"):
            self._emit("jmp", extra=self.exit_label)
            return
        # 最も内側の対応するループの脱出ラベルへ
        for kind, exit_l in reversed(self.loop_stack):
            if kind == st.kind:
                self._emit("jmp", extra=exit_l)
                return
        raise AssertionError("EXIT outside loop (analyzer should catch)")

    def _g_SelectStmt(self, st: A.SelectStmt) -> None:
        """SELECT CASE の展開。対象式は一度だけ評価して隠しスロットに置き、
        各 CASE 節の照合条件を順に試す。最初に一致した節の本体だけを
        実行する (仕様書 §6.4)。"""
        subj = self._expr(st.subject)
        n = self.label_id + 1
        subj_slot = VarSlot(f"T_sel{n}", value_type(subj), False)
        self._emit("mov", ty=subj_slot.ty, dest=subj_slot, args=(subj,))

        end = self._label("select_end")
        for cl in st.clauses:
            nxt = self._label("case_next")
            body_l = self._label("case_body")
            if cl.tests:   # 通常の CASE: どれかの条件が成立すれば本体へ
                for test in cl.tests:
                    c = self._case_test(subj_slot, test)
                    self._emit("jnz", args=(c,), extra=body_l)
                self._emit("jmp", extra=nxt)
            # CASE ELSE は無条件で本体へ (tests が空 = fallthrough)
            self._emit("label", extra=body_l)
            self._gen_stmts(cl.body)
            self._emit("jmp", extra=end)
            self._emit("label", extra=nxt)
        self._emit("label", extra=end)

    def _case_test(self, subj: VarSlot, test: tuple) -> Value:
        """CASE 照合条件 1 個を真理値 (INTEGER) に評価する。"""
        if test[0] == "EQ":
            return self._compare("EQ", subj, self._expr(test[1]))
        if test[0] == "RANGE":
            lo = self._compare("GE", subj, self._expr(test[1]))
            hi = self._compare("LE", subj, self._expr(test[2]))
            t = self._temp(I)
            self._emit("and", ty=I, dest=t, args=(lo, hi))
            return t
        # ("REL", op, expr) : CASE IS >= 100 など
        op_map = {"=": "EQ", "<>": "NE", "<": "LT",
                  "<=": "LE", ">": "GT", ">=": "GE"}
        return self._compare(op_map[test[1]], subj, self._expr(test[2]))

    # ---- 手続き呼び出し ----------------------------------------------------------

    def _g_CallStmt(self, st: A.CallStmt) -> None:
        proc: ProcInfo = st.proc
        args = tuple(self._coerce(self._expr(a), p.ty)
                     for a, p in zip(st.args, proc.params))
        # FUNCTION を文として呼んだ場合は戻り値を捨てる
        self._call("nbu_" + mangle(proc.name), args,
                   proc.ret_ty if proc.is_function else None)

    # ==================================================================
    # 式の生成
    # ==================================================================

    def _expr(self, e: A.Expr) -> Value:
        if isinstance(e, A.NumLit):
            return (IntConst(e.value) if isinstance(e.value, int)
                    else FloatConst(e.value))

        if isinstance(e, A.StrLit):
            return self.ir.intern_string(e.value)

        if isinstance(e, A.VarRef):
            if e.resolved == "const":
                # 名前付き定数は参照箇所で即値化する
                cv = e.const_value
                if isinstance(cv, str):
                    return self.ir.intern_string(cv)
                if e.ty == I:
                    return IntConst(int(cv))
                return FloatConst(float(cv))
            # 変数は必ず一時レジスタへコピーしてから使う。
            # これにより「左から右」の評価順が保たれる (モジュール先頭
            # コメント参照)。無駄なコピーは最適化器が除去する。
            slot = self._var_slot(e)
            t = self._temp(slot.ty)
            self._emit("mov", ty=slot.ty, dest=t, args=(slot,))
            return t

        if isinstance(e, A.ArrayRef):
            info: ArrayInfo = e.info
            handle = self._arr_slot(info)
            idx = tuple(self._coerce(self._expr(ix), I) for ix in e.indices)
            sym = f"nb_arr_get{info.ndims}_{_TYSFX[info.elem_ty]}"
            return self._call(sym, (handle, *idx), info.elem_ty)

        if isinstance(e, A.FuncCall):
            if e.builtin:
                return self._builtin_call(e)
            proc: ProcInfo = e.proc
            args = tuple(self._coerce(self._expr(a), p.ty)
                         for a, p in zip(e.args, proc.params))
            return self._call("nbu_" + mangle(proc.name), args, proc.ret_ty)

        if isinstance(e, A.BinOp):
            return self._binop(e)

        if isinstance(e, A.UnOp):
            v = self._expr(e.operand)
            if e.op == "-":
                t = self._temp(value_type(v))
                self._emit("neg", ty=t.ty, dest=t, args=(v,))
                return t
            # NOT: 整数へ丸めて 64bit ビット否定 (真理値 -1 ↔ 0 が反転する)
            v = self._coerce(v, I)
            t = self._temp(I)
            self._emit("not", ty=I, dest=t, args=(v,))
            return t

        raise AssertionError(f"unknown expr {e!r}")

    # ---- 二項演算 ------------------------------------------------------------

    def _binop(self, e: A.BinOp) -> Value:
        op = e.op

        # 文字列連結 (& は数値を文字列化してから連結、仕様書 §5.2)
        if op == "&" or (op == "+" and e.ty == S):
            a = self._to_string(self._expr(e.left))
            b = self._to_string(self._expr(e.right))
            return self._call("nb_concat", (a, b), S)

        # 比較 (結果は真理値: 真 = -1, 偽 = 0)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            op_map = {"=": "EQ", "<>": "NE", "<": "LT",
                      "<=": "LE", ">": "GT", ">=": "GE"}
            return self._compare(op_map[op],
                                 self._expr(e.left), self._expr(e.right))

        # 論理/ビット演算 (被演算子は整数へ丸める)
        if op in ("AND", "OR", "XOR"):
            a = self._coerce(self._expr(e.left), I)
            b = self._coerce(self._expr(e.right), I)
            t = self._temp(I)
            self._emit(op.lower(), ty=I, dest=t, args=(a, b))
            return t

        # 実数除算・べき乗は常に DOUBLE
        if op == "/":
            a = self._coerce(self._expr(e.left), D)
            b = self._coerce(self._expr(e.right), D)
            t = self._temp(D)
            self._emit("fdiv", ty=D, dest=t, args=(a, b))
            return t
        if op == "^":
            a = self._coerce(self._expr(e.left), D)
            b = self._coerce(self._expr(e.right), D)
            return self._call("nb_pow", (a, b), D)

        # 整数除算・剰余はゼロ除算検査のためランタイム呼び出し
        if op == "\\":
            a = self._coerce(self._expr(e.left), I)
            b = self._coerce(self._expr(e.right), I)
            return self._call("nb_idiv", (a, b), I)
        if op == "MOD":
            a = self._coerce(self._expr(e.left), I)
            b = self._coerce(self._expr(e.right), I)
            return self._call("nb_imod", (a, b), I)

        # 加減乗: 両方 INTEGER なら整数演算、さもなくば DOUBLE 演算
        assert op in ("+", "-", "*")
        ty = e.ty
        a = self._coerce(self._expr(e.left), ty)
        b = self._coerce(self._expr(e.right), ty)
        t = self._temp(ty)
        ins = {"+": "add", "-": "sub", "*": "mul"}[op]
        self._emit(ins, ty=ty, dest=t, args=(a, b))
        return t

    def _compare(self, cmp_kind: str, a: Value, b: Value) -> Value:
        """比較を発行する。文字列は nb_str_cmp (C の strcmp 相当) を
        呼んでから結果を 0 と比較する 2 段構えに低水準化する。"""
        ta, tb = value_type(a), value_type(b)
        if ta == S or tb == S:
            c = self._call("nb_str_cmp", (a, b), I)
            t = self._temp(I)
            self._emit("cmp", ty=I, dest=t, args=(c, IntConst(0)),
                       extra=cmp_kind)
            return t
        # 数値: どちらかが DOUBLE なら両方 DOUBLE に揃える
        ty = D if D in (ta, tb) else I
        a = self._coerce(a, ty)
        b = self._coerce(b, ty)
        t = self._temp(I)
        self._emit("cmp", ty=ty, dest=t, args=(a, b), extra=cmp_kind)
        return t

    def _to_string(self, v: Value) -> Value:
        """& 演算子のための文字列化。STR$ と違い正数に先頭空白を
        付けないコンパクトな表記を使う (仕様書 §5.2)。"""
        ty = value_type(v)
        if ty == S:
            return v
        sym = "nb_tostr_i64" if ty == I else "nb_tostr_f64"
        return self._call(sym, (v,), S)

    # ---- 組込関数 ------------------------------------------------------------

    def _builtin_call(self, e: A.FuncCall) -> Value:
        """組込関数をランタイム呼び出し (または単一 IR 命令) に変換する。
        シグネチャ検査は意味解析器が済ませているので、ここでは型に応じた
        ランタイム関数の選択と引数の暗黙変換だけを行う。"""
        name = e.name

        # --- 引数なし ---
        if name == "TIMER":
            return self._call("nb_timer", (), D)
        if name == "INKEY$":
            return self._call("nb_inkey", (), S)
        if name == "COMMAND$":
            # 引数なし = 0 (全引数を空白区切りで連結) をランタイム規約に
            if e.args:
                n = self._coerce(self._expr(e.args[0]), I)
            else:
                n = IntConst(0)
            return self._call("nb_command", (n,), S)
        if name == "RND":
            # RND(x) の引数は古典 BASIC との互換のために受け付けるが、
            # 副作用のため評価だけして値は無視する (仕様書 §10.4)。
            if e.args:
                self._expr(e.args[0])
            return self._call("nb_rnd", (), D)

        args = [self._expr(a) for a in e.args]

        # --- 多相: 引数の型で実装を選ぶ ---
        if name == "ABS":
            ty = value_type(args[0])
            return self._call(f"nb_abs_{_TYSFX[ty]}", (args[0],), ty)
        if name == "SGN":
            ty = value_type(args[0])
            return self._call(f"nb_sgn_{_TYSFX[ty]}", (args[0],), I)
        if name in ("INT", "CINT", "FIX"):
            if value_type(args[0]) == I:
                return args[0]              # 整数はそのまま (恒等変換)
            if name == "CINT":
                # 最近接丸めは IR の ftoi 命令そのもの
                t = self._temp(I)
                self._emit("ftoi", ty=I, dest=t, args=(args[0],))
                return t
            sym = "nb_int_floor" if name == "INT" else "nb_fix"
            return self._call(sym, (args[0],), I)
        if name == "STR$":
            ty = value_type(args[0])
            return self._call(f"nb_str_from_{_TYSFX[ty]}", (args[0],), S)

        # --- 可変引数 ---
        if name == "INSTR":
            if len(args) == 3:
                start = self._coerce(args[0], I)
                return self._call("nb_instr", (start, args[1], args[2]), I)
            return self._call("nb_instr", (IntConst(1), args[0], args[1]), I)
        if name == "MID$":
            s = args[0]
            start = self._coerce(args[1], I)
            # 長さ省略は「末尾まで」= -1 をランタイムへの規約とする
            length = self._coerce(args[2], I) if len(args) == 3 \
                else IntConst(-1)
            return self._call("nb_mid", (s, start, length), S)

        # --- 固定シグネチャ: 表に従って引数を変換して呼ぶだけ ---
        table = {
            "SQR": ("nb_sqr", (D,), D), "SIN": ("nb_sin", (D,), D),
            "COS": ("nb_cos", (D,), D), "TAN": ("nb_tan", (D,), D),
            "ATN": ("nb_atn", (D,), D), "LOG": ("nb_log", (D,), D),
            "EXP": ("nb_exp", (D,), D),
            "LEN": ("nb_len", (S,), I), "ASC": ("nb_asc", (S,), I),
            "EOF": ("nb_eof", (I,), I),
            "VAL": ("nb_val", (S,), D), "CHR$": ("nb_chr", (I,), S),
            "LEFT$": ("nb_left", (S, I), S),
            "RIGHT$": ("nb_right", (S, I), S),
            "UCASE$": ("nb_ucase", (S,), S),
            "LCASE$": ("nb_lcase", (S,), S),
            "SPACE$": ("nb_space", (I,), S),
        }
        sym, ptys, rty = table[name]
        conv = tuple(self._coerce(a, t) for a, t in zip(args, ptys))
        return self._call(sym, conv, rty)


def generate(program: A.Program, info: ProgramInfo) -> IRProgram:
    """モジュールの公開エントリポイント。"""
    return IRGen(program, info).generate()
