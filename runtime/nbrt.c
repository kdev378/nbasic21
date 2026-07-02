/*
 * nbrt.c — NBASIC-21 ランタイムライブラリ実装
 * ============================================
 *
 * 可搬性のある C99 で書かれており、
 *   - C バックエンドの出力と一緒にホストの cc でビルドする
 *   - x86-64 バックエンドの出力 (NASM) と一緒に mingw-w64 でリンクする
 * の両方で同じソースを使う。OS 依存箇所は nb_timer() のみ。
 *
 * ■ メモリ管理 — ブロックアリーナ
 *   実行中に作られる文字列と配列は、チェーンされたブロックから
 *   バンプアロケートする。個別の解放はせず、プログラム終了時に
 *   チェーンごと解放する。BASIC プログラムは短命でオブジェクトも
 *   小さいため、この方式で十分かつ最速 (解放し忘れ・二重解放が
 *   構造的に起こらない)。トレードオフとして、ループ内で大量の
 *   文字列を作り続けるプログラムはメモリを積み増す (仕様書 §12)。
 *
 * ■ エラー処理
 *   古典 BASIC の伝統に従い、実行時エラーは
 *       ?RUNTIME ERROR: <メッセージ>
 *   を表示して終了コード 1 で終了する。行番号の追跡は行わない。
 */

#include "nbrt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <inttypes.h>

/* ================================================================== */
/* アリーナアロケータ                                                  */
/* ================================================================== */

#define NB_ARENA_BLOCK (64 * 1024)   /* 通常ブロックのサイズ */

typedef struct arena_block {
    struct arena_block *next;
    size_t              used;
    size_t              cap;
    /* この直後に cap バイトのデータ領域が続く */
} arena_block;

static arena_block *arena_head = NULL;

/* size バイトを確保する。8 バイト境界に丸め、通常はブロック内から
 * バンプアロケート、ブロックより大きい要求は専用ブロックを作る。 */
static void *nb_alloc(size_t size)
{
    size = (size + 7u) & ~(size_t)7u;   /* 8 バイト整列 */
    if (arena_head == NULL || arena_head->used + size > arena_head->cap) {
        size_t cap = size > NB_ARENA_BLOCK ? size : NB_ARENA_BLOCK;
        arena_block *b = (arena_block *)malloc(sizeof(arena_block) + cap);
        if (b == NULL) {
            fputs("?RUNTIME ERROR: Out of memory\n", stderr);
            exit(1);
        }
        b->next = arena_head;
        b->used = 0;
        b->cap  = cap;
        arena_head = b;
    }
    {
        char *base = (char *)(arena_head + 1);
        void *p = base + arena_head->used;
        arena_head->used += size;
        return p;
    }
}

static void arena_free_all(void)
{
    arena_block *b = arena_head;
    while (b != NULL) {
        arena_block *next = b->next;
        free(b);
        b = next;
    }
    arena_head = NULL;
}

/* ================================================================== */
/* 実行制御                                                            */
/* ================================================================== */

void nb_fatal(const char *msg)
{
    fflush(stdout);
    fprintf(stderr, "?RUNTIME ERROR: %s\n", msg);
    arena_free_all();
    exit(1);
}

void nb_fatal_bad_return(void)
{
    /* GOSUB ディスパッチャで未知の復帰 ID が出た場合。コンパイラが
     * 正しければ到達しない (irgen.py の _gen_gosub_dispatcher 参照)。 */
    nb_fatal("internal: bad GOSUB return id");
}

void nb_end(void)
{
    fflush(stdout);
    arena_free_all();
    exit(0);
}

/* ---- GOSUB スタック ------------------------------------------------ */
/* 必要に応じて倍々に伸びる素朴な int64 スタック。 */

static int64_t *gosub_stack = NULL;
static size_t   gosub_len = 0, gosub_cap = 0;

void nb_gosub_push(int64_t id)
{
    if (gosub_len == gosub_cap) {
        gosub_cap = gosub_cap ? gosub_cap * 2 : 64;
        gosub_stack = (int64_t *)realloc(gosub_stack,
                                         gosub_cap * sizeof(int64_t));
        if (gosub_stack == NULL)
            nb_fatal("Out of memory");
    }
    gosub_stack[gosub_len++] = id;
}

int64_t nb_gosub_pop(void)
{
    if (gosub_len == 0)
        nb_fatal("RETURN without GOSUB");
    return gosub_stack[--gosub_len];
}

