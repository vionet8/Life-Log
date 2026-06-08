"""
振り返りレポート用の決定論的統計エンジン。

設計思想（品質コントロール）:
  レポートに出る「数値」は全てここでPythonが算出する。
  Claude には算出済みの事実だけを渡し、「解釈」のみ任せる。
  → 数字のハルシネーション（83%等を文章から目測する）を構造的に防ぐ。
  → データが足りないセルは出さない。「ある数字だけ」を語らせる。
"""
from collections import Counter, defaultdict
from datetime import datetime

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

# しきい値: この件数以上のサンプルがあるセルだけを「傾向」として扱う
MIN_CELL_SAMPLES = 2      # 場所×天気マトリクスの1セル
MIN_WEEKDAY_SAMPLES = 2   # 曜日別スコア
MIN_SCORED_FOR_TREND = 6  # スコア傾向を語るのに必要な総スコア数

# 話題分類のキーワード辞書（つぶやき本文を素朴にマッチ）
TOPIC_KEYWORDS = {
    "仕事": [
        "仕事", "会議", "ミーティング", "上司", "部下", "職場", "残業", "プロジェクト",
        "案件", "業務", "出社", "在宅", "リモート", "タスク", "締切", "納期", "資料",
        "クライアント", "客先", "営業", "売上",
    ],
    "家族": [
        "娘", "息子", "子供", "子ども", "妻", "夫", "嫁", "旦那", "家族", "親",
        "実家", "育児", "保育園", "幼稚園", "学校", "パパ", "ママ", "お風呂", "寝かしつけ",
    ],
    "自己成長": [
        "副業", "勉強", "学習", "AI", "スキル", "成長", "資格", "読書", "インプット",
        "アウトプット", "将来", "夢", "やりたい", "挑戦", "目標",
    ],
    "健康": [
        "睡眠", "寝", "疲れ", "しんどい", "だるい", "運動", "ジム", "走", "体調",
        "頭痛", "肩こり", "ストレス", "休",
    ],
    "人間関係": [
        "友達", "友人", "同僚", "飲み", "誘", "連絡", "ケンカ", "喧嘩", "仲",
    ],
}

# 注目ワード（頻度を出すと刺さるキーワード群）
WATCH_WORDS = {
    "AI・学習": ["AI", "人工知能", "機械学習", "勉強", "学習"],
    "副業": ["副業", "サイドビジネス"],
    "成長したい": ["成長", "スキルアップ", "伸ばし", "上達"],
    "疲れ": ["疲れ", "しんどい", "だるい", "へとへと", "限界"],
    "転職": ["転職", "辞めたい", "辞めよう"],
    "時間がない": ["時間がない", "時間が足りない", "余裕がない", "間に合わ"],
    "家族との時間": ["娘", "息子", "子供", "子ども", "家族で"],
}

# 仕事への直接的なネガティブ表現（「仕事が嫌だ」系）
WORK_HATE_WORDS = ["仕事が嫌", "仕事嫌い", "会社辞めたい", "働きたくない", "仕事したくない"]

# 高スコアのしきい値（20〜100スケール）
HIGH_SCORE = 70


