"""
errors.py — コンパイルエラーの共通表現
=====================================

コンパイラの全ステージ (字句解析・構文解析・意味解析) は、ユーザーの
ソースコードに問題を見つけると `CompileError` を送出する。
エラーには必ず「ソース上の位置 (行・桁)」を持たせ、ドライバが
`ファイル名:行:桁: メッセージ` の形式で表示する。

内部バグ (コンパイラ自身の不整合) は通常の AssertionError 等で落とし、
CompileError とは区別する。
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePos:
    """ソースコード上の位置。行・桁ともに 1 始まり。

    行番号 (line) は「物理行」であって BASIC の行番号ラベルとは無関係
    である点に注意。エラーメッセージはエディタで探しやすい物理行を使う。
    """
    line: int
    col: int

    def __str__(self) -> str:
        return f"{self.line}:{self.col}"


class CompileError(Exception):
    """ユーザーのソースコードに起因するエラー。

    message : 人間向けのエラー説明
    pos     : エラーの発生位置 (不明な場合は None)
    """

    def __init__(self, message: str, pos: SourcePos | None = None):
        super().__init__(message)
        self.message = message
        self.pos = pos

    def format(self, filename: str) -> str:
        """`ファイル名:行:桁: error: メッセージ` 形式に整形する。"""
        if self.pos is not None:
            return f"{filename}:{self.pos}: error: {self.message}"
        return f"{filename}: error: {self.message}"
