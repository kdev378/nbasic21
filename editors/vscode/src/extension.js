/*
 * extension.js — NBASIC-21 の VS Code 拡張本体
 * =============================================
 *
 * 依存パッケージなし・ビルド不要の素の JavaScript 拡張。機能は 3 つ:
 *
 * 1. 保存時診断
 *    保存のたびにコンパイラを `--check` で走らせ、
 *    「ファイル:行:桁: error: メッセージ」形式のエラー出力を
 *    エディタの波線 (Diagnostics) に変換する。LSP サーバは使わず、
 *    コンパイラ自身を検査器として使う最小構成。
 *
 * 2. コンパイル & 実行 (F5 / エディタ右上の ▶)
 *    統合ターミナルで  nbasic → C コンパイラ → 実行  を連結して流す。
 *    INPUT や INKEY$ を使うプログラムのために「ターミナルで実行する」
 *    ことが重要 (出力チャネルでは対話できない)。
 *
 * 3. IR 表示
 *    `--emit-ir -O` の出力を新しいエディタタブで開く。コンパイラの
 *    中身を覗くための教材ボタン。
 *
 * コンパイラの場所 (compilerRoot) は次の順で決める:
 *   設定 nbasic.compilerRoot → ワークスペースフォルダのどれかに
 *   nbasic/__main__.py があればそこ → 編集中ファイルから上へ探索。
 */

"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

/** 診断のコレクション (拡張全体で 1 個) */
let diagnostics;

/** 実行用ターミナル (使い回すと cwd が古くなるので都度作り直す) */
let runTerminal = null;

// ------------------------------------------------------------------
// 設定とコンパイラの場所
// ------------------------------------------------------------------

function config() {
    return vscode.workspace.getConfiguration("nbasic");
}

/** dir が nbasic21 リポジトリのルートか (= コンパイラを実行できるか) */
function isCompilerRoot(dir) {
    return fs.existsSync(path.join(dir, "nbasic", "__main__.py"));
}

/**
 * コンパイラのルートディレクトリを解決する。
 * 見つからなければ null (呼び出し側がエラーメッセージを出す)。
 */
function findCompilerRoot(documentUri) {
    // (1) 明示設定が最優先
    const configured = config().get("compilerRoot");
    if (configured && isCompilerRoot(configured)) {
        return configured;
    }
    // (2) ワークスペースフォルダを探す
    for (const folder of vscode.workspace.workspaceFolders || []) {
        if (isCompilerRoot(folder.uri.fsPath)) {
            return folder.uri.fsPath;
        }
    }
    // (3) 編集中ファイルの位置から親へたどる (リポジトリ内の深い場所で
    //     単一ファイルを開いている場合のため)
    if (documentUri && documentUri.scheme === "file") {
        let dir = path.dirname(documentUri.fsPath);
        for (let i = 0; i < 10; i++) {
            if (isCompilerRoot(dir)) {
                return dir;
            }
            const parent = path.dirname(dir);
            if (parent === dir) {
                break;
            }
            dir = parent;
        }
    }
    return null;
}

/** シェルに渡すパスの引用 (空白対策の最小限) */
function q(p) {
    return /[ \t]/.test(p) ? `"${p}"` : p;
}

// ------------------------------------------------------------------
// 保存時診断 (--check)
// ------------------------------------------------------------------

/**
 * コンパイラの --check を走らせ、標準エラー出力の
 *   ファイル名:行:桁: error: メッセージ
 * を Diagnostic に変換して document に付ける。
 */
function checkDocument(document) {
    if (document.languageId !== "nbasic") {
        return;
    }
    if (!config().get("checkOnSave")) {
        return;
    }
    const root = findCompilerRoot(document.uri);
    if (root === null) {
        return; // コンパイラが見つからない環境では黙って何もしない
    }
    const python = config().get("pythonPath");

    cp.execFile(
        python,
        ["-m", "nbasic", "--check", document.uri.fsPath],
        { cwd: root, timeout: 15000 },
        (_err, _stdout, stderr) => {
            const found = [];
            // コンパイラは最初のエラーで停止するが、将来複数返しても
            // よいように全行をなめる
            const re = /^.*:(\d+):(\d+): error: (.*)$/gm;
            let m;
            while ((m = re.exec(stderr)) !== null) {
                const line = Math.max(0, parseInt(m[1], 10) - 1);
                const col = Math.max(0, parseInt(m[2], 10) - 1);
                // 波線はエラー桁から行末まで引く (単語境界の計算は
                // しない — BASIC は行指向なので行末までで十分読める)
                let range;
                if (line < document.lineCount) {
                    const lineEnd = document.lineAt(line).range.end;
                    range = new vscode.Range(line, Math.min(col, lineEnd.character), line, lineEnd.character);
                    if (range.isEmpty) {
                        range = document.lineAt(line).range;
                    }
                } else {
                    range = new vscode.Range(0, 0, 0, 1);
                }
                found.push(new vscode.Diagnostic(
                    range, m[3], vscode.DiagnosticSeverity.Error));
            }
            diagnostics.set(document.uri, found);
        });
}

