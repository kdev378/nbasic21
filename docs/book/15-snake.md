# 第 15 章 プロジェクト①: スネークゲーム

いよいよ総合演習です。ヘビを操作してエサを食べ、食べるほど体が
伸びていく — 携帯電話の黎明期に世界中を夢中にさせた「スネーク」を
ゼロから作ります。この章の主役はコードそのものではなく、
**大きなものを小さな段階に分けて作る**という進め方です。

## 15.1 いきなり全部作らない

初心者が挫折する最大の原因は「全部を一度に作ろうとする」こと。
プロは必ず**動く状態を保ったまま少しずつ育てます**。今回の計画:

1. 段階 1: 頭だけのヘビが右に進む
2. 段階 2: キーで曲がれる。壁にぶつかったら終了
3. 段階 3: 体がついてくる (配列の出番!)
4. 段階 4: エサを食べると体が伸びる
5. 段階 5: 自分の体にぶつかったら終了。スコア表示

各段階で必ず実行して遊びます。「動く→ちょい足し→動く→ちょい足し」
のリズムを体で覚えてください。

## 15.2 段階 1〜2: 動く頭

第 14 章のゲームループに「向き」の変数を足しただけです。
向きを (DX%, DY%) のペアで持つのがポイント — 右なら (1, 0)、
上なら (0, -1)。「位置に向きを足し続ける」と勝手に進みます:

```basic
' snake1.bas — 段階 1〜2: 曲がれる頭 + 壁
CLS
' ---- 壁を描く (盤面は 2〜21 行、2〜59 桁) ----
FOR I% = 1 TO 60
  LOCATE 1, I%
  PRINT "#";
  LOCATE 22, I%
  PRINT "#";
NEXT I%
FOR I% = 1 TO 22
  LOCATE I%, 1
  PRINT "#";
  LOCATE I%, 60
  PRINT "#";
NEXT I%

X% = 30
Y% = 11        ' 位置
DX% = 1
DY% = 0        ' 向き (最初は右)

DO
  K$ = INKEY$
  IF K$ = "q" THEN EXIT DO
  IF K$ = "w" THEN DX% = 0 : DY% = -1
  IF K$ = "s" THEN DX% = 0 : DY% = 1
  IF K$ = "a" THEN DX% = -1 : DY% = 0
  IF K$ = "d" THEN DX% = 1 : DY% = 0

  LOCATE Y%, X%
  PRINT " ";                   ' 前の位置を消す
  X% = X% + DX%
  Y% = Y% + DY%
  IF X% <= 1 OR X% >= 60 OR Y% <= 1 OR Y% >= 22 THEN EXIT DO
  LOCATE Y%, X%
  PRINT "@";

  SLEEP 0.08
LOOP
LOCATE 24, 1
PRINT "ゲームオーバー"
```

ここまでで既に「操作できて、死ねる」— ゲームの最小骨格が
できています。遊んで動きを確かめてから先へ。

## 15.3 段階 3 の考えどころ: 体をどう覚えるか

ヘビの体は「マス目の列」です。**配列 2 本** (X 座標の列と
Y 座標の列) で表しましょう。`BX%(0), BY%(0)` が頭、
`BX%(1), BY%(1)` がその次、…、`BX%(LEN%-1)` がしっぽ。

1 マス進むとき、体はどう動くでしょう? じっと観察すると —
**「新しい頭が 1 個生え、しっぽが 1 個消える」だけ**で、
体の途中は動いていません。そこで:

1. しっぽの画面表示を消す
2. 配列を 1 個ずつ後ろへずらす (第 6 章の練習 4 でやった
   「配列をずらす」の実戦投入!)
3. 先頭に新しい頭の座標を入れ、画面に描く

エサを食べたときは「しっぽを消さず、ずらす前に長さを 1 増やす」
— つまり**消えないしっぽ = 成長**です。この気づきがこのゲームの
アルゴリズムの核心です。

## 15.4 完成版

段階 3〜5 を組み込んだ完成版です。長く見えますが、
段階 1〜2 のコードがそのまま中に残っていることを確認しながら
読んでください:

