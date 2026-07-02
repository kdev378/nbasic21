/*
 * nbrt.h — NBASIC-21 ランタイムライブラリ公開ヘッダ
 * ==================================================
 *
 * コンパイラの両バックエンド (C / x86-64) が生成するコードは、
 * 複雑な処理をすべてこのランタイムの関数呼び出しとして表現する。
 * ここに宣言されている関数群が、生成コードとランタイムの「ABI 契約」
 * である。x86-64 バックエンドはこのヘッダを読まずにシンボル名と
 * 引数の並びだけを知って呼び出すため、**関数の引数はすべて 8 バイト
 * (int64_t / double / ポインタ) に統一**してある。
 *
 * 型の対応 (docs/ARCHITECTURE.md §5):
 *   BASIC の INTEGER → int64_t
 *   BASIC の DOUBLE  → double
 *   BASIC の STRING  → nb_str* (イミュータブルな文字列記述子へのポインタ)
 *   BASIC の配列     → int64_t (ランタイム内の配列表を指すハンドル ID)
 *
 * 真理値の規約: 真 = -1, 偽 = 0 (古典 BASIC 互換。仕様書 §5.3)
 *
 * メモリ管理: ランタイムが作る文字列・配列はすべて内部アリーナから
 * 割り付けられ、プログラム終了時に一括解放される (nbrt.c 冒頭参照)。
 * 生成コードが個々に解放する必要はない。
 */

#ifndef NBRT_H
#define NBRT_H

/* MinGW では既定の printf が MSVCRT 版になり %lld 系の挙動が揺れるため、
 * C99 準拠の実装に切り替える。stdio.h を include する前に定義すること。 */
#if defined(__MINGW32__) || defined(__MINGW64__)
#define __USE_MINGW_ANSI_STDIO 1
#endif

#include <stdint.h>

/* ------------------------------------------------------------------ */
/* 文字列                                                              */
/* ------------------------------------------------------------------ */

/* イミュータブルな文字列記述子。
 * data は len バイトの本体を指す (ランタイム生成分は NUL 終端も付ける
 * が、リテラルに NUL を含められるよう長さを正とする)。
 * 一度作った nb_str の内容は決して変更されない — BASIC の文字列は
 * 値セマンティクスなので、共有してもコピーしても意味が変わらない。 */
typedef struct nb_str {
    int64_t     len;
    const char *data;
} nb_str;

/* ------------------------------------------------------------------ */
/* 生成コードが定義するシンボル (バックエンドとの契約)                 */
/* ------------------------------------------------------------------ */

/* メインプログラム本体。ランタイムの main() から呼ばれる。 */
extern void nb_basic_main(void);

/* DATA 文の項目表。項目が無くても count=0 で必ず定義される。 */
extern const char *const nb_data_items[];
extern const int64_t     nb_data_count;

/* ------------------------------------------------------------------ */
/* 実行制御                                                            */
/* ------------------------------------------------------------------ */

void nb_end(void);                    /* END/STOP: 後始末して exit(0)  */
void nb_fatal(const char *msg);       /* 実行時エラー: 表示して exit(1) */
void nb_fatal_bad_return(void);       /* GOSUB ディスパッチャの保険     */

/* GOSUB/RETURN 用の復帰 ID スタック (docs/ARCHITECTURE.md §4.3) */
void    nb_gosub_push(int64_t id);
int64_t nb_gosub_pop(void);           /* 空なら "RETURN without GOSUB" */

/* ------------------------------------------------------------------ */
/* 出力 (PRINT)                                                        */
/* ------------------------------------------------------------------ */

void nb_print_i64(int64_t v);         /* 正数は先頭に空白、末尾に空白  */
void nb_print_f64(double v);          /* %.15g 相当。同上の空白規則    */
void nb_print_str(nb_str *s);
void nb_print_tab(void);              /* `,` : 次の 14 桁ゾーンへ      */
void nb_print_nl(void);               /* 改行                          */

/* ------------------------------------------------------------------ */
/* 入力 (INPUT) と DATA/READ                                           */
/* ------------------------------------------------------------------ */

void    nb_input_begin(void);         /* "? " を表示して 1 行読み込む  */
int64_t nb_input_i64(void);           /* 行内の次のカンマ区切り値      */
double  nb_input_f64(void);
nb_str *nb_input_str(void);

void    nb_restore(int64_t index);    /* DATA 読み取り位置の変更       */
int64_t nb_read_i64(void);
double  nb_read_f64(void);
nb_str *nb_read_str(void);

