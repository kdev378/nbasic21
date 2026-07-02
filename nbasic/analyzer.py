"""
analyzer.py — 意味解析器 (AST → 型注釈付き AST + 記号情報)
==========================================================

構文解析済みの AST を検査・注釈して、IR 生成器がためらいなく
コードを吐ける状態にする。仕事は次の 6 つ:

1. **記号表の構築**
   変数・配列・定数・手続き (SUB/FUNCTION) を登録する。
   スコープ規則 (仕様書 §8):
     - 先頭レベルで DIM/CONST された名前は「大域」— 手続きからも見える。
     - 先頭レベルで代入によって暗黙に作られた変数はメイン専用。
     - 手続き内の変数は (仮引数を含め) すべてローカル。
     - スカラーと配列は別の名前空間 (A と A() は共存できる)。

2. **曖昧ノードの解決**
   構文上区別できない `名前(引数)` (IndexOrCall) を、記号表を引いて
   ArrayRef (配列参照) か FuncCall (関数呼び出し) に置き換える。
   引数なしで呼べる組込関数 (RND, TIMER) は VarRef からも解決する。

3. **型検査と型注釈**
   すべての式ノードに .ty (Type) を書き込む。数値型どうしは暗黙変換
   (仕様書 §3.4) を認め、実際の変換命令は IR 生成器が挿入する。

4. **制御フローの妥当性検査**
   GOTO/GOSUB のターゲット存在、EXIT 文の位置、RETURN 式の位置など。

5. **定数式の畳み込み**
   CONST の右辺をコンパイル時に評価する。

6. **DATA 文の収集**
   プログラム順に DATA 項目を集め、RESTORE のターゲットを
   「データ表の添字」に解決する。

解析結果はノードへの属性書き込み (expr.ty, node.resolved など) と、
戻り値の ProgramInfo にまとめて IR 生成器へ渡す。
"""

from __future__ import annotations
from dataclasses import dataclass, field

from .errors import CompileError, SourcePos
from . import ast_nodes as A
from .ast_nodes import Type


def _is_num(t: Type) -> bool:
    return t in (Type.INTEGER, Type.DOUBLE)


# --------------------------------------------------------------------------
# 組込関数表
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BuiltinSig:
    """組込関数のシグネチャ。

    params : 仮引数型のリスト。呼び出し側の数値型は暗黙変換される。
             None は「多相 (ABS のように引数型に依存)」を表し、
             analyzer/irgen が個別に処理する。
    ret    : 戻り値型。None は多相。
    min_args / max_args : 引数個数の範囲 (省略可能引数のため)。
    """
    params: tuple | None
    ret: Type | None
    min_args: int
    max_args: int


I, D, S = Type.INTEGER, Type.DOUBLE, Type.STRING

# 名前 → シグネチャ。名前は大文字・サフィックス込み (CHR$ など)。
BUILTINS: dict[str, BuiltinSig] = {
    # --- 数値 (多相: 引数の型を保つ) ---
    "ABS":    BuiltinSig(None, None, 1, 1),
    "SGN":    BuiltinSig(None, I, 1, 1),
    # --- 丸め (DOUBLE → INTEGER。INTEGER 引数はそのまま) ---
    "INT":    BuiltinSig((D,), I, 1, 1),   # 床関数 (負の無限大方向)
    "CINT":   BuiltinSig((D,), I, 1, 1),   # 最近接丸め
    "FIX":    BuiltinSig((D,), I, 1, 1),   # ゼロ方向切り捨て
    # --- 数学関数 (常に DOUBLE) ---
    "SQR":    BuiltinSig((D,), D, 1, 1),
    "SIN":    BuiltinSig((D,), D, 1, 1),
    "COS":    BuiltinSig((D,), D, 1, 1),
    "TAN":    BuiltinSig((D,), D, 1, 1),
    "ATN":    BuiltinSig((D,), D, 1, 1),
    "LOG":    BuiltinSig((D,), D, 1, 1),
    "EXP":    BuiltinSig((D,), D, 1, 1),
    # --- 乱数・時刻 ---
    "RND":    BuiltinSig((D,), D, 0, 1),   # 引数は互換性のため受けるが無視
    "TIMER":  BuiltinSig((), D, 0, 0),
    # --- 文字列 → 数値 ---
    "LEN":    BuiltinSig((S,), I, 1, 1),
    "ASC":    BuiltinSig((S,), I, 1, 1),
    "VAL":    BuiltinSig((S,), D, 1, 1),
    "INSTR":  BuiltinSig(None, I, 2, 3),   # INSTR([開始,] s1, s2)
    # --- 数値/文字列 → 文字列 ---
    "CHR$":   BuiltinSig((I,), S, 1, 1),
    "STR$":   BuiltinSig(None, S, 1, 1),   # 引数は INTEGER/DOUBLE どちらでも
    "LEFT$":  BuiltinSig((S, I), S, 2, 2),
    "RIGHT$": BuiltinSig((S, I), S, 2, 2),
    "MID$":   BuiltinSig(None, S, 2, 3),   # MID$(s, 開始 [, 長さ])
    "UCASE$": BuiltinSig((S,), S, 1, 1),
    "LCASE$": BuiltinSig((S,), S, 1, 1),
    "SPACE$": BuiltinSig((I,), S, 1, 1),
}