/* ================================================================== */
/* 文字列の生成ヘルパ                                                  */
/* ================================================================== */

static nb_str nb_empty_str = { 0, "" };

/* len バイトの可変バッファ付き nb_str を確保する。
 * 呼び出し側は buf に書き込んでから返すこと (以後イミュータブル)。 */
static nb_str *str_alloc(int64_t len, char **buf)
{
    /* 記述子と本体を 1 回の確保にまとめる。+1 は NUL 終端
     * (strtod などの C 関数に渡すときの安全のため)。 */
    nb_str *s = (nb_str *)nb_alloc(sizeof(nb_str) + (size_t)len + 1);
    char *data = (char *)(s + 1);
    s->len = len;
    s->data = data;
    data[len] = '\0';
    *buf = data;
    return s;
}

static nb_str *str_from_cstr(const char *p, size_t n)
{
    char *buf;
    nb_str *s;
    if (n == 0)
        return &nb_empty_str;
    s = str_alloc((int64_t)n, &buf);
    memcpy(buf, p, n);
    return s;
}

/* ================================================================== */
/* 出力 (PRINT)                                                        */
/* ================================================================== */

/* PRINT のカンマ区切り (14 桁ゾーン) を実装するため、現在の桁位置を
 * 数えながら出力する。改行でゾーンはリセットされる。 */
static int64_t out_col = 0;

static void out_write(const char *p, size_t n)
{
    size_t i;
    fwrite(p, 1, n, stdout);
    for (i = 0; i < n; i++) {
        if (p[i] == '\n')
            out_col = 0;
        else
            out_col++;
    }
}

/* 数値の共通出力: 古典 BASIC の書式 (仕様書 §9.3) に従い、
 * 非負数には符号の位置として先頭に空白を、すべての数値には
 * 区切りとして末尾に空白を付ける。 */
static void print_number(const char *digits, int negative)
{
    if (!negative)
        out_write(" ", 1);
    out_write(digits, strlen(digits));
    out_write(" ", 1);
}

void nb_print_i64(int64_t v)
{
    char buf[32];
    snprintf(buf, sizeof buf, "%" PRId64, v);
    print_number(buf, v < 0);
}

void nb_print_f64(double v)
{
    /* %.15g は double を過不足なく人間向けに丸める書式。
     * 整数値 (3.0 など) は小数点なしの "3" になる — 古典 BASIC と同じ。 */
    char buf[40];
    snprintf(buf, sizeof buf, "%.15g", v);
    /* 負数は buf 自体が '-' で始まるのでそのまま渡す (先頭空白なし) */
    print_number(buf, buf[0] == '-');
}

void nb_print_str(nb_str *s)
{
    out_write(s->data, (size_t)s->len);
}

void nb_print_tab(void)
{
    /* 次の 14 桁ゾーンの先頭へ。既にゾーン境界でも最低 1 桁進む
     * (2 つの項目がくっつかないようにする古典動作)。 */
    int64_t target = (out_col / 14 + 1) * 14;
    while (out_col < target)
        out_write(" ", 1);
}

void nb_print_nl(void)
{
    out_write("\n", 1);
}

/* ================================================================== */
/* 入力 (INPUT)                                                        */
/* ================================================================== */

/* INPUT は 1 行を読み込み、カンマ区切りの値を変数へ順に割り当てる。
 * 行バッファと読み取り位置をランタイムが保持する。 */
static char  in_line[4096];
static char *in_ptr = NULL;

void nb_input_begin(void)
{
    fputs("? ", stdout);
    out_col += 2;
    fflush(stdout);
    if (fgets(in_line, sizeof in_line, stdin) == NULL)
        nb_fatal("Out of input (EOF)");
    /* 入力エコーは端末が行うが、桁位置の追跡上は行が変わったとみなす */
    out_col = 0;
    in_ptr = in_line;
}

/* 行内の次のカンマ区切りトークンを取り出す (前後の空白は除去)。
 * out_len に長さ、戻り値に先頭ポインタ。値が尽きたら長さ 0 を返す。 */
static const char *input_token(size_t *out_len)
{
    char *start, *end;
    if (in_ptr == NULL)
        nb_input_begin();   /* 保険: begin なしで呼ばれた場合 */
    start = in_ptr;
    while (*start == ' ' || *start == '\t')
        start++;
    end = start;
    while (*end != '\0' && *end != ',' && *end != '\n' && *end != '\r')
        end++;
    /* 次回のために読み取り位置を進める (カンマは飛ばす) */
    in_ptr = (*end == ',') ? end + 1 : end;
    /* 末尾の空白を切り詰める */
    while (end > start && (end[-1] == ' ' || end[-1] == '\t'))
        end--;
    *out_len = (size_t)(end - start);
    return start;
}