def _parse_dt(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None


def _classify_topics(body: str) -> list[str]:
    """1つのつぶやきが該当する話題を返す（複数可）。"""
    hits = []
    for topic, kws in TOPIC_KEYWORDS.items():
        if any(kw in body for kw in kws):
            hits.append(topic)
    return hits


def compute_stats(entries: list[dict]) -> dict:
    """
    エントリー群から、レポートに使える「確定した数値」だけを算出する。
    足りないものは None / 空 を返す（捏造しない）。
    """
    murmurs = [e for e in entries if e.get("entry_type", "murmur") == "murmur"]
    consults = [e for e in entries if e.get("entry_type") == "consult"]

    # ── 記録日数・期間 ──
    days = set()
    for e in murmurs:
        dt = _parse_dt(e.get("created_at", ""))
        if dt:
            days.add(dt.date())
    record_days = len(days)
    day_span = (max(days) - min(days)).days + 1 if days else 0

    # ── スコア統計 ──
    scored = [e for e in murmurs if e.get("score") is not None]
    avg_score = round(sum(e["score"] for e in scored) / len(scored), 1) if scored else None

    # 曜日別平均（サンプル2件以上の曜日のみ）
    wd = defaultdict(list)
    for e in scored:
        dt = _parse_dt(e.get("created_at", ""))
        if dt:
            wd[dt.weekday()].append(e["score"])
    weekday_scores = {
        WEEKDAY_JP[k]: {"avg": round(sum(v) / len(v), 1), "n": len(v)}
        for k, v in sorted(wd.items())
        if len(v) >= MIN_WEEKDAY_SAMPLES
    }
    # 最高/最低の曜日（語れるだけのデータがある場合のみ）
    worst_weekday = best_weekday = None
    if len(weekday_scores) >= 2:
        worst_weekday = min(weekday_scores.items(), key=lambda kv: kv[1]["avg"])
        best_weekday = max(weekday_scores.items(), key=lambda kv: kv[1]["avg"])

    # ── 場所×天気マトリクス（サンプル2件以上のセルのみ）──
    cell = defaultdict(list)
    for e in scored:
        loc = (e.get("location") or "").strip()
        wea = (e.get("weather") or "").strip()
        if loc and wea:
            cell[(loc, wea)].append(e["score"])
    loc_weather = {}
    for (loc, wea), vals in cell.items():
        if len(vals) >= MIN_CELL_SAMPLES:
            loc_weather[f"{loc}×{wea}"] = {
                "avg": round(sum(vals) / len(vals), 1),
                "n": len(vals),
            }
    worst_cell = best_cell = None
    if len(loc_weather) >= 2:
        worst_cell = min(loc_weather.items(), key=lambda kv: kv[1]["avg"])
        best_cell = max(loc_weather.items(), key=lambda kv: kv[1]["avg"])

    # ── 話題分布 ──
    topic_counts = Counter()
    for e in murmurs:
        for t in _classify_topics(e.get("body", "")):
            topic_counts[t] += 1
    total_topic = sum(topic_counts.values())
    topic_dist = {}
    if total_topic:
        for t, c in topic_counts.most_common():
            topic_dist[t] = {"count": c, "pct": round(c / total_topic * 100)}

    # ── 高スコアの日に共通する話題（「満たされる条件」）──
    high_topic_counts = Counter()
    high_days_scored = [e for e in scored if e["score"] >= HIGH_SCORE]
    for e in high_days_scored:
        for t in _classify_topics(e.get("body", "")):
            high_topic_counts[t] += 1
    high_total = sum(high_topic_counts.values())
    high_topic_dist = {}
    if high_total:
        for t, c in high_topic_counts.most_common():
            high_topic_dist[t] = {"count": c, "pct": round(c / high_total * 100)}

    # ── 注目ワードの出現件数 ──
    keyword_hits = Counter()
    for e in murmurs:
        body = e.get("body", "")
        for label, kws in WATCH_WORDS.items():
            if any(kw in body for kw in kws):
                keyword_hits[label] += 1

    # 「仕事が嫌だ」系の直接表現が何回あったか
    work_hate_count = 0
    for e in murmurs:
        body = e.get("body", "")
        if any(w in body for w in WORK_HATE_WORDS):
            work_hate_count += 1

    # ── データ深度（レポートの段階を決める）──
    if record_days >= 14 and len(scored) >= 10:
        depth = "rich"
    elif record_days >= 5 and len(murmurs) >= 8:
        depth = "medium"
    else:
        depth = "thin"

    # ── 話題「あり/なし」の日のスコア差（相関係数の代わりの堅実版）──
    # 「ストレス源は仕事と思っているが、実際にスコアが下がるのは家族の話が無い日」
    # のような自己認識とのズレを、相関係数を使わず平均差で示す。
    topic_score_gap = {}
    for topic in TOPIC_KEYWORDS:
        with_topic = [e["score"] for e in scored if topic in _classify_topics(e.get("body", ""))]
        without_topic = [e["score"] for e in scored if topic not in _classify_topics(e.get("body", ""))]
        if len(with_topic) >= 2 and len(without_topic) >= 2:
            avg_with = round(sum(with_topic) / len(with_topic), 1)
            avg_without = round(sum(without_topic) / len(without_topic), 1)
            topic_score_gap[topic] = {
                "with": avg_with,
                "without": avg_without,
                "gap": round(avg_with - avg_without, 1),
                "n_with": len(with_topic),
            }
    # 最も「あると上がる」話題
    biggest_lift = None
    if topic_score_gap:
        biggest_lift = max(topic_score_gap.items(), key=lambda kv: kv[1]["gap"])

    return {
        "murmur_count": len(murmurs),
        "consult_count": len(consults),
        "record_days": record_days,
        "day_span": day_span,
        "scored_count": len(scored),
        "avg_score": avg_score,
        "weekday_scores": weekday_scores,
        "worst_weekday": worst_weekday,
        "best_weekday": best_weekday,
        "loc_weather": loc_weather,
        "worst_cell": worst_cell,
        "best_cell": best_cell,
        "topic_dist": topic_dist,
        "high_topic_dist": high_topic_dist,
        "high_days_count": len(high_days_scored),
        "keyword_hits": dict(keyword_hits.most_common()),
        "work_hate_count": work_hate_count,
        "topic_score_gap": topic_score_gap,
        "biggest_lift": biggest_lift,
        "depth": depth,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 思考フェーズ（FPRL）分析
#   P=問題発見 / R=解決案 / L=学習 / F=実行
#   ※ 分類は LLM（claude_service.classify_entries_fprl）が行い、
#     ここでは「分類済みラベルの集計」だけを決定論的に行う。
# ══════════════════════════════════════════════════════════════════════════════

PHASE_LABELS = {
    "P": "問題発見",
    "R": "解決案",
    "L": "学習",
    "F": "実行",
}


def aggregate_phases(phases: list[str]) -> dict:
    """
    LLMが付与したフェーズラベル列（'P'/'R'/'L'/'F'/'-'）を集計する。
    '-' は該当なし（無理に分類しない）。
    """
    counts = Counter(p for p in phases if p in PHASE_LABELS)
    total = sum(counts.values())
    dist = {}
    if total:
        for p in ["P", "R", "L", "F"]:
            c = counts.get(p, 0)
            dist[p] = {
                "label": PHASE_LABELS[p],
                "count": c,
                "pct": round(c / total * 100),
            }

    # 構造的な発見フラグ
    finding = None
    if total >= 8:
        f_pct = dist["F"]["pct"]
        p_pct = dist["P"]["pct"]
        r_pct = dist["R"]["pct"]
        l_pct = dist["L"]["pct"]
        # 問題発見+解決案は多いが実行が極端に少ない＝「実行で止まる」
        if (p_pct + r_pct) >= 50 and f_pct <= 15:
            finding = "stuck_before_action"
        # 学習・情報収集は多いが実行が少ない＝「インプット過多・実践不足」
        elif l_pct >= 25 and f_pct <= 15:
            finding = "input_heavy"
        # 問題発見ばかりで解決案・実行に進まない＝「発見で止まる」
        elif p_pct >= 45 and (r_pct + f_pct) <= 25:
            finding = "problem_only"

    return {"dist": dist, "total": total, "finding": finding}


def phases_to_facts(phase_stats: dict) -> str:
    """フェーズ集計を Claude に渡す事実テキストにする。"""
    if not phase_stats or not phase_stats.get("dist"):
        return ""
    dist = phase_stats["dist"]
    parts = "、".join(f"{v['label']} {v['count']}件({v['pct']}%)" for v in dist.values())
    line = f"・思考フェーズ分布（記録{phase_stats['total']}件を分類）: {parts}"
    finding_map = {
        "stuck_before_action": "  └ 構造的傾向: 問題発見・解決案は多いが「実行」が極端に少ない（実行フェーズで止まりやすい）",
        "input_heavy": "  └ 構造的傾向: 学習・情報収集に対して「実行」が少ない（インプット過多・実践不足の可能性）",
        "problem_only": "  └ 構造的傾向: 問題発見が多く、解決案・実行に進みにくい（発見フェーズで止まりやすい）",
    }
    if phase_stats.get("finding"):
        line += "\n" + finding_map[phase_stats["finding"]]
    return line


def stats_to_facts_block(stats: dict) -> str:
    """
    算出済みの統計を、Claudeに渡す「確定した事実」テキストにする。
    ここに無い数字は語らせない。
    """
    lines = []
    lines.append(f"・記録日数: {stats['record_days']}日（期間 {stats['day_span']}日間）")
    lines.append(f"・つぶやき総数: {stats['murmur_count']}件 / 相談: {stats['consult_count']}件")
    lines.append(f"・スコア記録: {stats['scored_count']}件")
    if stats["avg_score"] is not None:
        lines.append(f"・平均スコア: {stats['avg_score']}点（20〜100スケール）")

    if stats["weekday_scores"]:
        wd = "、".join(
            f"{k}曜 {v['avg']}点(n={v['n']})" for k, v in stats["weekday_scores"].items()
        )
        lines.append(f"・曜日別平均スコア: {wd}")
        if stats["worst_weekday"] and stats["best_weekday"]:
            ww = stats["worst_weekday"]
            bw = stats["best_weekday"]
            lines.append(f"  └ 最も低い曜日: {ww[0]}曜({ww[1]['avg']}点) / 最も高い曜日: {bw[0]}曜({bw[1]['avg']}点)")

    if stats["loc_weather"]:
        lw = "、".join(
            f"{k} {v['avg']}点(n={v['n']})" for k, v in stats["loc_weather"].items()
        )
        lines.append(f"・場所×天気の平均スコア（2件以上のみ）: {lw}")
        if stats["worst_cell"] and stats["best_cell"]:
            wc = stats["worst_cell"]
            bc = stats["best_cell"]
            lines.append(f"  └ 最も低い組合せ: {wc[0]}({wc[1]['avg']}点) / 最も高い組合せ: {bc[0]}({bc[1]['avg']}点)")

    if stats["topic_dist"]:
        td = "、".join(f"{t} {v['pct']}%({v['count']}件)" for t, v in stats["topic_dist"].items())
        lines.append(f"・つぶやきの話題分布: {td}")

    if stats["high_topic_dist"]:
        ht = "、".join(f"{t} {v['count']}件" for t, v in stats["high_topic_dist"].items())
        lines.append(f"・高スコア({HIGH_SCORE}点以上)の日({stats['high_days_count']}件)に登場した話題: {ht}")

    if stats["keyword_hits"]:
        kh = "、".join(f"「{k}」{v}件" for k, v in stats["keyword_hits"].items())
        lines.append(f"・注目ワードの出現件数: {kh}")

    lines.append(f"・「仕事が嫌だ」系の直接表現の回数: {stats['work_hate_count']}回")

    # 話題あり/なしのスコア差（自己認識のズレの材料）
    if stats.get("topic_score_gap"):
        for topic, g in stats["topic_score_gap"].items():
            sign = "+" if g["gap"] >= 0 else ""
            lines.append(
                f"・「{topic}」の話題がある日: 平均{g['with']}点 / ない日: 平均{g['without']}点"
                f"（差 {sign}{g['gap']}点・該当{g['n_with']}件）"
            )

    return "\n".join(lines)