# 引数なしで裸の識別子として書ける組込関数 (仕様書 §10.4)
ZERO_ARG_BUILTINS = frozenset({"RND", "TIMER"})


# --------------------------------------------------------------------------
# 記号情報
# --------------------------------------------------------------------------

@dataclass
class ArrayInfo:
    """配列 1 個の情報。resolved 属性として ArrayRef にも付与される。"""
    name: str          # ソース上の名前 (大文字・サフィックス込み)
    elem_ty: Type
    ndims: int         # 1 または 2
    is_global: bool
    pos: SourcePos


@dataclass
class ProcInfo:
    """SUB/FUNCTION 1 個のシグネチャ。"""
    name: str
    params: list[A.Param]
    is_function: bool
    ret_ty: Type | None
    node: A.ProcDef


@dataclass
class Scope:
    """1 つの変数スコープ (メインまたは手続き 1 個)。"""
    vars: dict[str, Type] = field(default_factory=dict)
    arrays: dict[str, ArrayInfo] = field(default_factory=dict)
    labels: set[str] = field(default_factory=set)


@dataclass
class ProgramInfo:
    """意味解析の結果一式。IR 生成器への入力。"""
    consts: dict[str, tuple[Type, object]] = field(default_factory=dict)
    global_vars: dict[str, Type] = field(default_factory=dict)   # 明示 DIM
    global_arrays: dict[str, ArrayInfo] = field(default_factory=dict)
    procs: dict[str, ProcInfo] = field(default_factory=dict)
    main_scope: Scope = field(default_factory=Scope)
    proc_scopes: dict[str, Scope] = field(default_factory=dict)
    data_items: list[str] = field(default_factory=list)
    # ラベル名 → そのラベル以降で最初に現れる DATA 項目の添字 (RESTORE 用)
    data_label_index: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------
# 意味解析器本体
# --------------------------------------------------------------------------

