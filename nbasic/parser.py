"""
parser.py — 構文解析器 (トークン列 → AST)
=========================================

手書きの再帰下降パーサ。BASIC の文法は文の先頭キーワードでほぼ
一意に分岐できるため、先読み 1〜2 トークンの LL 解析で足りる。

行構造の扱い
------------
BASIC は行指向言語なので、構文解析器は NEWLINE/COLON を文の区切りとして
明示的に消費する。ブロック構文 (IF/FOR/WHILE/DO/SELECT/SUB/FUNCTION) は
複数行にまたがるため、「ブロック終端語 (END IF, WEND, NEXT, ...) が現れる
まで文を読み続ける」という形で実装する (parse_statements の stop 述語)。

ラベルの規則 (仕様書 §4.2)
--------------------------
- 物理行の先頭にある整数リテラルは「行番号ラベル」。
- 物理行の先頭にある `識別子 :` は「名前ラベル」。
  (行の先頭以外では `識別子 :` は SUB 呼び出し + 文区切りと解釈される)

代入と呼び出しの曖昧性
----------------------
`A(1) = 2` は配列代入、`F(1)` 単独は SUB 呼び出し、`F 1, 2` は引数付き
SUB 呼び出し。識別子で始まる文はこの 3 通り + 単純代入がありうるので、
`=` の有無で分岐する (_parse_ident_statement 参照)。
"""

from __future__ import annotations

from .errors import CompileError, SourcePos
from .lexer import Token, tokenize
from . import ast_nodes as A
from .ast_nodes import Type

# AS 句で書ける型名 → Type の対応
TYPE_KEYWORDS = {
    "INTEGER": Type.INTEGER,
    "DOUBLE": Type.DOUBLE,
    "STRING": Type.STRING,
}