/* ------------------------------------------------------------------ */
/* 数値演算 (ゼロ除算などの検査付き)                                   */
/* ------------------------------------------------------------------ */

int64_t nb_idiv(int64_t a, int64_t b);   /* \  : ゼロ方向切り捨て商    */
int64_t nb_imod(int64_t a, int64_t b);   /* MOD: 符号は被除数に従う    */
double  nb_pow(double a, double b);      /* ^                          */
double  nb_sqr(double x);                /* 負数は実行時エラー         */
double  nb_sin(double x);
double  nb_cos(double x);
double  nb_tan(double x);
double  nb_atn(double x);
double  nb_log(double x);                /* 非正数は実行時エラー       */
double  nb_exp(double x);
int64_t nb_abs_i64(int64_t v);
double  nb_abs_f64(double v);
int64_t nb_sgn_i64(int64_t v);
int64_t nb_sgn_f64(double v);
int64_t nb_int_floor(double x);          /* INT: 負の無限大方向        */
int64_t nb_fix(double x);                /* FIX: ゼロ方向              */

double  nb_rnd(void);                    /* [0,1) の一様乱数           */
void    nb_randomize(double seed);
void    nb_randomize_timer(void);
double  nb_timer(void);                  /* 深夜 0 時からの経過秒      */

/* ------------------------------------------------------------------ */
/* 文字列操作                                                          */
/* ------------------------------------------------------------------ */

nb_str *nb_concat(nb_str *a, nb_str *b);
int64_t nb_str_cmp(nb_str *a, nb_str *b);   /* <0 / 0 / >0 (バイト順) */
int64_t nb_len(nb_str *s);
int64_t nb_asc(nb_str *s);                  /* 空文字列はエラー        */
nb_str *nb_chr(int64_t code);               /* 0..255 以外はエラー     */
double  nb_val(nb_str *s);
nb_str *nb_str_from_i64(int64_t v);         /* STR$: 正数は先頭空白    */
nb_str *nb_str_from_f64(double v);
nb_str *nb_tostr_i64(int64_t v);            /* & 用: 先頭空白なし      */
nb_str *nb_tostr_f64(double v);
nb_str *nb_left(nb_str *s, int64_t n);
nb_str *nb_right(nb_str *s, int64_t n);
nb_str *nb_mid(nb_str *s, int64_t start, int64_t len);  /* len<0 は末尾まで */
int64_t nb_instr(int64_t start, nb_str *hay, nb_str *needle);
nb_str *nb_ucase(nb_str *s);
nb_str *nb_lcase(nb_str *s);
nb_str *nb_space(int64_t n);

/* ------------------------------------------------------------------ */
/* 配列 (ハンドル方式。docs/ARCHITECTURE.md §4.4)                      */
/* ------------------------------------------------------------------ */

/* 要素種別コード: 0 = INTEGER, 1 = DOUBLE, 2 = STRING
 * (irgen.py の _ARR_KIND と一致させること)                             */
int64_t nb_arr_new1(int64_t kind, int64_t upper);
int64_t nb_arr_new2(int64_t kind, int64_t upper1, int64_t upper2);

/* 添字はすべて 0 起点・宣言時の上限を含む (DIM A(10) は A(0)..A(10))。
 * 範囲外アクセスと未確保ハンドルは実行時エラーになる。 */
int64_t nb_arr_get1_i64(int64_t h, int64_t i);
double  nb_arr_get1_f64(int64_t h, int64_t i);
nb_str *nb_arr_get1_str(int64_t h, int64_t i);
void    nb_arr_set1_i64(int64_t h, int64_t i, int64_t v);
void    nb_arr_set1_f64(int64_t h, int64_t i, double v);
void    nb_arr_set1_str(int64_t h, int64_t i, nb_str *v);

int64_t nb_arr_get2_i64(int64_t h, int64_t i, int64_t j);
double  nb_arr_get2_f64(int64_t h, int64_t i, int64_t j);
nb_str *nb_arr_get2_str(int64_t h, int64_t i, int64_t j);
void    nb_arr_set2_i64(int64_t h, int64_t i, int64_t j, int64_t v);
void    nb_arr_set2_f64(int64_t h, int64_t i, int64_t j, double v);
void    nb_arr_set2_str(int64_t h, int64_t i, int64_t j, nb_str *v);

#endif /* NBRT_H */
