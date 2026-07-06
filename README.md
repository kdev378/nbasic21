# NBASIC-21

行番号付きの古典 BASIC に現代的な構造化機能を加えた言語
**NBASIC-21** のコンパイラ / クロスコンパイラ。

- **古典互換**: 行番号、`GOTO`/`GOSUB`、`DATA`/`READ`、型サフィックス
  (`%` `#` `!` `$`)、`PRINT` の桁ゾーン、暗黙の変数宣言
- **現代的機能**: ブロック `IF`/`ELSEIF`、`SELECT CASE`、`DO`/`LOOP`、
  `SUB`/`FUNCTION` (再帰・前方参照可)、ローカル変数、`CONST`、
  `EXIT` 文、名前ラベル、`AS INTEGER/DOUBLE/STRING` 型宣言
- **CLI 向け**: ファイル入出力 (`OPEN`/`PRINT #`/`INPUT #`/
  `LINE INPUT #`/`EOF`)、コマンドライン引数 (`COMMAND$`)、
  終了コード (`END 式`)、標準入力の EOF 検査 (`EOF(0)`)
- **TUI 向け**: `CLS`/`LOCATE`/`COLOR` (ANSI、Windows 10+ の VT モード
  自動有効化)、ノンブロッキングキー入力 `INKEY$`、`SLEEP`
- **3 つのバックエンド** (共通の三番地コード IR から生成):
  - **C** — 可搬。手元の cc でビルドしてどこでも実行 (macOS/ARM も
    こちらで)
  - **x86-64 Windows** — Microsoft x64 呼び出し規約の NASM アセンブリ。
    Linux/macOS から mingw-w64 でクロスコンパイル可能
  - **x86-64 Linux** — System V AMD64 ABI の NASM アセンブリ。
    nasm + gcc/clang でネイティブビルド

```
.bas → 字句解析 → 構文解析 → 意味解析 → IR → 最適化(-O) → C / x64 asm
```

## 必要なもの

- コンパイラ本体: Python 3.10+ (標準ライブラリのみ)
- C ターゲット: 任意の C99 コンパイラ (gcc / clang / MSVC)
- x64 ターゲット: [NASM](https://nasm.us) と、リンクのために
  mingw-w64 (Linux/macOS からのクロス) または Windows 上の gcc/clang

## 使い方

### C ターゲット (おすすめ・可搬)

```sh
python3 -m nbasic -O examples/fizzbuzz.bas          # → examples/fizzbuzz.c
cc -O2 -I runtime examples/fizzbuzz.c runtime/nbrt.c -lm -o fizzbuzz
./fizzbuzz
```

### x86-64 Windows ターゲット (クロスコンパイル)

```sh
python3 -m nbasic -t x64 -O examples/fizzbuzz.bas   # → examples/fizzbuzz.asm
nasm -f win64 examples/fizzbuzz.asm -o fizzbuzz.obj
x86_64-w64-mingw32-gcc -I runtime fizzbuzz.obj runtime/nbrt.c -o fizzbuzz.exe
wine fizzbuzz.exe        # または Windows 上で実行
```

### x86-64 Linux ターゲット (ネイティブアセンブリ)

```sh
python3 -m nbasic -t x64-linux -O examples/fizzbuzz.bas
nasm -f elf64 examples/fizzbuzz.asm -o fizzbuzz.o
gcc fizzbuzz.o runtime/nbrt.c -lm -o fizzbuzz
./fizzbuzz
```

Windows 上でセルフビルドする場合は最後のリンクを
`gcc -I runtime fizzbuzz.obj runtime\nbrt.c -o fizzbuzz.exe` にする。

### その他のオプション

```sh
python3 -m nbasic --emit-ir -O program.bas   # 最適化後の IR を表示
python3 -m nbasic --check program.bas        # エラー検査のみ (エディタ連携用)
python3 -m nbasic -o out.c program.bas       # 出力ファイル名の指定
```

### VS Code 拡張

[editors/vscode/](editors/vscode/) にシンタックスハイライト・
スニペット・**F5 でコンパイル & 実行**・保存時のエラー診断 (波線表示)・
IR 表示コマンドを備えた拡張がある。インストール方法は
[editors/vscode/README.md](editors/vscode/README.md) を参照
(フォルダをコピーするだけでも入る)。

## 例

```basic
100 REM 古典スタイルもそのまま動く
110 FOR I% = 1 TO 5
120   GOSUB 200
130 NEXT I%
140 END
200 PRINT "SQUARE OF"; I%; "IS"; I% * I%
210 RETURN
```

```basic
' 現代スタイル: 再帰関数と SELECT CASE
FOR N% = 1 TO 15
  SELECT CASE N% MOD 15
    CASE 0
      PRINT "FizzBuzz"
    CASE 3, 6, 9, 12
      PRINT "Fizz"
    CASE 5, 10
      PRINT "Buzz"
    CASE ELSE
      PRINT "" & N%
  END SELECT
NEXT N%

FUNCTION Fib% (N% AS INTEGER)
  IF N% < 2 THEN RETURN N%
  RETURN Fib%(N% - 1) + Fib%(N% - 2)
END FUNCTION
```

その他のサンプルは [examples/](examples/) を参照
(エラトステネスのふるい、文字列ソート、数当てゲーム、
`wc` 風の CLI ツールなど)。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | 言語仕様書 (字句規則・型・演算子・全文法 EBNF・組込関数・エラー一覧) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | コンパイラ内部設計 (IR 仕様・ランタイム ABI・各バックエンドの戦略) |

## リポジトリ構成

```
nbasic/            コンパイラ本体 (Python パッケージ)
  lexer.py           字句解析
  parser.py          構文解析 (再帰下降)
  ast_nodes.py       AST 定義
  analyzer.py        意味解析 (記号表・型検査)
  ir.py              中間表現 (型付き三番地コード)
  irgen.py           IR 生成 (低水準化)
  optimizer.py       IR 最適化 (-O)
  backend_c.py       C コード生成
  backend_x64.py     x86-64 共通基盤 + Windows x64 (Microsoft ABI)
  backend_x64_linux.py  x86-64 Linux (System V ABI)
  driver.py          CLI / パイプライン結線
runtime/           C ランタイムライブラリ (両バックエンド共通)
  nbrt.h nbrt.c      文字列・配列・入出力・数値検査・GOSUB スタック
examples/          サンプルプログラム
docs/              言語仕様・内部設計
tests/             統合テスト (ゴールデン + x64 クロス検証 + エラー)
editors/vscode/    VS Code 拡張 (ハイライト・診断・F5 実行・IR 表示)
```

## テスト

```sh
python3 tests/run_tests.py
```

C バックエンドの全サンプルのゴールデンテストに加え、`nasm` /
`x86_64-w64-mingw32-gcc` / `wine` が揃っている環境では x64 バック
エンドで同じプログラムを Windows 実行物としてビルド・実行し、
出力が一致することを検証する。

## ライセンス

MIT — [LICENSE](LICENSE) を参照。