# 文の終わりとみなすトークン (次の文へ進んでよい位置)
_STMT_END_KINDS = frozenset(["COLON", "NEWLINE", "EOF"])


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.k = 0  # 次に読むトークンのインデックス

    # ======================================================================
    # 低レベルヘルパ
    # ======================================================================

    def _cur(self) -> Token:
        return self.toks[self.k]

    def _peek(self, ahead: int = 1) -> Token:
        j = min(self.k + ahead, len(self.toks) - 1)
        return self.toks[j]

    def _advance(self) -> Token:
        tok = self.toks[self.k]
        if tok.kind != "EOF":
            self.k += 1
        return tok

    def _at(self, kind: str, value: object = None) -> bool:
        """現在のトークンが指定の種類 (と値) かどうか。"""
        tok = self._cur()
        if tok.kind != kind:
            return False
        return value is None or tok.value == value

    def _at_kw(self, *words: str) -> bool:
        """現在位置からキーワード列 words が並んでいるか。
        例: _at_kw("END", "IF") は `END IF` の先頭にいるとき True。
        """
        for i, w in enumerate(words):
            tok = self._peek(i) if i else self._cur()
            if tok.kind != "KEYWORD" or tok.value != w:
                return False
        return True

    def _accept_kw(self, word: str) -> bool:
        """キーワード word なら消費して True。"""
        if self._at_kw(word):
            self._advance()
            return True
        return False

    def _expect_kw(self, word: str) -> Token:
        if not self._at_kw(word):
            raise CompileError(f"'{word}' が必要です", self._cur().pos)
        return self._advance()

    def _accept_op(self, op: str) -> bool:
        if self._at("OP", op):
            self._advance()
            return True
        return False

    def _expect_op(self, op: str) -> Token:
        if not self._at("OP", op):
            raise CompileError(f"'{op}' が必要です", self._cur().pos)
        return self._advance()

    def _expect_ident(self) -> Token:
        if not self._at("IDENT"):
            raise CompileError("識別子が必要です", self._cur().pos)
        return self._advance()

    def _at_stmt_end(self) -> bool:
        """文の終わり (COLON / NEWLINE / EOF) にいるか。"""
        return self._cur().kind in _STMT_END_KINDS

    def _expect_stmt_end(self) -> None:
        """文の直後は必ず区切りでなければならない。区切り自体は消費しない
        (parse_statements のループ先頭でまとめて読み飛ばすため)。"""
        if not self._at_stmt_end():
            raise CompileError(
                f"文の終わりが必要ですが {self._describe(self._cur())} があります",
                self._cur().pos)

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.kind == "EOF":
            return "ファイル末尾"
        if tok.kind == "NEWLINE":
            return "行末"
        return f"'{tok.value}'"

    # ======================================================================
    # プログラム全体
    # ======================================================================

    def parse_program(self) -> A.Program:
        """プログラム = { SUB/FUNCTION 定義 | メインの文 } の並び。

        先頭レベルの文はソース出現順にメインプログラムとなり、
        SUB/FUNCTION 定義は procs へ分離される (どこに書いても同じ)。
        """
        main: list[A.Stmt] = []
        procs: list[A.ProcDef] = []
        while not self._at("EOF"):
            # 空行・余分なコロンを読み飛ばす
            if self._cur().kind in ("NEWLINE", "COLON"):
                self._advance()
                continue
            if self._at_kw("SUB") or self._at_kw("FUNCTION"):
                procs.append(self._parse_proc())
            elif self._at_kw("DECLARE"):
                # DECLARE SUB/FUNCTION ... は QBasic 互換の前方宣言。
                # NBASIC-21 では全手続きが自動的に前方参照可能なので、
                # 互換性のため行ごと読み飛ばす。
                while not self._at("NEWLINE") and not self._at("EOF"):
                    self._advance()
            else:
                main.extend(self._parse_line_into(main))
        return A.Program(main, procs)

    def _parse_line_into(self, _sink) -> list[A.Stmt]:
        """メインプログラムの 1 論理単位 (ラベル or 文) を読む。

        parse_statements と同じ規則を使うが、先頭レベルでは
        ブロック終端語が現れたらエラーにしたいので stop 述語は常に False。
        """
        return self._parse_statements(stop=lambda: False, toplevel_once=True)

    # ======================================================================
    # 文の並び
    # ======================================================================

    def _parse_statements(self, stop, toplevel_once: bool = False) -> list[A.Stmt]:
        """文の並びを読む。

        stop() が True を返す位置 (ブロック終端語の直前) で停止する。
        終端語そのものは消費しない — 消費は呼び出し側 (各ブロック構文の
        パーサ) の責任。ラベルは物理行の先頭でのみ認識する。

        toplevel_once=True のときは 1 行分だけ読んで戻る
        (parse_program が SUB 定義の検出のため行単位で制御したいので)。
        """
        out: list[A.Stmt] = []
        while True:
            # ---- 区切り (改行・コロン) を読み飛ばす ----
            while self._cur().kind in ("NEWLINE", "COLON"):
                self._advance()
                if toplevel_once and out:
                    return out  # 1 行読み終えた
            if self._at("EOF") or stop():
                return out

            # 「行頭にいる」= 直前のトークンが改行 (または入力の先頭)。
            # この判定は parse_program からの呼び出し単位をまたいでも
            # 正しく働く (トークン列自体を見ているので状態を持たない)。
            at_line_start = (self.k == 0
                             or self.toks[self.k - 1].kind == "NEWLINE")

            # ---- ラベル (行頭のみ) ----
            if at_line_start:
                if self._at("NUMBER") and isinstance(self._cur().value, int):
                    tok = self._advance()
                    out.append(A.LabelStmt(tok.pos, name=str(tok.value),
                                           is_line_number=True))
                    # 行番号の後には同じ行に文が続く (無くてもよい)
                    continue
                if self._at("IDENT") and self._peek().kind == "COLON":
                    tok = self._advance()   # 識別子
                    self._advance()         # コロン
                    out.append(A.LabelStmt(tok.pos, name=tok.value,
                                           is_line_number=False))
                    continue

            # ---- 通常の文 ----
            out.extend(self._parse_statement())
            # 文の後は区切り・EOF・ブロック終端のどれかでなければならない
            if not (self._at_stmt_end() or stop()):
                raise CompileError(
                    f"文の終わりが必要ですが {self._describe(self._cur())} があります",
                    self._cur().pos)

    # ======================================================================
    # 個々の文
    # ======================================================================

    def _parse_statement(self) -> list[A.Stmt]:
        """1 個の文を読む。DIM/CONST のような複数宣言は複数ノードに
        展開されるため、戻り値はリスト。"""
        tok = self._cur()

        if tok.kind == "KEYWORD":
            word = tok.value
            # 各キーワードに対応するメソッドへ分岐。
            method = getattr(self, f"_parse_{word.lower()}_stmt", None)
            if method is not None:
                return method()
            raise CompileError(f"ここでは '{word}' は使えません", tok.pos)

        if tok.kind == "IDENT":
            return self._parse_ident_statement()

        raise CompileError(
            f"文が必要ですが {self._describe(tok)} があります", tok.pos)

    # ---- PRINT -----------------------------------------------------------

    def _parse_print_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # PRINT
        items: list[A.PrintItem] = []
        trailing = False
        # 空の PRINT は空行の出力
        while not self._at_stmt_end() and not self._at_kw("ELSE"):
            expr = self._parse_expr()
            if self._at("OP", ";") or self._at("OP", ","):
                sep = self._advance().value
                items.append(A.PrintItem(expr, sep))
                # 区切りの直後で文が終わる → 改行抑制
                if self._at_stmt_end() or self._at_kw("ELSE"):
                    trailing = True
                    break
            else:
                items.append(A.PrintItem(expr, ""))
                break
        return [A.PrintStmt(pos, items=items, trailing_sep=trailing)]

    # ---- INPUT -----------------------------------------------------------

    def _parse_input_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # INPUT
        prompt: str | None = None
        # INPUT "プロンプト"; 変数   または   INPUT "プロンプト", 変数
        if self._at("STRING"):
            prompt = self._advance().value
            if not (self._accept_op(";") or self._accept_op(",")):
                raise CompileError("プロンプト文字列の後に ';' か ',' が必要です",
                                   self._cur().pos)
        targets = [self._parse_lvalue()]
        while self._accept_op(","):
            targets.append(self._parse_lvalue())
        return [A.InputStmt(pos, prompt=prompt, targets=targets)]

    def _parse_lvalue(self) -> A.Expr:
        """代入先 (変数または配列要素) を読む。"""
        tok = self._expect_ident()
        if self._at("OP", "("):
            args = self._parse_paren_args()
            node = A.IndexOrCall(tok.pos, name=tok.value, args=args)
            return node
        return A.VarRef(tok.pos, name=tok.value)

    # ---- LET / 代入 / SUB 呼び出し ----------------------------------------

    def _parse_let_stmt(self) -> list[A.Stmt]:
        self._advance()  # LET
        # LET の後は必ず代入
        target = self._parse_lvalue()
        eq = self._expect_op("=")
        value = self._parse_expr()
        return [A.AssignStmt(eq.pos, target=target, value=value)]

    def _parse_ident_statement(self) -> list[A.Stmt]:
        """識別子で始まる文: 代入 / 配列代入 / SUB 呼び出しを判別する。"""
        tok = self._advance()  # 識別子
        name = tok.value

        if self._at("OP", "("):
            # `名前(...)` — 続きが `=` なら配列要素への代入、
            # 文末なら括弧付き SUB 呼び出し。
            args = self._parse_paren_args()
            if self._at("OP", "="):
                eq = self._advance()
                value = self._parse_expr()
                target = A.IndexOrCall(tok.pos, name=name, args=args)
                return [A.AssignStmt(eq.pos, target=target, value=value)]
            self._expect_stmt_end_or_else()
            return [A.CallStmt(tok.pos, name=name, args=args)]

        if self._at("OP", "="):
            eq = self._advance()
            value = self._parse_expr()
            return [A.AssignStmt(eq.pos, target=A.VarRef(tok.pos, name=name),
                                 value=value)]

        if self._at_stmt_end() or self._at_kw("ELSE"):
            # 引数なし SUB 呼び出し (`Foo`)
            return [A.CallStmt(tok.pos, name=name, args=[])]

        # 括弧なし引数付き SUB 呼び出し (`Foo 1, 2`)
        args = [self._parse_expr()]
        while self._accept_op(","):
            args.append(self._parse_expr())
        return [A.CallStmt(tok.pos, name=name, args=args)]

    def _expect_stmt_end_or_else(self) -> None:
        if not (self._at_stmt_end() or self._at_kw("ELSE")):
            raise CompileError(
                f"文の終わりが必要ですが {self._describe(self._cur())} があります",
                self._cur().pos)

    def _parse_call_stmt(self) -> list[A.Stmt]:
        """CALL 名前 [(引数, ...)] — CALL キーワード形式の SUB 呼び出し。"""
        self._advance()  # CALL
        tok = self._expect_ident()
        args: list[A.Expr] = []
        if self._at("OP", "("):
            args = self._parse_paren_args()
        return [A.CallStmt(tok.pos, name=tok.value, args=args)]

    # ---- IF ---------------------------------------------------------------

    def _parse_if_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # IF
        cond = self._parse_expr()
        self._expect_kw("THEN")

        if self._at("NEWLINE"):
            return [self._parse_block_if(pos, cond)]
        return [self._parse_single_line_if(pos, cond)]

    def _parse_single_line_if(self, pos: SourcePos, cond: A.Expr) -> A.IfStmt:
        """単一行 IF:  IF c THEN 文 [: 文...] [ELSE 文 [: 文...]]
        古典互換で `IF c THEN 100` (行番号への GOTO 省略形) も許す。"""
        then_body = self._parse_inline_body()
        else_body: list[A.Stmt] | None = None
        if self._accept_kw("ELSE"):
            else_body = self._parse_inline_body()
        return A.IfStmt(pos, branches=[(cond, then_body)], else_body=else_body)

    def _parse_inline_body(self) -> list[A.Stmt]:
        """単一行 IF の THEN/ELSE 節: 行番号 GOTO 省略形、
        またはコロン区切りの文の並び (行末か ELSE まで)。"""
        if self._at("NUMBER") and isinstance(self._cur().value, int):
            tok = self._advance()
            return [A.GotoStmt(tok.pos, target=str(tok.value))]
        body: list[A.Stmt] = []
        while True:
            body.extend(self._parse_statement())
            if self._accept_op(",") :
                # 一部の古典方言はカンマ区切りも許すが NBASIC-21 では
                # 混乱を避けるためコロンのみとする (ここには来ない)。
                raise CompileError("文の区切りには ':' を使ってください",
                                   self._cur().pos)
            if self._at("COLON"):
                self._advance()
                if self._at("NEWLINE") or self._at("EOF") or self._at_kw("ELSE"):
                    break
                continue
            break
        return body

    def _parse_block_if(self, pos: SourcePos, cond: A.Expr) -> A.IfStmt:
        """ブロック IF:
            IF c1 THEN
              ...
            ELSEIF c2 THEN
              ...
            ELSE
              ...
            END IF
        """
        def stop():
            return (self._at_kw("ELSEIF") or self._at_kw("ELSE")
                    or self._at_kw("END", "IF"))

        branches: list[tuple[A.Expr, list[A.Stmt]]] = []
        branches.append((cond, self._parse_statements(stop)))

        while self._at_kw("ELSEIF"):
            self._advance()
            c = self._parse_expr()
            self._expect_kw("THEN")
            branches.append((c, self._parse_statements(stop)))

        else_body: list[A.Stmt] | None = None
        if self._accept_kw("ELSE"):
            else_body = self._parse_statements(
                lambda: self._at_kw("END", "IF"))

        if not self._at_kw("END", "IF"):
            raise CompileError("'END IF' が必要です", self._cur().pos)
        self._advance()  # END
        self._advance()  # IF
        return A.IfStmt(pos, branches=branches, else_body=else_body)

    # ---- ループ -----------------------------------------------------------

    def _parse_for_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # FOR
        var_tok = self._expect_ident()
        var = A.VarRef(var_tok.pos, name=var_tok.value)
        self._expect_op("=")
        start = self._parse_expr()
        self._expect_kw("TO")
        end = self._parse_expr()
        step: A.Expr | None = None
        if self._accept_kw("STEP"):
            step = self._parse_expr()
        body = self._parse_statements(lambda: self._at_kw("NEXT"))
        if not self._at_kw("NEXT"):
            raise CompileError("'NEXT' が必要です (FOR に対応)", self._cur().pos)
        self._advance()  # NEXT
        # NEXT に変数名が付いていたら FOR の変数と一致するか検査する
        if self._at("IDENT"):
            next_var = self._advance()
            if next_var.value != var.name:
                raise CompileError(
                    f"NEXT の変数 '{next_var.value}' が FOR の変数 "
                    f"'{var.name}' と一致しません", next_var.pos)
        return [A.ForStmt(pos, var=var, start=start, end=end, step=step,
                          body=body)]

    def _parse_while_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # WHILE
        cond = self._parse_expr()
        body = self._parse_statements(lambda: self._at_kw("WEND"))
        self._expect_kw("WEND")
        return [A.WhileStmt(pos, cond=cond, body=body)]

    def _parse_do_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # DO
        pre_cond: A.Expr | None = None
        pre_neg = False
        if self._accept_kw("WHILE"):
            pre_cond = self._parse_expr()
        elif self._accept_kw("UNTIL"):
            pre_cond = self._parse_expr()
            pre_neg = True
        body = self._parse_statements(lambda: self._at_kw("LOOP"))
        self._expect_kw("LOOP")
        post_cond: A.Expr | None = None
        post_neg = False
        if self._accept_kw("WHILE"):
            post_cond = self._parse_expr()
        elif self._accept_kw("UNTIL"):
            post_cond = self._parse_expr()
            post_neg = True
        if pre_cond is not None and post_cond is not None:
            raise CompileError("DO と LOOP の両方に条件は書けません", pos)
        return [A.DoLoopStmt(pos, pre_cond=pre_cond, pre_negate=pre_neg,
                             body=body, post_cond=post_cond,
                             post_negate=post_neg)]

    def _parse_exit_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # EXIT
        for kw in ("FOR", "WHILE", "DO", "SUB", "FUNCTION"):
            if self._accept_kw(kw):
                return [A.ExitStmt(pos, kind=kw)]
        raise CompileError(
            "EXIT の後には FOR / WHILE / DO / SUB / FUNCTION が必要です", pos)

    # ---- ジャンプ -----------------------------------------------------------

    def _parse_jump_target(self) -> str:
        """GOTO/GOSUB/RESTORE のターゲット (行番号または名前ラベル)。"""
        if self._at("NUMBER") and isinstance(self._cur().value, int):
            return str(self._advance().value)
        if self._at("IDENT"):
            return self._advance().value
        raise CompileError("行番号かラベル名が必要です", self._cur().pos)

    def _parse_goto_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos
        return [A.GotoStmt(pos, target=self._parse_jump_target())]

    def _parse_gosub_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos
        return [A.GosubStmt(pos, target=self._parse_jump_target())]

    def _parse_return_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos
        value: A.Expr | None = None
        if not self._at_stmt_end() and not self._at_kw("ELSE"):
            value = self._parse_expr()
        return [A.ReturnStmt(pos, value=value)]

    def _parse_end_stmt(self) -> list[A.Stmt]:
        # ここに来るのは単独の END のみ。END IF / END SUB / END FUNCTION /
        # END SELECT はそれぞれのブロックパーサが stop 述語で検出して
        # 消費するので、ここに現れたら対応するブロックが無いということ。
        pos = self._cur().pos
        nxt = self._peek()
        if nxt.kind == "KEYWORD" and nxt.value in ("IF", "SUB", "FUNCTION", "SELECT"):
            raise CompileError(
                f"対応するブロックのない 'END {nxt.value}' です", pos)
        self._advance()
        return [A.EndStmt(pos)]

    def _parse_stop_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos
        return [A.EndStmt(pos)]

    # ---- 宣言 --------------------------------------------------------------

    def _parse_as_type(self) -> Type | None:
        """省略可能な `AS 型名` を読む。"""
        if not self._accept_kw("AS"):
            return None
        tok = self._cur()
        if tok.kind == "KEYWORD" and tok.value in TYPE_KEYWORDS:
            self._advance()
            return TYPE_KEYWORDS[tok.value]
        raise CompileError("AS の後には INTEGER / DOUBLE / STRING が必要です",
                           tok.pos)

    def _parse_dim_stmt(self) -> list[A.Stmt]:
        """DIM 宣言 [, 宣言 ...]
        宣言 = 名前 [ "(" 上限式 [, 上限式] ")" ] [ AS 型 ]"""
        self._advance()  # DIM
        out: list[A.Stmt] = []
        while True:
            tok = self._expect_ident()
            dims: list[A.Expr] = []
            if self._at("OP", "("):
                dims = self._parse_paren_args()
                if not 1 <= len(dims) <= 2:
                    raise CompileError("配列は 1 次元または 2 次元です", tok.pos)
            elem = self._parse_as_type()
            out.append(A.DimStmt(tok.pos, name=tok.value, dims=dims,
                                 elem_type=elem))
            if not self._accept_op(","):
                break
        return out

    def _parse_const_stmt(self) -> list[A.Stmt]:
        """CONST 名前 = 定数式 [, 名前 = 定数式 ...]"""
        self._advance()  # CONST
        out: list[A.Stmt] = []
        while True:
            tok = self._expect_ident()
            self._expect_op("=")
            value = self._parse_expr()
            out.append(A.ConstStmt(tok.pos, name=tok.value, value=value))
            if not self._accept_op(","):
                break
        return out

    def _parse_redim_stmt(self) -> list[A.Stmt]:
        raise CompileError("REDIM は NBASIC-21 では未対応です (仕様書 §12)",
                           self._cur().pos)

    # ---- SELECT CASE -------------------------------------------------------

    def _parse_select_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # SELECT
        self._expect_kw("CASE")
        subject = self._parse_expr()

        def stop():
            return self._at_kw("CASE") or self._at_kw("END", "SELECT")

        # SELECT CASE の直後、最初の CASE までは空行のみ許される
        lead = self._parse_statements(stop)
        if lead:
            raise CompileError("SELECT CASE と最初の CASE の間に文は書けません",
                               lead[0].pos)

        clauses: list[A.CaseClause] = []
        seen_else = False
        while self._at_kw("CASE"):
            cpos = self._advance().pos  # CASE
            tests: list[tuple] = []
            if self._accept_kw("ELSE"):
                if seen_else:
                    raise CompileError("CASE ELSE は 1 つだけです", cpos)
                seen_else = True
            else:
                # 照合条件のカンマ区切りリスト
                while True:
                    tests.append(self._parse_case_test())
                    if not self._accept_op(","):
                        break
            body = self._parse_statements(stop)
            clauses.append(A.CaseClause(tests=tests, body=body, pos=cpos))

        if not self._at_kw("END", "SELECT"):
            raise CompileError("'END SELECT' が必要です", self._cur().pos)
        self._advance()  # END
        self._advance()  # SELECT
        return [A.SelectStmt(pos, subject=subject, clauses=clauses)]

    def _parse_case_test(self) -> tuple:
        """CASE の照合条件 1 個 (仕様書 §6.4):
             IS 比較演算子 式   → ("REL", op, 式)
             式 TO 式          → ("RANGE", 下限, 上限)
             式                → ("EQ", 式)
        """
        if self._accept_kw("IS"):
            tok = self._cur()
            if tok.kind == "OP" and tok.value in ("=", "<>", "<", "<=", ">", ">="):
                op = self._advance().value
                return ("REL", op, self._parse_expr())
            raise CompileError("IS の後には比較演算子が必要です", tok.pos)
        first = self._parse_expr()
        if self._accept_kw("TO"):
            return ("RANGE", first, self._parse_expr())
        return ("EQ", first)

    # ---- SUB / FUNCTION ------------------------------------------------------

    def _parse_proc(self) -> A.ProcDef:
        """SUB 名前 [(仮引数, ...)] ... END SUB
        FUNCTION 名前 [(仮引数, ...)] [AS 型] ... END FUNCTION"""
        is_function = self._at_kw("FUNCTION")
        kw = "FUNCTION" if is_function else "SUB"
        pos = self._advance().pos
        name_tok = self._expect_ident()
        name = name_tok.value

        params: list[A.Param] = []
        if self._accept_op("("):
            if not self._at("OP", ")"):
                while True:
                    ptok = self._expect_ident()
                    pty = self._parse_as_type()
                    if pty is None:
                        # AS 句が無ければサフィックス、それも無ければ既定の DOUBLE
                        pty = A.type_from_name(ptok.value) or Type.DOUBLE
                    else:
                        self._check_suffix_conflict(ptok.value, pty, ptok.pos)
                    params.append(A.Param(ptok.value, pty, ptok.pos))
                    if not self._accept_op(","):
                        break
            self._expect_op(")")

        ret_type: Type | None = None
        if is_function:
            ret_type = self._parse_as_type()
            if ret_type is None:
                ret_type = A.type_from_name(name) or Type.DOUBLE
            else:
                self._check_suffix_conflict(name, ret_type, name_tok.pos)

        def stop():
            return self._at_kw("END", kw)

        body = self._parse_statements(stop)
        if not self._at_kw("END", kw):
            raise CompileError(f"'END {kw}' が必要です", self._cur().pos)
        self._advance()  # END
        self._advance()  # SUB / FUNCTION
        return A.ProcDef(pos, name=name, params=params,
                         is_function=is_function, ret_type=ret_type, body=body)

    @staticmethod
    def _check_suffix_conflict(name: str, ty: Type, pos: SourcePos) -> None:
        """`X% AS STRING` のようなサフィックスと AS 句の矛盾を検出する。"""
        sfx = A.type_from_name(name)
        if sfx is not None and sfx != ty:
            raise CompileError(
                f"'{name}' の型サフィックスと AS 句の型 {ty} が矛盾しています",
                pos)

    # ---- DATA / READ / RESTORE ----------------------------------------------

    def _parse_data_stmt(self) -> list[A.Stmt]:
        """DATA 項目 [, 項目 ...]。項目は字句解析器が STRING トークンに
        まとめてある (lexer.py の _lex_data_items 参照)。"""
        pos = self._advance().pos  # DATA
        items: list[str] = []
        if self._at("STRING"):
            items.append(self._advance().value)
            while self._accept_op(","):
                if not self._at("STRING"):
                    raise CompileError("DATA の項目が必要です", self._cur().pos)
                items.append(self._advance().value)
        return [A.DataStmt(pos, items=items)]

    def _parse_read_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # READ
        targets = [self._parse_lvalue()]
        while self._accept_op(","):
            targets.append(self._parse_lvalue())
        return [A.ReadStmt(pos, targets=targets)]

    def _parse_restore_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # RESTORE
        target: str | None = None
        if not self._at_stmt_end():
            target = self._parse_jump_target()
        return [A.RestoreStmt(pos, target=target)]

    # ---- その他 ----------------------------------------------------------------

    def _parse_randomize_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # RANDOMIZE
        seed: A.Expr | None = None
        if not self._at_stmt_end():
            seed = self._parse_expr()
        return [A.RandomizeStmt(pos, seed=seed)]

    def _parse_swap_stmt(self) -> list[A.Stmt]:
        pos = self._advance().pos  # SWAP
        a = self._parse_lvalue()
        self._expect_op(",")
        b = self._parse_lvalue()
        return [A.SwapStmt(pos, a=a, b=b)]

    # ======================================================================
    # 式 (演算子優先順位法)
    # ======================================================================
    #
    # 優先順位 (低 → 高、仕様書 §5.4):
    #   XOR < OR < AND < NOT < 比較 < & < + - < MOD < \ < * / < 単項- < ^
    #
    # 各レベルを 1 メソッドにする素直な再帰下降。二項演算子はすべて左結合。
    # NOT と単項 - は前置演算子で、自分と同レベル以上を再帰する。

    def _parse_expr(self) -> A.Expr:
        return self._parse_xor()

    def _binop_level(self, sub, kinds: tuple[tuple[str, str], ...]) -> A.Expr:
        """左結合の二項演算レベルを 1 段解析する共通ヘルパ。

        kinds は (トークン種類, 値) の組の列。例えば加減算レベルなら
        (("OP","+"), ("OP","-"))。マッチする限り左結合で畳み込む。
        """
        left = sub()
        while True:
            tok = self._cur()
            matched = None
            for kind, value in kinds:
                if tok.kind == kind and tok.value == value:
                    matched = value
                    break
            if matched is None:
                return left
            self._advance()
            right = sub()
            node = A.BinOp(tok.pos, op=matched, left=left, right=right)
            left = node

    def _parse_xor(self) -> A.Expr:
        return self._binop_level(self._parse_or, (("KEYWORD", "XOR"),))

    def _parse_or(self) -> A.Expr:
        return self._binop_level(self._parse_and, (("KEYWORD", "OR"),))

    def _parse_and(self) -> A.Expr:
        return self._binop_level(self._parse_not, (("KEYWORD", "AND"),))

    def _parse_not(self) -> A.Expr:
        if self._at_kw("NOT"):
            pos = self._advance().pos
            operand = self._parse_not()  # NOT NOT X も許す
            return A.UnOp(pos, op="NOT", operand=operand)
        return self._parse_relational()

    def _parse_relational(self) -> A.Expr:
        return self._binop_level(
            self._parse_concat,
            (("OP", "="), ("OP", "<>"), ("OP", "<"),
             ("OP", "<="), ("OP", ">"), ("OP", ">=")))

    def _parse_concat(self) -> A.Expr:
        return self._binop_level(self._parse_additive, (("OP", "&"),))

    def _parse_additive(self) -> A.Expr:
        return self._binop_level(self._parse_mod,
                                 (("OP", "+"), ("OP", "-")))

    def _parse_mod(self) -> A.Expr:
        return self._binop_level(self._parse_intdiv, (("KEYWORD", "MOD"),))

    def _parse_intdiv(self) -> A.Expr:
        return self._binop_level(self._parse_multiplicative, (("OP", "\\"),))

    def _parse_multiplicative(self) -> A.Expr:
        return self._binop_level(self._parse_unary,
                                 (("OP", "*"), ("OP", "/")))

    def _parse_unary(self) -> A.Expr:
        """単項マイナス。^ より弱い (-2^2 は -(2^2) = -4、仕様書 §5.4)。"""
        if self._at("OP", "-"):
            pos = self._advance().pos
            operand = self._parse_unary()
            return A.UnOp(pos, op="-", operand=operand)
        if self._at("OP", "+"):     # 単項 + は何もしない
            self._advance()
            return self._parse_unary()
        return self._parse_power()

    def _parse_power(self) -> A.Expr:
        """べき乗 ^ (左結合: 2^3^2 = (2^3)^2 = 64)。
        右辺には単項マイナスを許す (2^-3 が書ける)。"""
        left = self._parse_primary()
        while self._at("OP", "^"):
            tok = self._advance()
            # 右辺の先頭の単項マイナスだけ特別扱いする
            if self._at("OP", "-"):
                npos = self._advance().pos
                right: A.Expr = A.UnOp(npos, op="-", operand=self._parse_primary())
            else:
                right = self._parse_primary()
            left = A.BinOp(tok.pos, op="^", left=left, right=right)
        return left

    def _parse_primary(self) -> A.Expr:
        tok = self._cur()
        if tok.kind == "NUMBER":
            self._advance()
            return A.NumLit(tok.pos, value=tok.value)
        if tok.kind == "STRING":
            self._advance()
            return A.StrLit(tok.pos, value=tok.value)
        if tok.kind == "IDENT":
            self._advance()
            if self._at("OP", "("):
                # 配列アクセスか関数呼び出しか、この段階では分からない
                args = self._parse_paren_args()
                return A.IndexOrCall(tok.pos, name=tok.value, args=args)
            return A.VarRef(tok.pos, name=tok.value)
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            inner = self._parse_expr()
            self._expect_op(")")
            return inner
        raise CompileError(
            f"式が必要ですが {self._describe(tok)} があります", tok.pos)

    def _parse_paren_args(self) -> list[A.Expr]:
        """`( 式, 式, ... )` を読む。空の `()` も許す。"""
        self._expect_op("(")
        args: list[A.Expr] = []
        if not self._at("OP", ")"):
            args.append(self._parse_expr())
            while self._accept_op(","):
                args.append(self._parse_expr())
        self._expect_op(")")
        return args


def parse(source: str) -> A.Program:
    """モジュールの公開エントリポイント: ソース文字列 → AST。"""
    return Parser(tokenize(source)).parse_program()
