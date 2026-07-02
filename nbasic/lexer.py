"""
lexer.py — 字句解析器 (ソース文字列 → トークン列)
=================================================

BASIC は「行指向」の言語なので、字句解析器は改行を捨てずに
NEWLINE トークンとして構文解析器へ渡す。また `:` は同一行内の
文および複数ラベルの区切りとして使われるため COLON トークンになる。

トークンの種類 (TokenKind):
    NUMBER   数値リテラル (整数または浮動小数点。value に Python の int/float)
    STRING   文字列リテラル (value に内容の str。囲みの " は除去済み)
    IDENT    識別子 (型サフィックス % # ! $ を含む。大文字に正規化済み)
    KEYWORD  予約語 (PRINT, IF, FOR, ...。大文字に正規化済み)
    OP       演算子・区切り記号 ( + - * / \\ ^ = <> < <= > >= ( ) , ; & )
    COLON    文区切りの `:`
    NEWLINE  物理行の終わり
    EOF      入力の終わり

BASIC の伝統に従い、キーワードと識別子は大文字小文字を区別しない。
字句解析の段階ですべて大文字に正規化することで、以降のステージは
大文字だけを考えればよくなる。

コメントは 2 種類:
    REM このように行末までコメント
    ' アポストロフィも行末までコメント
どちらも字句解析の段階で読み飛ばす (トークンを生成しない)。
"""

from __future__ import annotations
from dataclasses import dataclass
from .errors import CompileError, SourcePos

# --------------------------------------------------------------------------
# トークン定義
# --------------------------------------------------------------------------

# 予約語の一覧。ここに載っている綴りの識別子は IDENT ではなく KEYWORD になる。
# NOT/AND/OR/XOR/MOD は演算子だが、綴りが英単語なのでキーワードとして
# 字句解析し、構文解析器が演算子として扱う。
KEYWORDS = frozenset("""
    PRINT INPUT LET IF THEN ELSE ELSEIF END
    FOR TO STEP NEXT WHILE WEND DO LOOP UNTIL
    GOTO GOSUB RETURN
    DIM AS CONST REDIM
    SUB FUNCTION DECLARE CALL
    SELECT CASE IS
    DATA READ RESTORE
    REM STOP EXIT SWAP RANDOMIZE
    AND OR XOR NOT MOD
    INTEGER DOUBLE STRING
    OPEN CLOSE LINE
    CLS LOCATE COLOR SLEEP
""".split())
# 注: OPEN の OUTPUT / APPEND モード名は予約語ではなく、OPEN 文の
# 文脈でのみ識別子として照合する (変数名 OUTPUT を壊さないため)。

# 2 文字演算子。1 文字演算子より先に照合しなければならない
# (例: "<=" を "<" と "=" に分けてしまわないように)。
TWO_CHAR_OPS = ("<=", ">=", "<>")

# 1 文字演算子・区切り記号。
# \  : 整数除算   ^ : べき乗   & : 文字列連結   ; , : PRINT の区切り
# #  : ファイル番号の目印 (PRINT #1 など)。識別子・数値の直後の # は
#      型サフィックスとしてそちらの字句解析が先に消費するので衝突しない。
ONE_CHAR_OPS = "+-*/\\^=<>(),;&#"


@dataclass(frozen=True)
class Token:
    """1 個のトークン。kind で種類を、value で内容を表す。

    value の型は kind によって異なる:
        NUMBER  → int または float
        STRING  → str (囲みの " を除いた内容)
        IDENT   → str (大文字化済み。型サフィックス込み。例 "N%", "NAME$")
        KEYWORD → str (大文字化済み。例 "PRINT")
        OP      → str (例 "<=", "+")
        COLON/NEWLINE/EOF → None
    """
    kind: str
    value: object
    pos: SourcePos

    def __repr__(self) -> str:  # デバッグ表示用
        return f"Token({self.kind}, {self.value!r}, {self.pos})"


# --------------------------------------------------------------------------
# 字句解析器本体
# --------------------------------------------------------------------------