// ------------------------------------------------------------------
// コンパイル & 実行
// ------------------------------------------------------------------

/**
 * ビルドコマンド列を組み立てる。
 * 戻り値: { commandLine, exePath } または null (エラー表示済み)。
 *
 * 生成物はソースを汚さないよう OS の一時ディレクトリに置く。
 */
function buildCommand(document) {
    const root = findCompilerRoot(document.uri);
    if (root === null) {
        vscode.window.showErrorMessage(
            "NBASIC-21 コンパイラが見つかりません。設定 nbasic.compilerRoot に " +
            "リポジトリのルート (nbasic/ と runtime/ がある場所) を指定してください。");
        return null;
    }
    const cfg = config();
    const python = cfg.get("pythonPath");
    const cc = cfg.get("ccPath");
    const optFlag = cfg.get("optimize") ? "-O " : "";

    const src = document.uri.fsPath;
    const base = path.basename(src, path.extname(src));
    const tmp = os.tmpdir();
    const cFile = path.join(tmp, `nbasic_${base}.c`);
    const exePath = path.join(
        tmp, `nbasic_${base}${process.platform === "win32" ? ".exe" : ""}`);
    const runtime = path.join(root, "runtime");

    // nbasic → C コンパイラ → (実行) を && で連結する。
    // 注: Windows の古い PowerShell (5.x) は && を解さないので、
    //     その場合は既定シェルを cmd か PowerShell 7 にすること (README)。
    const compile =
        `${q(python)} -m nbasic ${optFlag}-t c -o ${q(cFile)} ${q(src)} && ` +
        `${q(cc)} -O2 -I ${q(runtime)} ${q(cFile)} ` +
        `${q(path.join(runtime, "nbrt.c"))} -lm -o ${q(exePath)}`;
    return { compile, exePath, root };
}

/** ビルド (+ 実行) を統合ターミナルで走らせる */
function runInTerminal(document, alsoRun) {
    const built = buildCommand(document);
    if (built === null) {
        return;
    }
    // INPUT / INKEY$ のためにターミナルで実行する。cwd はソースのある
    // ディレクトリ (OPEN の相対パスが直感通りになる)。
    if (runTerminal !== null) {
        runTerminal.dispose();
    }
    runTerminal = vscode.window.createTerminal({
        name: "NBASIC",
        cwd: path.dirname(document.uri.fsPath),
    });
    runTerminal.show(true);
    const cmd = alsoRun
        ? `${built.compile} && ${q(built.exePath)}`
        : `${built.compile} && echo BUILD OK: ${q(built.exePath)}`;
    runTerminal.sendText(cmd);
}

async function commandRunFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "nbasic") {
        return;
    }
    await editor.document.save();
    runInTerminal(editor.document, /* alsoRun= */ true);
}

async function commandBuildFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "nbasic") {
        return;
    }
    await editor.document.save();
    runInTerminal(editor.document, /* alsoRun= */ false);
}

// ------------------------------------------------------------------
// IR 表示
// ------------------------------------------------------------------

async function commandShowIR() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "nbasic") {
        return;
    }
    await editor.document.save();
    const document = editor.document;
    const root = findCompilerRoot(document.uri);
    if (root === null) {
        vscode.window.showErrorMessage("NBASIC-21 コンパイラが見つかりません。");
        return;
    }
    const python = config().get("pythonPath");
    const optFlag = config().get("optimize") ? ["-O"] : [];

    cp.execFile(
        python,
        ["-m", "nbasic", "--emit-ir", ...optFlag, document.uri.fsPath],
        { cwd: root, timeout: 15000 },
        async (err, stdout, stderr) => {
            if (err) {
                vscode.window.showErrorMessage(
                    "IR の生成に失敗しました: " + stderr.trim());
                return;
            }
            const doc = await vscode.workspace.openTextDocument({
                content: stdout,
                language: "plaintext",
            });
            await vscode.window.showTextDocument(doc, {
                viewColumn: vscode.ViewColumn.Beside,
                preview: true,
            });
        });
}

// ------------------------------------------------------------------
// 活性化 / 終了
// ------------------------------------------------------------------

function activate(context) {
    diagnostics = vscode.languages.createDiagnosticCollection("nbasic");
    context.subscriptions.push(diagnostics);

    context.subscriptions.push(
        vscode.commands.registerCommand("nbasic.runFile", commandRunFile),
        vscode.commands.registerCommand("nbasic.buildFile", commandBuildFile),
        vscode.commands.registerCommand("nbasic.showIR", commandShowIR),
        // 保存・オープン時に診断を更新、クローズ時に消す
        vscode.workspace.onDidSaveTextDocument(checkDocument),
        vscode.workspace.onDidOpenTextDocument(checkDocument),
        vscode.workspace.onDidCloseTextDocument(
            (doc) => diagnostics.delete(doc.uri)),
    );

    // 既に開いているファイルにも初回の診断をかける
    for (const doc of vscode.workspace.textDocuments) {
        checkDocument(doc);
    }
}

function deactivate() {
    if (runTerminal !== null) {
        runTerminal.dispose();
    }
}

module.exports = { activate, deactivate };