```basic
' snake.bas — スネークゲーム 完成版
' 操作: w/a/s/d で移動、q であきらめる
RANDOMIZE

' ==== 定数と盤面のサイズ ====
CONST TOP% = 1, BOTTOM% = 22, LEFT% = 1, RIGHT% = 60

' ==== ヘビの体 (BX%/BY% の 0 番が頭) ====
DIM BX%(500), BY%(500)
SNAKELEN% = 3                  ' 最初は 3 マス
DIRX% = 1
DIRY% = 0                      ' 右向きでスタート
FOR I% = 0 TO SNAKELEN% - 1
  BX%(I%) = 30 - I%            ' 横に 3 マス並べて配置
  BY%(I%) = 11
NEXT I%

' ==== 画面の用意 ====
CLS
FOR I% = LEFT% TO RIGHT%
  LOCATE TOP%, I%
  PRINT "#";
  LOCATE BOTTOM%, I%
  PRINT "#";
NEXT I%
FOR I% = TOP% TO BOTTOM%
  LOCATE I%, LEFT%
  PRINT "#";
  LOCATE I%, RIGHT%
  PRINT "#";
NEXT I%
FOR I% = 0 TO SNAKELEN% - 1    ' 初期の体を描いておく
  LOCATE BY%(I%), BX%(I%)
  PRINT "o";
NEXT I%

' ==== 最初のエサを置く ====
GOSUB PutFood

SCORE% = 0
DO
  ' ---- (1) 入力 ----
  K$ = INKEY$
  IF K$ = "q" THEN EXIT DO
  IF K$ = "w" AND DIRY% = 0 THEN DIRX% = 0 : DIRY% = -1
  IF K$ = "s" AND DIRY% = 0 THEN DIRX% = 0 : DIRY% = 1
  IF K$ = "a" AND DIRX% = 0 THEN DIRX% = -1 : DIRY% = 0
  IF K$ = "d" AND DIRX% = 0 THEN DIRX% = 1 : DIRY% = 0
  ' (DIRY% = 0 のチェックは「真後ろへの折り返し禁止」——
  '  上下に動いていない時しか上下へ曲がれない)

  ' ---- (2) 新しい頭の位置を計算 ----
  NEWX% = BX%(0) + DIRX%
  NEWY% = BY%(0) + DIRY%

  ' ---- (3) 衝突判定: 壁 ----
  IF NEWX% <= LEFT% OR NEWX% >= RIGHT% OR NEWY% <= TOP% OR NEWY% >= BOTTOM% THEN
    EXIT DO
  END IF
  ' ---- 衝突判定: 自分の体 (線形探索! 第 9 章) ----
  HIT% = 0
  FOR I% = 0 TO SNAKELEN% - 1
    IF BX%(I%) = NEWX% AND BY%(I%) = NEWY% THEN HIT% = -1
  NEXT I%
  IF HIT% THEN EXIT DO

  ' ---- (4) エサを食べた? ----
  IF NEWX% = FOODX% AND NEWY% = FOODY% THEN
    SCORE% = SCORE% + 10
    SNAKELEN% = SNAKELEN% + 1  ' 成長 = しっぽが消えない
    GOSUB PutFood
  ELSE
    ' しっぽを画面から消す (成長しない普通の一歩)
    LOCATE BY%(SNAKELEN% - 1), BX%(SNAKELEN% - 1)
    PRINT " ";
  END IF

  ' ---- (5) 体をずらして新しい頭を差し込む ----
  FOR I% = SNAKELEN% - 1 TO 1 STEP -1
    BX%(I%) = BX%(I% - 1)
    BY%(I%) = BY%(I% - 1)
  NEXT I%
  BX%(0) = NEWX%
  BY%(0) = NEWY%

  ' ---- (6) 描画 ----
  LOCATE BY%(1), BX%(1)
  PRINT "o";                   ' さっきまで頭だった場所は体に
  LOCATE BY%(0), BX%(0)
  PRINT "@";                   ' 新しい頭
  LOCATE TOP%, 5
  PRINT " SCORE:"; SCORE%; "";

  ' ---- (7) ひと呼吸 ----
  SLEEP 0.08
LOOP

COLOR 7
LOCATE BOTTOM% + 2, 1
PRINT "ゲームオーバー! スコア:"; SCORE%
END

' ==== サブルーチン: エサをヘビと重ならない場所に置く ====
PutFood:
DO
  FOODX% = LEFT% + 1 + INT(RND * (RIGHT% - LEFT% - 1))
  FOODY% = TOP% + 1 + INT(RND * (BOTTOM% - TOP% - 1))
  OK% = -1
  FOR I% = 0 TO SNAKELEN% - 1
    IF BX%(I%) = FOODX% AND BY%(I%) = FOODY% THEN OK% = 0
  NEXT I%
LOOP UNTIL OK%
LOCATE FOODY%, FOODX%
PRINT "*";
RETURN
```

`tools/nbc run work/snake.bas` — 遊んでみてください。

## 15.5 読みどころ解説

このプログラムは、本書で学んだことの見本市です:

- **配列のずらし** (第 6 章) が体の移動そのもの
- **線形探索** (第 9 章) が自己衝突判定とエサの重なり判定
- **GOSUB** (第 8 章コラム) — エサ置き処理は 2 か所から使うので
  サブルーチンに。引数が要らない小さな共通処理には GOSUB も
  まだまだ現役です
- `CONST` で盤面サイズに**名前をつけた**ので、あちこちに 60 や 22
  が散らばらず、サイズ変更が 1 行で済む
- 「真後ろ折り返し禁止」のような**仕様の小さなこだわり**が
  遊び心地を決める — `AND DIRY% = 0` の 1 個の条件に注目

## 15.6 改造してこそ自分のもの

ゲームは改造の教材として最強です。易しい順に:

1. **スピードアップ**: スコアが上がるたび `SLEEP` を短くする
2. **色**: 頭は黄色 (`COLOR 14`)、エサは赤、体は緑に
3. **ハイスコア**: 第 12 章の APPEND でスコアをファイルに記録し、
   起動時に過去最高を表示する
4. **障害物**: 盤面のランダムな位置に `#` を数個置き、
   ぶつかったら終了 (衝突判定に 1 条件足すだけ)
5. **毒エサ**: たまに `x` が出て、食べると体が**縮む**
   (縮んだ分のしっぽを消すのを忘れずに!)

## 練習問題

この章の練習問題は上の改造リストです。最低 1 つ、できれば 3 つ
やってみてください。改造 3 (ハイスコア) までできたら、
あなたはもう立派に「プログラムが書ける人」です。

[改造例はこちら](answers.md#第-15-章)

---

[← 第 14 章](14-tui.md) | [目次](README.md) | [第 16 章 プロジェクト②: ToDo 管理アプリ →](16-todo-app.md)