class Lexer:
    """ソース文字列を 1 パスで走査してトークン列を作る。

    実装は「現在位置 self.i を進めながら 1 文字ずつ判定する」古典的な
    手書きスキャナ。BASIC の字句規則は正規表現で足りるほど単純だが、
    エラー位置の追跡とコメント/改行の扱いを明示するため手書きにしている。
    """

    def __init__(self, source: str):
        self.src = source
        self.i = 0              # 次に読む文字のインデックス
        self.line = 1           # 現在の物理行 (1 始まり)
        self.col = 1            # 現在の桁 (1 始まり)
        self.tokens: list[Token] = []

    # ---- 低レベルヘルパ ---------------------------------------------------

    def _pos(self) -> SourcePos:
        return SourcePos(self.line, self.col)

    def _peek(self, ahead: int = 0) -> str:
        """現在位置から ahead 文字先を覗く。範囲外なら空文字。"""
        j = self.i + ahead
        return self.src[j] if j < len(self.src) else ""

    def _advance(self) -> str:
        """1 文字消費して返す。行・桁カウンタも更新する。"""
        ch = self.src[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _emit(self, kind: str, value: object, pos: SourcePos) -> None:
        self.tokens.append(Token(kind, value, pos))

    # ---- トークン化 -------------------------------------------------------

    def tokenize(self) -> list[Token]:
        """入力全体をトークン列へ変換する。最後に必ず EOF を付ける。"""
        while self.i < len(self.src):
            ch = self._peek()
            pos = self._pos()

            # --- 空白 (改行以外) は読み飛ばす ---
            if ch in " \t\r":
                self._advance()
                continue

            # --- 改行 → NEWLINE トークン ---
            if ch == "\n":
                self._advance()
                # 連続する空行で NEWLINE を量産しても害はないが、
                # パーサの見通しのため直前が NEWLINE なら重複を省く。
                if self.tokens and self.tokens[-1].kind == "NEWLINE":
                    continue
                self._emit("NEWLINE", None, pos)
                continue

            # --- ' コメント: 行末まで読み飛ばす ---
            if ch == "'":
                while self._peek() not in ("", "\n"):
                    self._advance()
                continue

            # --- 数値リテラル (整数 / 小数 / 指数 / &H 16進) ---
            if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
                self._lex_number(pos)
                continue

            # --- &H 16進リテラル (& 単独は文字列連結演算子) ---
            if ch == "&" and self._peek(1).upper() == "H":
                self._lex_hex(pos)
                continue

            # --- 文字列リテラル ---
            if ch == '"':
                self._lex_string(pos)
                continue

            # --- 識別子 / キーワード ---
            if ch.isalpha() or ch == "_":
                self._lex_word(pos)
                continue

            # --- : は文区切り ---
            if ch == ":":
                self._advance()
                self._emit("COLON", None, pos)
                continue

            # --- 演算子 (2 文字を先に照合) ---
            two = ch + self._peek(1)
            if two in TWO_CHAR_OPS:
                self._advance()
                self._advance()
                self._emit("OP", two, pos)
                continue
            if ch in ONE_CHAR_OPS:
                self._advance()
                self._emit("OP", ch, pos)
                continue

            raise CompileError(f"不正な文字です: {ch!r}", pos)

        # 最終行に改行が無くても文が終端するよう NEWLINE を補い、EOF を置く。
        if self.tokens and self.tokens[-1].kind != "NEWLINE":
            self._emit("NEWLINE", None, self._pos())
        self._emit("EOF", None, self._pos())
        return self.tokens

    # ---- 各リテラルの字句解析 ---------------------------------------------

    def _lex_number(self, pos: SourcePos) -> None:
        """数値リテラルを読む。

        文法:  digits [ "." digits ] [ ("E"|"e") ["+"|"-"] digits ] [ "#" | "!" ]
        - 小数点か指数部があれば float、無ければ int として value に格納。
        - 末尾の `#` (倍精度) `!` (単精度) サフィックスは「浮動小数点である」
          という指示として扱う。NBASIC-21 の浮動小数点は常に倍精度なので
          両者に意味の差はない。
        """
        text = ""
        is_float = False
        while self._peek().isdigit():
            text += self._advance()
        if self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            text += self._advance()          # '.'
            while self._peek().isdigit():
                text += self._advance()
        elif self._peek() == "." and not self._peek(1).isdigit():
            # "1." のような末尾ピリオドも浮動小数点として許す
            is_float = True
            text += self._advance()
        if self._peek() in "eE" and (self._peek(1).isdigit()
                                     or (self._peek(1) in "+-" and self._peek(2).isdigit())):
            is_float = True
            text += self._advance()          # 'E'
            if self._peek() in "+-":
                text += self._advance()
            while self._peek().isdigit():
                text += self._advance()
        if self._peek() in "#!":
            self._advance()                  # サフィックスは捨てて float 扱い
            is_float = True
        value: object = float(text) if is_float else int(text)
        self._emit("NUMBER", value, pos)

    def _lex_hex(self, pos: SourcePos) -> None:
        """&H に続く 16 進数リテラル。値は整数。例: &HFF → 255"""
        self._advance()                      # '&'
        self._advance()                      # 'H'
        text = ""
        while self._peek() in "0123456789abcdefABCDEF":
            text += self._advance()
        if not text:
            raise CompileError("&H の後に 16 進数の桁がありません", pos)
        self._emit("NUMBER", int(text, 16), pos)

    def _lex_string(self, pos: SourcePos) -> None:
        """文字列リテラルを読む。

        古典 BASIC の流儀で、文字列中の `""` は 1 個の `"` を表す。
        バックスラッシュエスケープは存在しない (仕様書 §2.4 参照)。
        文字列は行をまたげない。
        """
        self._advance()                      # 開きの '"'
        chars: list[str] = []
        while True:
            ch = self._peek()
            if ch in ("", "\n"):
                raise CompileError("文字列リテラルが閉じていません", pos)
            self._advance()
            if ch == '"':
                if self._peek() == '"':      # "" → " 1文字
                    chars.append('"')
                    self._advance()
                    continue
                break                        # 閉じの '"'
            chars.append(ch)
        self._emit("STRING", "".join(chars), pos)

    def _lex_word(self, pos: SourcePos) -> None:
        """識別子またはキーワードを読む。

        識別子は英字/アンダースコアで始まり、英数字/アンダースコアが続き、
        末尾に型サフィックス 1 個 (% # ! $) を許す。読み取り後に大文字化し、
        キーワード表に載っていれば KEYWORD、なければ IDENT として発行する。

        REM キーワードだけは特別扱い: 続く行末までがコメントなので、
        ここで読み飛ばしてトークン自体を発行しない。
        """
        text = ""
        while self._peek().isalnum() or self._peek() == "_":
            text += self._advance()
        if self._peek() in "%#!$":           # 型サフィックス
            text += self._advance()
        upper = text.upper()

        if upper == "REM":
            while self._peek() not in ("", "\n"):
                self._advance()
            return

        if upper == "DATA":
            # DATA 文の項目は「生テキスト」であり通常の字句規則に従わない
            # (例: DATA HELLO WORLD, 3.14)。そこで DATA キーワードを発行した
            # 直後は行末まで専用の読み方に切り替える。
            self._emit("KEYWORD", upper, pos)
            self._lex_data_items()
            return

        if upper in KEYWORDS:
            self._emit("KEYWORD", upper, pos)
        else:
            self._emit("IDENT", upper, pos)

    def _lex_data_items(self) -> None:
        """DATA 文の項目列を行末まで読む (仕様書 §9.1)。

        項目はカンマ区切り。各項目は
          - 引用符付き文字列 ("" は " 1文字)。カンマや空白を含められる。
          - 引用符なしの生テキスト。前後の空白を取り除いたもの。
        として STRING トークンで発行し、区切りのカンマは OP "," で発行する。
        数値も文字列として保持し、READ 側の変数型で実行時に解釈する。
        DATA 行内ではコロンやアポストロフィも項目の一部として扱う
        (古典 BASIC と同じ)。
        """
        while True:
            # 項目前の空白 (改行以外) を読み飛ばす
            while self._peek() in " \t\r":
                self._advance()
            pos = self._pos()
            if self._peek() in ("", "\n"):
                break
            if self._peek() == '"':
                # 引用符付き項目: 通常の文字列リテラルと同じ規則
                self._lex_string(pos)
            else:
                # 引用符なし項目: カンマか行末まで読み、末尾空白を落とす
                chars: list[str] = []
                while self._peek() not in ("", "\n", ","):
                    chars.append(self._advance())
                self._emit("STRING", "".join(chars).strip(), pos)
            # 項目の後: カンマなら次の項目へ、行末なら終了
            while self._peek() in " \t\r":
                self._advance()
            if self._peek() == ",":
                cpos = self._pos()
                self._advance()
                self._emit("OP", ",", cpos)
                continue
            break


def tokenize(source: str) -> list[Token]:
    """モジュールの公開エントリポイント。"""
    return Lexer(source).tokenize()