int64_t nb_input_i64(void)
{
    return llrint(nb_input_f64());
}

double nb_input_f64(void)
{
    size_t n;
    const char *p = input_token(&n);
    char buf[64];
    if (n >= sizeof buf)
        n = sizeof buf - 1;
    memcpy(buf, p, n);
    buf[n] = '\0';
    /* 解析できない入力は 0 になる (仕様書 §9.2)。古典 BASIC の
     * "?Redo from start" 再入力ループはあえて実装しない。 */
    return strtod(buf, NULL);
}

nb_str *nb_input_str(void)
{
    size_t n;
    const char *p = input_token(&n);
    return str_from_cstr(p, n);
}

/* ================================================================== */
/* DATA / READ / RESTORE                                               */
/* ================================================================== */

/* データ項目表 nb_data_items / nb_data_count は生成コード側で定義される
 * (バックエンドとの契約)。ここでは読み取り位置だけを管理する。 */
static int64_t data_pos = 0;

void nb_restore(int64_t index)
{
    data_pos = index;
}

static const char *next_data(void)
{
    if (data_pos >= nb_data_count)
        nb_fatal("Out of DATA");
    return nb_data_items[data_pos++];
}

int64_t nb_read_i64(void)
{
    return llrint(strtod(next_data(), NULL));
}

double nb_read_f64(void)
{
    return strtod(next_data(), NULL);
}

nb_str *nb_read_str(void)
{
    const char *p = next_data();
    return str_from_cstr(p, strlen(p));
}

/* ================================================================== */
/* 数値演算                                                            */
/* ================================================================== */

int64_t nb_idiv(int64_t a, int64_t b)
{
    if (b == 0)
        nb_fatal("Division by zero");
    if (b == -1 && a == INT64_MIN)   /* INT64_MIN / -1 は CPU 例外になる */
        return INT64_MIN;            /* ラップアラウンドとして定義する   */
    return a / b;                    /* C99 の除算はゼロ方向切り捨て     */
}

int64_t nb_imod(int64_t a, int64_t b)
{
    if (b == 0)
        nb_fatal("Division by zero");
    if (b == -1)
        return 0;
    return a % b;                    /* C99 の % は符号が被除数に従う    */
}

double nb_pow(double a, double b)
{
    /* 古典 BASIC の ^ は数学的に定義できない場合エラーにする */
    if (a == 0.0 && b < 0.0)
        nb_fatal("Division by zero");            /* 0 の負ベき */
    if (a < 0.0 && b != floor(b))
        nb_fatal("Illegal function call");       /* 負数の非整数ベき */
    return pow(a, b);
}

double nb_sqr(double x)
{
    if (x < 0.0)
        nb_fatal("Illegal function call");
    return sqrt(x);
}

double nb_log(double x)
{
    if (x <= 0.0)
        nb_fatal("Illegal function call");
    return log(x);
}

double nb_sin(double x) { return sin(x); }
double nb_cos(double x) { return cos(x); }
double nb_tan(double x) { return tan(x); }
double nb_atn(double x) { return atan(x); }
double nb_exp(double x) { return exp(x); }

int64_t nb_abs_i64(int64_t v) { return v < 0 ? -v : v; }
double  nb_abs_f64(double v)  { return fabs(v); }
int64_t nb_sgn_i64(int64_t v) { return v > 0 ? 1 : v < 0 ? -1 : 0; }
int64_t nb_sgn_f64(double v)  { return v > 0.0 ? 1 : v < 0.0 ? -1 : 0; }

int64_t nb_int_floor(double x) { return (int64_t)floor(x); }
int64_t nb_fix(double x)       { return (int64_t)trunc(x); }

/* ---- 乱数 ----------------------------------------------------------- */
/* プラットフォーム非依存の再現性を持たせるため、C ライブラリの rand()
 * ではなく自前の xorshift64* を使う。種を与えなければ固定の初期値から
 * 始まる — 古典 BASIC の「RANDOMIZE しなければ毎回同じ列」と同じ。 */

static uint64_t rng_state = UINT64_C(0x9E3779B97F4A7C15);