class Analyzer:
    def __init__(self, program: A.Program):
        self.prog = program
        self.info = ProgramInfo()
        # 解析中の文脈 (どのスコープ/手続き/ループの中か)
        self.scope: Scope = self.info.main_scope
        self.cur_proc: ProcInfo | None = None
        self.loop_stack: list[str] = []   # "FOR" / "WHILE" / "DO"

    # ==================================================================
    # エントリポイント
    # ==================================================================

    def analyze(self) -> ProgramInfo:
        # --- パス 1: 手続きシグネチャの登録 (前方参照を可能にする) ---
        for proc in self.prog.procs:
            self._register_proc(proc)

        # --- パス 2: ラベルと DATA の収集 ---
        # ラベルはスコープ内ジャンプの妥当性検査のため先に全部集める。
        # DATA はプログラム順 (メイン→各手続きの順) に項目を数え上げ、
        # 各ラベル位置のデータ添字を記録して RESTORE を解決可能にする。
        self._collect_labels_and_data(self.prog.main_body, self.info.main_scope,
                                      allow_data=True)
        for proc in self.prog.procs:
            scope = Scope()
            self.info.proc_scopes[proc.name] = scope
            self._collect_labels_and_data(proc.body, scope, allow_data=False)

        # --- パス 3: メイン本体の解析 ---
        self.scope = self.info.main_scope
        self.cur_proc = None
        self._stmt_list(self.prog.main_body)

        # --- パス 4: 各手続き本体の解析 ---
        for proc in self.prog.procs:
            pinfo = self.info.procs[proc.name]
            scope = self.info.proc_scopes[proc.name]
            # 仮引数をローカル変数として登録
            for p in proc.params:
                if p.name in scope.vars:
                    raise CompileError(f"仮引数 '{p.name}' が重複しています", p.pos)
                scope.vars[p.name] = p.ty
            self.scope = scope
            self.cur_proc = pinfo
            self.loop_stack = []
            self._stmt_list(proc.body)

        return self.info

    # ==================================================================
    # パス 1: 手続き登録
    # ==================================================================

    def _register_proc(self, proc: A.ProcDef) -> None:
        if proc.name in self.info.procs:
            raise CompileError(f"SUB/FUNCTION '{proc.name}' が再定義されています",
                               proc.pos)
        if proc.name in BUILTINS:
            # 組込関数と同名のユーザー定義はユーザー側を優先する仕様も
            # ありうるが、混乱のもとなのでエラーにする (仕様書 §7.5)。
            raise CompileError(f"'{proc.name}' は組込関数の名前です", proc.pos)
        self.info.procs[proc.name] = ProcInfo(
            name=proc.name, params=proc.params,
            is_function=proc.is_function, ret_ty=proc.ret_type, node=proc)

    # ==================================================================
    # パス 2: ラベル・DATA 収集 (再帰的に全文を走査)
    # ==================================================================

    def _collect_labels_and_data(self, body: list[A.Stmt], scope: Scope,
                                 allow_data: bool) -> None:
        """文リストを (ブロックの中まで) 走査してラベルと DATA を集める。

        走査順はソースの実行文順と一致するので、
        「ラベル L の位置 = それまでに集まった DATA 項目数」を
        記録すれば RESTORE L の復帰位置になる。
        """
        for st in body:
            if isinstance(st, A.LabelStmt):
                if st.name in scope.labels:
                    raise CompileError(f"ラベル '{st.name}' が重複しています",
                                       st.pos)
                scope.labels.add(st.name)
                if allow_data:
                    self.info.data_label_index[st.name] = \
                        len(self.info.data_items)
            elif isinstance(st, A.DataStmt):
                if not allow_data:
                    raise CompileError(
                        "DATA 文はメインプログラムにのみ書けます (仕様書 §9.1)",
                        st.pos)
                self.info.data_items.extend(st.items)
            elif isinstance(st, A.IfStmt):
                for _, b in st.branches:
                    self._collect_labels_and_data(b, scope, allow_data)
                if st.else_body:
                    self._collect_labels_and_data(st.else_body, scope, allow_data)
            elif isinstance(st, (A.WhileStmt, A.ForStmt, A.DoLoopStmt)):
                self._collect_labels_and_data(st.body, scope, allow_data)
            elif isinstance(st, A.SelectStmt):
                for cl in st.clauses:
                    self._collect_labels_and_data(cl.body, scope, allow_data)

    # ==================================================================
    # 名前解決ヘルパ
    # ==================================================================

    def _default_type(self, name: str) -> Type:
        """サフィックスから型を決める。無ければ既定の DOUBLE (仕様書 §3.3)。"""
        return A.type_from_name(name) or Type.DOUBLE

    def _lookup_scalar(self, name: str, pos: SourcePos,
                       create: bool) -> tuple[str, Type]:
        """スカラー変数を解決する。戻り値は (種別, 型)。

        種別: "ret"    — FUNCTION 内での関数名 (戻り値変数)
              "local"  — 現在スコープのローカル変数
              "global" — 明示 DIM された大域変数
              "const"  — 名前付き定数
        create=True なら未知の名前を現在スコープに自動生成する
        (BASIC の伝統: 変数は宣言なしで使える。仕様書 §3.3)。
        """
        # (1) FUNCTION 自身の名前 = 戻り値変数
        if (self.cur_proc is not None and self.cur_proc.is_function
                and name == self.cur_proc.name):
            return ("ret", self.cur_proc.ret_ty)
        # (2) 現在スコープのローカル (メインでは「メインの変数」)
        if name in self.scope.vars:
            return ("local", self.scope.vars[name])
        # (3) 名前付き定数
        if name in self.info.consts:
            return ("const", self.info.consts[name][0])
        # (4) 明示 DIM された大域変数 (手続きの中からも見える)
        if name in self.info.global_vars:
            return ("global", self.info.global_vars[name])
        # (5) 自動生成
        if not create:
            raise CompileError(f"変数 '{name}' は未定義です", pos)
        ty = self._default_type(name)
        self.scope.vars[name] = ty
        return ("local", ty)

    def _lookup_array(self, name: str) -> ArrayInfo | None:
        """配列を解決する。ローカル → 大域の順。見つからなければ None。"""
        if name in self.scope.arrays:
            return self.scope.arrays[name]
        return self.info.global_arrays.get(name)

    # ==================================================================
    # 式の解析
    # ==================================================================
    #
    # 各メソッドは「解決済みのノード」を返す。IndexOrCall のように
    # ノードの種類が変わることがあるため、親は戻り値を書き戻すこと。

    def _expr(self, e: A.Expr) -> A.Expr:
        if isinstance(e, A.NumLit):
            e.ty = Type.INTEGER if isinstance(e.value, int) else Type.DOUBLE
            return e

        if isinstance(e, A.StrLit):
            e.ty = Type.STRING
            return e

        if isinstance(e, A.VarRef):
            return self._resolve_varref(e, create=True)

        if isinstance(e, A.IndexOrCall):
            return self._resolve_index_or_call(e)

        if isinstance(e, A.BinOp):
            e.left = self._expr(e.left)
            e.right = self._expr(e.right)
            e.ty = self._binop_type(e)
            return e

        if isinstance(e, A.UnOp):
            e.operand = self._expr(e.operand)
            t = e.operand.ty
            if e.op == "-":
                if not _is_num(t):
                    raise CompileError("単項 '-' は数値にのみ使えます", e.pos)
                e.ty = t
            else:  # NOT: 整数へ丸めてビット否定 (仕様書 §5.3)
                if not _is_num(t):
                    raise CompileError("NOT は数値にのみ使えます", e.pos)
                e.ty = Type.INTEGER
            return e

        raise AssertionError(f"unknown expr node {e!r}")

    def _resolve_varref(self, e: A.VarRef, create: bool) -> A.Expr:
        """裸の識別子。RND/TIMER は引数なし組込関数呼び出しに変換する。"""
        if e.name in ZERO_ARG_BUILTINS and not self._name_is_variable(e.name):
            call = A.FuncCall(e.pos, name=e.name, args=[], builtin=True)
            call.ty = BUILTINS[e.name].ret
            return call
        kind, ty = self._lookup_scalar(e.name, e.pos, create)
        e.ty = ty
        e.resolved = kind          # IR 生成器が参照する注釈
        if kind == "const":
            e.const_value = self.info.consts[e.name][1]
        return e

    def _name_is_variable(self, name: str) -> bool:
        """RND という名前の変数を作ってしまったプログラムのための逃げ道。
        既に変数として存在すれば変数を優先する。"""
        return (name in self.scope.vars or name in self.info.global_vars
                or name in self.info.consts)

    def _resolve_index_or_call(self, e: A.IndexOrCall) -> A.Expr:
        """`名前(引数...)` を配列参照・ユーザー関数・組込関数の順で解決。"""
        args = [self._expr(a) for a in e.args]

        # (1) 配列
        arr = self._lookup_array(e.name)
        if arr is not None:
            node = A.ArrayRef(e.pos, name=e.name, indices=args)
            self._check_array_ref(node, arr)
            return node

        # (2) ユーザー定義 FUNCTION
        proc = self.info.procs.get(e.name)
        if proc is not None:
            if not proc.is_function:
                raise CompileError(
                    f"SUB '{e.name}' は式の中では呼び出せません (CALL 文を使用)",
                    e.pos)
            node = A.FuncCall(e.pos, name=e.name, args=args, builtin=False)
            self._check_user_call_args(proc, node)
            node.ty = proc.ret_ty
            node.proc = proc
            return node

        # (3) 組込関数
        if e.name in BUILTINS:
            node = A.FuncCall(e.pos, name=e.name, args=args, builtin=True)
            node.ty = self._check_builtin_call(node)
            return node

        raise CompileError(f"'{e.name}' という配列・関数はありません", e.pos)

    def _check_array_ref(self, node: A.ArrayRef, arr: ArrayInfo) -> None:
        if len(node.indices) != arr.ndims:
            raise CompileError(
                f"配列 '{arr.name}' は {arr.ndims} 次元です "
                f"({len(node.indices)} 個の添字が指定されました)", node.pos)
        for ix in node.indices:
            if not _is_num(ix.ty):
                raise CompileError("配列の添字は数値でなければなりません",
                                   node.pos)
        node.ty = arr.elem_ty
        node.info = arr            # IR 生成器が参照する注釈

    def _check_user_call_args(self, proc: ProcInfo, node) -> None:
        """ユーザー手続き呼び出しの引数検査 (FuncCall / CallStmt 共用)。"""
        if len(node.args) != len(proc.params):
            raise CompileError(
                f"'{proc.name}' の引数は {len(proc.params)} 個です "
                f"({len(node.args)} 個渡されました)", node.pos)
        for a, p in zip(node.args, proc.params):
            self._check_assignable(p.ty, a, node.pos,
                                   what=f"引数 '{p.name}'")

    def _check_builtin_call(self, node: A.FuncCall) -> Type:
        """組込関数呼び出しの引数検査。戻り値型を返す。"""
        sig = BUILTINS[node.name]
        n = len(node.args)
        if not (sig.min_args <= n <= sig.max_args):
            raise CompileError(
                f"{node.name} の引数は {sig.min_args}〜{sig.max_args} 個です",
                node.pos)

        # --- 多相・可変引数の特別扱い ---
        if node.name in ("ABS", "SGN"):
            t = node.args[0].ty
            if not _is_num(t):
                raise CompileError(f"{node.name} の引数は数値です", node.pos)
            return t if node.name == "ABS" else Type.INTEGER
        if node.name == "STR$":
            if not _is_num(node.args[0].ty):
                raise CompileError("STR$ の引数は数値です", node.pos)
            return Type.STRING
        if node.name == "INSTR":
            # INSTR(s1, s2) または INSTR(開始位置, s1, s2)
            if n == 3:
                self._require_num(node.args[0], node.pos, "INSTR の開始位置")
                strs = node.args[1:]
            else:
                strs = node.args
            for a in strs:
                if a.ty != Type.STRING:
                    raise CompileError("INSTR の対象は文字列です", node.pos)
            return Type.INTEGER
        if node.name == "MID$":
            if node.args[0].ty != Type.STRING:
                raise CompileError("MID$ の第 1 引数は文字列です", node.pos)
            self._require_num(node.args[1], node.pos, "MID$ の開始位置")
            if n == 3:
                self._require_num(node.args[2], node.pos, "MID$ の長さ")
            return Type.STRING

        # --- 通常の固定シグネチャ ---
        for a, want in zip(node.args, sig.params):
            if want in (Type.INTEGER, Type.DOUBLE):
                self._require_num(a, node.pos, f"{node.name} の引数")
            elif a.ty != want:
                raise CompileError(
                    f"{node.name} の引数の型が違います "
                    f"({want} が必要、{a.ty} が渡されました)", node.pos)
        return sig.ret

    @staticmethod
    def _require_num(e: A.Expr, pos: SourcePos, what: str) -> None:
        if not _is_num(e.ty):
            raise CompileError(f"{what} は数値でなければなりません", pos)

    # ---- 二項演算の型規則 (仕様書 §5.2) -----------------------------------

    def _binop_type(self, e: A.BinOp) -> Type:
        lt, rt = e.left.ty, e.right.ty
        op = e.op

        # 文字列連結: + は両辺文字列のとき、& は数値も文字列化して連結
        if op == "+" and lt == Type.STRING and rt == Type.STRING:
            return Type.STRING
        if op == "&":
            for t in (lt, rt):
                if t == Type.STRING or _is_num(t):
                    continue
                raise CompileError("'&' の被演算子が不正です", e.pos)
            return Type.STRING

        # 比較: 数値どうし、または文字列どうし。結果は真理値 (INTEGER)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            if lt == Type.STRING and rt == Type.STRING:
                return Type.INTEGER
            if _is_num(lt) and _is_num(rt):
                return Type.INTEGER
            raise CompileError(
                f"'{op}' は数値どうしか文字列どうしを比較します "
                f"({lt} と {rt})", e.pos)

        # 論理/ビット演算: 整数へ丸めて 64bit ビット演算 (仕様書 §5.3)
        if op in ("AND", "OR", "XOR"):
            if _is_num(lt) and _is_num(rt):
                return Type.INTEGER
            raise CompileError(f"'{op}' は数値にのみ使えます", e.pos)

        # 算術
        if not (_is_num(lt) and _is_num(rt)):
            raise CompileError(
                f"'{op}' は数値にのみ使えます ({lt} と {rt})", e.pos)
        if op == "/":
            return Type.DOUBLE           # / は常に実数除算
        if op == "^":
            return Type.DOUBLE           # べき乗は常に DOUBLE
        if op in ("\\", "MOD"):
            return Type.INTEGER          # 被演算子は整数へ丸められる
        if op in ("+", "-", "*"):
            # 両方 INTEGER なら INTEGER、どちらかが DOUBLE なら DOUBLE
            if lt == Type.INTEGER and rt == Type.INTEGER:
                return Type.INTEGER
            return Type.DOUBLE
        raise AssertionError(f"unknown binop {op}")

    # ---- 代入可能性 --------------------------------------------------------

    def _check_assignable(self, target_ty: Type, value: A.Expr,
                          pos: SourcePos, what: str = "代入") -> None:
        """value を target_ty の場所に入れてよいか。
        数値→数値は暗黙変換 (IR 生成器が itof/ftoi を挿入)。"""
        if target_ty == value.ty:
            return
        if _is_num(target_ty) and _is_num(value.ty):
            return
        raise CompileError(
            f"{what}: {value.ty} を {target_ty} に変換できません", pos)

    # ==================================================================
    # 文の解析
    # ==================================================================

    def _stmt_list(self, body: list[A.Stmt]) -> None:
        for st in body:
            self._stmt(st)

    def _stmt(self, st: A.Stmt) -> None:
        """文 1 個をディスパッチ。クラス名からメソッド名を引く。"""
        name = "_s_" + type(st).__name__
        method = getattr(self, name, None)
        if method is None:
            raise AssertionError(f"no analyzer for {type(st).__name__}")
        method(st)

    # ---- 単純な文 ----------------------------------------------------------

    def _s_LabelStmt(self, st: A.LabelStmt) -> None:
        pass  # ラベルはパス 2 で収集済み

    def _s_EndStmt(self, st: A.EndStmt) -> None:
        pass

    def _s_PrintStmt(self, st: A.PrintStmt) -> None:
        for item in st.items:
            item.expr = self._expr(item.expr)   # 任意の型を出力できる

    def _s_InputStmt(self, st: A.InputStmt) -> None:
        st.targets = [self._lvalue(t) for t in st.targets]

    def _s_ReadStmt(self, st: A.ReadStmt) -> None:
        st.targets = [self._lvalue(t) for t in st.targets]

    def _lvalue(self, e: A.Expr) -> A.Expr:
        """代入先として解決する。スカラー変数か配列要素のみ。"""
        if isinstance(e, A.VarRef):
            node = self._resolve_varref(e, create=True)
            if isinstance(node, A.FuncCall):
                raise CompileError(f"'{e.name}' には代入できません", e.pos)
            if getattr(node, "resolved", None) == "const":
                raise CompileError(f"定数 '{e.name}' には代入できません", e.pos)
            return node
        if isinstance(e, A.IndexOrCall):
            node = self._resolve_index_or_call(e)
            if not isinstance(node, A.ArrayRef):
                raise CompileError("関数呼び出しには代入できません", e.pos)
            return node
        raise CompileError("代入先が不正です", e.pos)

    def _s_AssignStmt(self, st: A.AssignStmt) -> None:
        st.value = self._expr(st.value)
        st.target = self._lvalue(st.target)
        st.is_ret_assign = (isinstance(st.target, A.VarRef)
                            and getattr(st.target, "resolved", "") == "ret")
        self._check_assignable(st.target.ty, st.value, st.pos)

    def _s_SwapStmt(self, st: A.SwapStmt) -> None:
        st.a = self._lvalue(st.a)
        st.b = self._lvalue(st.b)
        if st.a.ty != st.b.ty:
            raise CompileError(
                f"SWAP は同じ型どうしのみです ({st.a.ty} と {st.b.ty})", st.pos)

    # ---- 宣言 --------------------------------------------------------------

    def _s_DimStmt(self, st: A.DimStmt) -> None:
        name = st.name
        # 型の決定: AS 句 > サフィックス > 既定 (DOUBLE)
        if st.elem_type is not None:
            sfx = A.type_from_name(name)
            if sfx is not None and sfx != st.elem_type:
                raise CompileError(
                    f"'{name}' のサフィックスと AS 句が矛盾しています", st.pos)
            ty = st.elem_type
        else:
            ty = self._default_type(name)

        at_top = self.cur_proc is None

        if st.dims:
            # ---- 配列宣言 ----
            new_dims: list[A.Expr] = []
            for d in st.dims:
                d2 = self._expr(d)
                self._require_num(d2, st.pos, "配列の上限")
                new_dims.append(d2)
            st.dims = new_dims
            if self._lookup_array(name) is not None:
                raise CompileError(f"配列 '{name}' は宣言済みです", st.pos)
            info = ArrayInfo(name=name, elem_ty=ty, ndims=len(st.dims),
                             is_global=at_top, pos=st.pos)
            if at_top:
                self.info.global_arrays[name] = info
            else:
                self.scope.arrays[name] = info
            st.array_info = info
        else:
            # ---- スカラー宣言 ----
            if name in self.scope.vars or name in self.info.global_vars \
               or name in self.info.consts:
                raise CompileError(f"変数 '{name}' は宣言済みです", st.pos)
            if at_top:
                # 先頭レベルの明示 DIM は大域変数 (手続きから見える)
                self.info.global_vars[name] = ty
            else:
                self.scope.vars[name] = ty
            st.array_info = None
        st.var_type = ty

    def _s_ConstStmt(self, st: A.ConstStmt) -> None:
        if self.cur_proc is not None:
            raise CompileError("CONST はメインプログラムにのみ書けます", st.pos)
        if (st.name in self.info.consts or st.name in self.info.global_vars
                or st.name in self.info.main_scope.vars):
            raise CompileError(f"'{st.name}' は既に定義されています", st.pos)
        value = self._const_eval(st.value)
        # 宣言型: サフィックス優先、無ければ値の自然な型
        sfx = A.type_from_name(st.name)
        if sfx is None:
            ty = (Type.STRING if isinstance(value, str)
                  else Type.INTEGER if isinstance(value, int) else Type.DOUBLE)
        else:
            ty = sfx
            if ty == Type.STRING and not isinstance(value, str):
                raise CompileError("文字列定数に数値は入れられません", st.pos)
            if ty != Type.STRING and isinstance(value, str):
                raise CompileError("数値定数に文字列は入れられません", st.pos)
            if ty == Type.INTEGER:
                value = int(round(value))
            elif ty == Type.DOUBLE:
                value = float(value)
        self.info.consts[st.name] = (ty, value)

    def _const_eval(self, e: A.Expr) -> object:
        """CONST 右辺のコンパイル時評価 (仕様書 §3.5)。
        リテラル・既出の定数・算術演算・単項マイナスのみ許す。"""
        if isinstance(e, A.NumLit):
            return e.value
        if isinstance(e, A.StrLit):
            return e.value
        if isinstance(e, A.VarRef) and e.name in self.info.consts:
            return self.info.consts[e.name][1]
        if isinstance(e, A.UnOp) and e.op == "-":
            v = self._const_eval(e.operand)
            if isinstance(v, str):
                raise CompileError("文字列に単項 '-' は使えません", e.pos)
            return -v
        if isinstance(e, A.BinOp):
            a = self._const_eval(e.left)
            b = self._const_eval(e.right)
            op = e.op
            try:
                if op == "+":
                    if isinstance(a, str) != isinstance(b, str):
                        raise CompileError("型が混在しています", e.pos)
                    return a + b
                if isinstance(a, str) or isinstance(b, str):
                    raise CompileError("文字列にこの演算子は使えません", e.pos)
                if op == "-":
                    return a - b
                if op == "*":
                    return a * b
                if op == "/":
                    return a / b
                if op in ("\\", "MOD"):
                    # 実行時と同じ規則 (仕様書 §5.2): 被演算子を最近接丸めで
                    # 整数化し、商はゼロ方向切り捨て、剰余の符号は被除数に従う。
                    qa, qb = int(round(a)), int(round(b))
                    if qb == 0:
                        raise ZeroDivisionError
                    quot = abs(qa) // abs(qb)
                    if (qa < 0) != (qb < 0):
                        quot = -quot
                    return quot if op == "\\" else qa - quot * qb
                if op == "^":
                    return float(a) ** float(b)
            except ZeroDivisionError:
                raise CompileError("定数式でゼロ除算です", e.pos)
        raise CompileError("CONST の右辺は定数式でなければなりません", e.pos)

    # ---- 制御構造 -----------------------------------------------------------

    def _cond(self, e: A.Expr, pos: SourcePos) -> A.Expr:
        e = self._expr(e)
        if not _is_num(e.ty):
            raise CompileError("条件式は数値でなければなりません "
                               "(0 以外が真)", pos)
        return e

    def _s_IfStmt(self, st: A.IfStmt) -> None:
        st.branches = [(self._cond(c, st.pos), b) for c, b in st.branches]
        for _, b in st.branches:
            self._stmt_list(b)
        if st.else_body is not None:
            self._stmt_list(st.else_body)

    def _s_WhileStmt(self, st: A.WhileStmt) -> None:
        st.cond = self._cond(st.cond, st.pos)
        self.loop_stack.append("WHILE")
        self._stmt_list(st.body)
        self.loop_stack.pop()

    def _s_DoLoopStmt(self, st: A.DoLoopStmt) -> None:
        if st.pre_cond is not None:
            st.pre_cond = self._cond(st.pre_cond, st.pos)
        self.loop_stack.append("DO")
        self._stmt_list(st.body)
        self.loop_stack.pop()
        if st.post_cond is not None:
            st.post_cond = self._cond(st.post_cond, st.pos)

    def _s_ForStmt(self, st: A.ForStmt) -> None:
        var = self._resolve_varref(st.var, create=True)
        if not isinstance(var, A.VarRef) or not _is_num(var.ty):
            raise CompileError("FOR のループ変数は数値変数です", st.pos)
        if getattr(var, "resolved", "") == "const":
            raise CompileError("定数はループ変数にできません", st.pos)
        st.var = var
        st.start = self._expr(st.start)
        st.end = self._expr(st.end)
        if st.step is not None:
            st.step = self._expr(st.step)
        for e, what in ((st.start, "開始値"), (st.end, "終了値"),
                        (st.step, "STEP")):
            if e is not None and not _is_num(e.ty):
                raise CompileError(f"FOR の{what}は数値です", st.pos)
        self.loop_stack.append("FOR")
        self._stmt_list(st.body)
        self.loop_stack.pop()

    def _s_ExitStmt(self, st: A.ExitStmt) -> None:
        if st.kind in ("FOR", "WHILE", "DO"):
            if st.kind not in self.loop_stack:
                raise CompileError(
                    f"EXIT {st.kind} が対応するループの外にあります", st.pos)
        elif st.kind == "SUB":
            if self.cur_proc is None or self.cur_proc.is_function:
                raise CompileError("EXIT SUB は SUB の中でのみ使えます", st.pos)
        elif st.kind == "FUNCTION":
            if self.cur_proc is None or not self.cur_proc.is_function:
                raise CompileError(
                    "EXIT FUNCTION は FUNCTION の中でのみ使えます", st.pos)

    def _s_SelectStmt(self, st: A.SelectStmt) -> None:
        st.subject = self._expr(st.subject)
        subj_ty = st.subject.ty
        for cl in st.clauses:
            new_tests: list[tuple] = []
            for test in cl.tests:
                kind = test[0]
                if kind == "EQ":
                    e = self._expr(test[1])
                    self._check_case_comparable(subj_ty, e, cl.pos)
                    new_tests.append(("EQ", e))
                elif kind == "RANGE":
                    lo = self._expr(test[1])
                    hi = self._expr(test[2])
                    self._check_case_comparable(subj_ty, lo, cl.pos)
                    self._check_case_comparable(subj_ty, hi, cl.pos)
                    new_tests.append(("RANGE", lo, hi))
                else:  # ("REL", op, expr)
                    e = self._expr(test[2])
                    self._check_case_comparable(subj_ty, e, cl.pos)
                    new_tests.append(("REL", test[1], e))
            cl.tests = new_tests
            self._stmt_list(cl.body)

    @staticmethod
    def _check_case_comparable(subj_ty: Type, e: A.Expr,
                               pos: SourcePos) -> None:
        if subj_ty == Type.STRING or e.ty == Type.STRING:
            if subj_ty != Type.STRING or e.ty != Type.STRING:
                raise CompileError(
                    "CASE の値の型が SELECT の式と合いません", pos)
        # 数値どうしは暗黙変換で比較できる

    # ---- ジャンプ -------------------------------------------------------------

    def _check_label(self, target: str, pos: SourcePos) -> None:
        if target not in self.scope.labels:
            where = ("この手続きの中" if self.cur_proc else "メインプログラム")
            raise CompileError(
                f"ラベル '{target}' が{where}にありません "
                "(GOTO/GOSUB はスコープを越えられません、仕様書 §4.3)", pos)

    def _s_GotoStmt(self, st: A.GotoStmt) -> None:
        self._check_label(st.target, st.pos)

    def _s_GosubStmt(self, st: A.GosubStmt) -> None:
        self._check_label(st.target, st.pos)

    def _s_ReturnStmt(self, st: A.ReturnStmt) -> None:
        if st.value is not None:
            if self.cur_proc is None or not self.cur_proc.is_function:
                raise CompileError(
                    "値付き RETURN は FUNCTION の中でのみ使えます", st.pos)
            st.value = self._expr(st.value)
            self._check_assignable(self.cur_proc.ret_ty, st.value, st.pos,
                                   what="RETURN")
        # 値なし RETURN は GOSUB からの復帰 (実行時に GOSUB スタックが
        # 空なら実行時エラー)

    def _s_RestoreStmt(self, st: A.RestoreStmt) -> None:
        if st.target is None:
            st.data_index = 0
            return
        if st.target not in self.info.data_label_index:
            raise CompileError(
                f"RESTORE のターゲット '{st.target}' がメインプログラムの"
                "ラベルにありません", st.pos)
        st.data_index = self.info.data_label_index[st.target]

    def _s_DataStmt(self, st: A.DataStmt) -> None:
        pass  # パス 2 で収集済み。実行時には何もしない文。

    # ---- 呼び出し・その他 -------------------------------------------------------

    def _s_CallStmt(self, st: A.CallStmt) -> None:
        proc = self.info.procs.get(st.name)
        if proc is None:
            raise CompileError(f"SUB '{st.name}' は定義されていません", st.pos)
        st.args = [self._expr(a) for a in st.args]
        self._check_user_call_args(proc, st)
        st.proc = proc   # FUNCTION を文として呼ぶことも許す (戻り値は捨てる)

    def _s_RandomizeStmt(self, st: A.RandomizeStmt) -> None:
        if st.seed is not None:
            st.seed = self._expr(st.seed)
            self._require_num(st.seed, st.pos, "RANDOMIZE の種")

    def _s_ProcDef(self, st: A.ProcDef) -> None:
        # parser が先頭レベルで procs に分離するのでここには来ないはず
        raise CompileError("SUB/FUNCTION はブロックの中に書けません", st.pos)


def analyze(program: A.Program) -> ProgramInfo:
    """モジュールの公開エントリポイント。"""
    return Analyzer(program).analyze()
