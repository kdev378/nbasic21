# NBASIC-21 for Visual Studio Code

NBASIC-21 ([リポジトリのルート](../../README.md) 参照) の言語サポート拡張。

## 機能

| 機能 | 説明 |
|---|---|
| シンタックスハイライト | キーワード・組込関数・行番号・ラベル・DATA・文字列 (`""` エスケープ対応) |
| スニペット | `for` `if` `select` `sub` `function` `openread` `stdin` `gameloop` など |
| 保存時のエラー診断 | 保存するとコンパイラの `--check` が走り、エラーが波線 + 問題パネルに出る |
| コンパイル & 実行 | **F5** (またはエディタ右上の ▶) でビルドして統合ターミナルで実行 |
| コンパイルのみ | コマンドパレット「NBASIC: コンパイルのみ」 |
| IR 表示 | コマンドパレット「NBASIC: IR (中間表現) を表示」— 最適化後の三番地コードが横に開く |

実行は統合ターミナルで行うので、`INPUT` や `INKEY$` を使う対話的な
プログラム・TUI もそのまま動く。作業ディレクトリはソースファイルの
あるフォルダになる (`OPEN` の相対パスが直感通りに解決される)。

## インストール

ビルド不要の素の JavaScript 拡張なので、2 通りの入れ方がある。

### 方法 1: フォルダをそのままコピー (一番簡単)

```sh
# Linux / macOS
cp -r editors/vscode ~/.vscode/extensions/nbasic21.nbasic21-0.1.0

# Windows (PowerShell)
Copy-Item -Recurse editors\vscode "$env:USERPROFILE\.vscode\extensions\nbasic21.nbasic21-0.1.0"
```

VS Code を再起動すると `.bas` ファイルで有効になる。

### 方法 2: VSIX にパッケージしてインストール

```sh
cd editors/vscode
npx --yes @vscode/vsce package    # → nbasic21-0.1.0.vsix
code --install-extension nbasic21-0.1.0.vsix
```

## 必要な設定

コンパイラ (このリポジトリ) と C コンパイラが必要:

| 設定 | 既定値 | 説明 |
|---|---|---|
| `nbasic.pythonPath` | `python3` | Windows では `py` や `python` に変える |
| `nbasic.compilerRoot` | (自動検出) | リポジトリのルート。**このリポジトリをワークスペースとして開いていれば設定不要** |
| `nbasic.ccPath` | `cc` | `gcc` / `clang`。Windows では MinGW の `gcc` など |
| `nbasic.optimize` | `true` | `-O` (IR 最適化) を付けるか |
| `nbasic.checkOnSave` | `true` | 保存時診断のオン/オフ |

リポジトリの外で `.bas` を書く場合だけ `nbasic.compilerRoot` を
設定すること (例: `/home/me/src/nbasic21`)。

## 注意

- 実行コマンドは `&&` でチェーンする。Windows で既定シェルが
  Windows PowerShell 5.x の場合は `&&` が使えないため、既定の
  ターミナルを **cmd** か **PowerShell 7+** にすること。
- 診断はコンパイラが最初に見つけた 1 個のエラーを表示する
  (コンパイラが最初のエラーで停止する仕様のため)。