static uint64_t rng_next(void)
{
    uint64_t x = rng_state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    rng_state = x;
    return x * UINT64_C(0x2545F4914F6CDD1D);
}

double nb_rnd(void)
{
    /* 上位 53 ビットを使って [0,1) の一様分布を作る */
    return (double)(rng_next() >> 11) * (1.0 / 9007199254740992.0);
}

void nb_randomize(double seed)
{
    /* double のビットパターンを混ぜて種にする。0 は状態として不正なので
     * 避ける。 */
    uint64_t bits;
    memcpy(&bits, &seed, sizeof bits);
    rng_state = bits ^ UINT64_C(0x9E3779B97F4A7C15);
    if (rng_state == 0)
        rng_state = 1;
}

void nb_randomize_timer(void)
{
    nb_randomize((double)time(NULL));
}

double nb_timer(void)
{
    /* 古典 BASIC の TIMER: ローカル時刻での深夜 0 時からの経過秒。
     * 秒未満の分解能は持たない (可搬性優先。仕様書 §10.4)。 */
    time_t t = time(NULL);
    struct tm *lt = localtime(&t);
    return (double)(lt->tm_hour * 3600 + lt->tm_min * 60 + lt->tm_sec);
}

/* ================================================================== */
/* 文字列操作                                                          */
/* ================================================================== */

nb_str *nb_concat(nb_str *a, nb_str *b)
{
    char *buf;
    nb_str *s;
    if (a->len == 0) return b;
    if (b->len == 0) return a;
    s = str_alloc(a->len + b->len, &buf);
    memcpy(buf, a->data, (size_t)a->len);
    memcpy(buf + a->len, b->data, (size_t)b->len);
    return s;
}

int64_t nb_str_cmp(nb_str *a, nb_str *b)
{
    /* バイト列の辞書式比較。共通部分が等しければ短い方が小さい。 */
    int64_t min = a->len < b->len ? a->len : b->len;
    int c = memcmp(a->data, b->data, (size_t)min);
    if (c != 0)
        return c < 0 ? -1 : 1;
    return a->len < b->len ? -1 : a->len > b->len ? 1 : 0;
}

int64_t nb_len(nb_str *s) { return s->len; }

int64_t nb_asc(nb_str *s)
{
    if (s->len == 0)
        nb_fatal("Illegal function call");   /* ASC("") は古典でもエラー */
    return (unsigned char)s->data[0];
}

nb_str *nb_chr(int64_t code)
{
    char *buf;
    nb_str *s;
    if (code < 0 || code > 255)
        nb_fatal("Illegal function call");
    s = str_alloc(1, &buf);
    buf[0] = (char)code;
    return s;
}

double nb_val(nb_str *s)
{
    /* strtod は先頭の空白を読み飛ばし、数値として解釈できる最長の
     * 前置部分を変換する。解釈できなければ 0 — VAL の古典動作と同じ。
     * str_alloc 由来の文字列は NUL 終端済みだが、リテラルは data が
     * 静的配列を直接指すため、安全のため一度コピーする。 */
    char buf[64];
    size_t n = (size_t)(s->len < 63 ? s->len : 63);
    memcpy(buf, s->data, n);
    buf[n] = '\0';
    return strtod(buf, NULL);
}

nb_str *nb_str_from_i64(int64_t v)
{
    /* STR$ の古典動作: 非負数には符号位置として先頭に空白 1 個。 */
    char buf[34];
    snprintf(buf, sizeof buf, v < 0 ? "%" PRId64 : " %" PRId64, v);
    return str_from_cstr(buf, strlen(buf));
}

nb_str *nb_str_from_f64(double v)
{
    char buf[42];
    if (v < 0.0)
        snprintf(buf, sizeof buf, "%.15g", v);
    else
        snprintf(buf, sizeof buf, " %.15g", v);
    return str_from_cstr(buf, strlen(buf));
}

nb_str *nb_tostr_i64(int64_t v)
{
    /* & 演算子用: 先頭空白なしのコンパクトな表記 (仕様書 §5.2) */
    char buf[32];
    snprintf(buf, sizeof buf, "%" PRId64, v);
    return str_from_cstr(buf, strlen(buf));
}

nb_str *nb_tostr_f64(double v)
{
    char buf[40];
    snprintf(buf, sizeof buf, "%.15g", v);
    return str_from_cstr(buf, strlen(buf));
}

nb_str *nb_left(nb_str *s, int64_t n)
{
    if (n < 0)
        nb_fatal("Illegal function call");
    if (n >= s->len)
        return s;                      /* 全体 — 共有してよい (不変) */
    return str_from_cstr(s->data, (size_t)n);
}

nb_str *nb_right(nb_str *s, int64_t n)
{
    if (n < 0)
        nb_fatal("Illegal function call");
    if (n >= s->len)
        return s;
    return str_from_cstr(s->data + (s->len - n), (size_t)n);
}

nb_str *nb_mid(nb_str *s, int64_t start, int64_t len)
{
    /* MID$(s, start [, len]) — start は 1 起点 (仕様書 §10.3)。
     * len < 0 は「末尾まで」の内部規約 (irgen.py 参照)。 */
    int64_t avail;
    if (start < 1)
        nb_fatal("Illegal function call");
    if (start > s->len)
        return &nb_empty_str;
    avail = s->len - (start - 1);
    if (len < 0 || len > avail)
        len = avail;
    return str_from_cstr(s->data + (start - 1), (size_t)len);
}

int64_t nb_instr(int64_t start, nb_str *hay, nb_str *needle)
{
    /* INSTR([start,] hay$, needle$) — 見つかった位置 (1 起点) か 0。
     * 空の検索文字列は start を返す (QBasic 互換)。 */
    int64_t i;
    if (start < 1)
        nb_fatal("Illegal function call");
    if (start > hay->len)
        return 0;
    if (needle->len == 0)
        return start;
    for (i = start - 1; i + needle->len <= hay->len; i++) {
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0)
            return i + 1;
    }
    return 0;
}

static nb_str *map_case(nb_str *s, int upper)
{
    char *buf;
    nb_str *r;
    int64_t i;
    if (s->len == 0)
        return s;
    r = str_alloc(s->len, &buf);
    for (i = 0; i < s->len; i++) {
        char c = s->data[i];
        if (upper)
            buf[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
        else
            buf[i] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c;
    }
    return r;
}

nb_str *nb_ucase(nb_str *s) { return map_case(s, 1); }
nb_str *nb_lcase(nb_str *s) { return map_case(s, 0); }

nb_str *nb_space(int64_t n)
{
    char *buf;
    nb_str *s;
    if (n < 0)
        nb_fatal("Illegal function call");
    if (n == 0)
        return &nb_empty_str;
    s = str_alloc(n, &buf);
    memset(buf, ' ', (size_t)n);
    return s;
}

/* ================================================================== */
/* 配列                                                                */
/* ================================================================== */

/* 配列はハンドル (1 起点の整数 ID) で参照される。ハンドル 0 は
 * 「未確保」を表し、DIM 前のアクセスを確実に検出できる。
 * 要素はすべて 8 バイト (int64_t / double / nb_str*) なので、
 * 記憶域は共用体的に void* 1 本で持ち、種別コードで解釈を変える。 */

typedef struct nb_array {
    int64_t d1;        /* 第 1 次元の上限 (要素数は d1+1)          */
    int64_t d2;        /* 第 2 次元の上限。1 次元配列では -1       */
    int64_t kind;      /* 0=INTEGER, 1=DOUBLE, 2=STRING            */
    void   *data;
} nb_array;

static nb_array **arr_table = NULL;
static size_t     arr_len = 0, arr_cap = 0;

static int64_t arr_register(nb_array *a)
{
    if (arr_len == arr_cap) {
        arr_cap = arr_cap ? arr_cap * 2 : 16;
        arr_table = (nb_array **)realloc(arr_table,
                                         arr_cap * sizeof(nb_array *));
        if (arr_table == NULL)
            nb_fatal("Out of memory");
    }
    arr_table[arr_len++] = a;
    return (int64_t)arr_len;           /* ID はテーブル添字 + 1 */
}

static nb_array *arr_lookup(int64_t h)
{
    if (h < 1 || (size_t)h > arr_len)
        nb_fatal("Array used before DIM");
    return arr_table[h - 1];
}

static nb_array *arr_new(int64_t kind, int64_t d1, int64_t d2)
{
    nb_array *a;
    int64_t count, i;
    if (d1 < 0 || (d2 != -1 && d2 < 0))
        nb_fatal("Subscript out of range");
    count = (d1 + 1) * (d2 == -1 ? 1 : d2 + 1);
    a = (nb_array *)nb_alloc(sizeof(nb_array));
    a->d1 = d1;
    a->d2 = d2;
    a->kind = kind;
    a->data = nb_alloc((size_t)count * 8);
    /* ゼロ初期化: 数値は 0、文字列は空文字列 (仕様書 §3.6) */
    if (kind == 2) {
        nb_str **p = (nb_str **)a->data;
        for (i = 0; i < count; i++)
            p[i] = &nb_empty_str;
    } else {
        memset(a->data, 0, (size_t)count * 8);
    }
    return a;
}

int64_t nb_arr_new1(int64_t kind, int64_t upper)
{
    return arr_register(arr_new(kind, upper, -1));
}

int64_t nb_arr_new2(int64_t kind, int64_t upper1, int64_t upper2)
{
    return arr_register(arr_new(kind, upper1, upper2));
}

/* 添字検査をして線形添字を返す共通ヘルパ。
 * want2 は「2 次元アクセスかどうか」— 次元数の不一致はコンパイル時に
 * 弾かれるが、防御的にここでも検査する。 */
static int64_t arr_index(nb_array *a, int64_t i, int64_t j, int want2)
{
    if ((a->d2 != -1) != want2)
        nb_fatal("internal: array dimension mismatch");
    if (i < 0 || i > a->d1)
        nb_fatal("Subscript out of range");
    if (!want2)
        return i;
    if (j < 0 || j > a->d2)
        nb_fatal("Subscript out of range");
    return i * (a->d2 + 1) + j;        /* 行優先 (row-major) 配置 */
}

/* 12 個のアクセサはどれも「表引き → 添字検査 → 8 バイト読み書き」 */

int64_t nb_arr_get1_i64(int64_t h, int64_t i)
{ nb_array *a = arr_lookup(h); return ((int64_t *)a->data)[arr_index(a, i, 0, 0)]; }

double nb_arr_get1_f64(int64_t h, int64_t i)
{ nb_array *a = arr_lookup(h); return ((double *)a->data)[arr_index(a, i, 0, 0)]; }

nb_str *nb_arr_get1_str(int64_t h, int64_t i)
{ nb_array *a = arr_lookup(h); return ((nb_str **)a->data)[arr_index(a, i, 0, 0)]; }

void nb_arr_set1_i64(int64_t h, int64_t i, int64_t v)
{ nb_array *a = arr_lookup(h); ((int64_t *)a->data)[arr_index(a, i, 0, 0)] = v; }

void nb_arr_set1_f64(int64_t h, int64_t i, double v)
{ nb_array *a = arr_lookup(h); ((double *)a->data)[arr_index(a, i, 0, 0)] = v; }

void nb_arr_set1_str(int64_t h, int64_t i, nb_str *v)
{ nb_array *a = arr_lookup(h); ((nb_str **)a->data)[arr_index(a, i, 0, 0)] = v; }

int64_t nb_arr_get2_i64(int64_t h, int64_t i, int64_t j)
{ nb_array *a = arr_lookup(h); return ((int64_t *)a->data)[arr_index(a, i, j, 1)]; }

double nb_arr_get2_f64(int64_t h, int64_t i, int64_t j)
{ nb_array *a = arr_lookup(h); return ((double *)a->data)[arr_index(a, i, j, 1)]; }

nb_str *nb_arr_get2_str(int64_t h, int64_t i, int64_t j)
{ nb_array *a = arr_lookup(h); return ((nb_str **)a->data)[arr_index(a, i, j, 1)]; }

void nb_arr_set2_i64(int64_t h, int64_t i, int64_t j, int64_t v)
{ nb_array *a = arr_lookup(h); ((int64_t *)a->data)[arr_index(a, i, j, 1)] = v; }

void nb_arr_set2_f64(int64_t h, int64_t i, int64_t j, double v)
{ nb_array *a = arr_lookup(h); ((double *)a->data)[arr_index(a, i, j, 1)] = v; }

void nb_arr_set2_str(int64_t h, int64_t i, int64_t j, nb_str *v)
{ nb_array *a = arr_lookup(h); ((nb_str **)a->data)[arr_index(a, i, j, 1)] = v; }

/* ================================================================== */
/* エントリポイント                                                    */
/* ================================================================== */

int main(void)
{
    /* 生成コードのメイン関数を呼ぶだけ。END 文は nb_end() 経由で
     * ここへ戻らず exit するが、メイン末尾まで実行が到達した場合は
     * ここで後始末する。 */
    nb_basic_main();
    fflush(stdout);
    arena_free_all();
    free(gosub_stack);
    free(arr_table);
    return 0;
}
