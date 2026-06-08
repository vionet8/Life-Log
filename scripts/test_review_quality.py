"""
品質コントロール検証スクリプト。
架空ユーザー（36歳・会社員・2児の父）の1ヶ月分データで
  ① 決定論エンジンが正しい数値を出すか
  ② 実際の振り返りレポートが「肩透かし」にならないか
を確認する。

実行: python -m scripts.test_review_quality
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import review_stats
from backend.services import claude_service


# ── 架空データ（36歳・会社員・2児の父・2026年5月）──
# location: 🏠 自宅 / 🏢 職場 / ☕ カフェ / 🚃 移動中
# weather:  ☀️ 晴れ / ☁️ 曇り / ☔ 雨 / 🌀 低気圧
# score: 20〜100（夜間つぶやきのみ）
def _e(date, body, loc=None, wea=None, score=None, etype="murmur"):
    return {
        "id": 0, "user_id": "test",
        "created_at": f"2026-05-{date} 21:30:00",
        "body": body, "location": loc, "weather": wea,
        "score": score, "score_reason": None, "entry_type": etype,
    }


ENTRIES = [
    # 第1週
    _e("01", "朝の電車でAIの勉強できた。少しだけ前進した感じ", "🚃 移動中", "☀️ 晴れ", 70),
    _e("02", "今日も会議ばかりで自分の時間がなかった", "🏢 職場", "☁️ 曇り", 45),
    _e("03", "娘と公園に行った。久しぶりにゆっくりできた", "🏠 自宅", "☀️ 晴れ", 85),
    _e("04", "副業の準備、全然進まない。時間が足りない", "🏠 自宅", "☔ 雨", 40),
    # 第2週
    _e("06", "週明け。なんとなく気が重い", "🏠 自宅", "☔ 雨", 38),
    _e("07", "会議の合間にAIの記事を読んだ。こういうの楽しい", "🏢 職場", "☀️ 晴れ", 68),
    _e("08", "また会議か。今日は一日中ミーティングだった", "🏢 職場", "🌀 低気圧", 35),
    _e("09", "息子の寝かしつけ担当。絵本読んだら寝た", "🏠 自宅", "☁️ 曇り", 72),
    _e("10", "カフェで副業の構想を練った。少し進んだ", "☕ カフェ", "☀️ 晴れ", 75),
    _e("11", "娘の自転車の練習を見れなかった。ごめんって気持ち", "🏠 自宅", "☔ 雨", 42),
    # 第3週
    _e("13", "在宅勤務。雨だとどうも気分が乗らない", "🏠 自宅", "☔ 雨", 33),
    _e("14", "会議、会議、会議。コントロールできてる感じがしない", "🏢 職場", "☁️ 曇り", 40),
    _e("15", "通勤中にAI学習。30分だけど積み重ねたい", "🚃 移動中", "☀️ 晴れ", 66),
    _e("16", "家族で外食。子どもたちが楽しそうで良かった", "🏠 自宅", "☀️ 晴れ", 88),
    _e("17", "副業に1週間触れてない。焦りだけある", "🏠 自宅", "☁️ 曇り", 48),
    # 第4週
    _e("20", "水曜は本当に消耗する。定例が重なる日", "🏢 職場", "☔ 雨", 36),
    _e("21", "朝活でAIのコード書いた。やっぱり成長してる時が一番いい", "☕ カフェ", "☀️ 晴れ", 78),
    _e("22", "娘とお風呂入りながらいろいろ話した", "🏠 自宅", "☁️ 曇り", 80),
    _e("23", "在宅で雨。なんか一日中だるかった", "🏠 自宅", "☔ 雨", 34),
    _e("24", "副業の初案件、少し進んだ。手応えあった", "☕ カフェ", "☀️ 晴れ", 82),
    _e("27", "また水曜。会議で持っていかれた", "🏢 職場", "🌀 低気圧", 38),
    _e("28", "通勤中の勉強が習慣になってきた", "🚃 移動中", "☁️ 曇り", 64),
    # 相談サマリー（entry_type=consult）
    _e("05", "[相談] テーマ：転職すべきか / 内容：今の会社に不満はないが成長実感がない。でも何がしたいかは不明確 / 着地：転職そのものより「成長の実感」が欲しいと気づいた", etype="consult"),
    _e("12", "[相談] テーマ：副業を始めるか / 内容：時間がない中で副業に踏み出すか迷い。家族との時間とのバランスが不安 / 着地：朝の30分から小さく始めてみることにした", etype="consult"),
    _e("19", "[相談] テーマ：AIを学びたい / 内容：何から手をつければいいか分からず焦る。完璧主義が足を引っ張っている / 着地：毎日5分でも触れることを優先すると決めた", etype="consult"),
]


async def main():
    print("=" * 70)
    print("① 決定論エンジンが算出した『確定した数値』")
    print("=" * 70)
    stats = review_stats.compute_stats(ENTRIES)
    print(review_stats.stats_to_facts_block(stats))
    print(f"\n[データ深度判定] depth = {stats['depth']}")

    print("\n" + "=" * 70)
    print("①.5 思考フェーズ（FPRL）分類の検証")
    print("=" * 70)
    targets = [e for e in ENTRIES if e.get("entry_type", "murmur") == "murmur"] + \
              [e for e in ENTRIES if e.get("entry_type") == "consult"]
    phases = await claude_service.classify_entries_fprl(targets)
    for e, p in zip(targets, phases):
        label = review_stats.PHASE_LABELS.get(p, "—")
        print(f"  [{p}/{label}] {e['body'][:40]}")
    phase_stats = review_stats.aggregate_phases(phases)
    print("\n" + review_stats.phases_to_facts(phase_stats))

    print("\n" + "=" * 70)
    print("② 実際に生成された振り返りレポート（ミライ）")
    print("=" * 70)
    report = await claude_service.generate_review("2026年5月", ENTRIES, persona="mirai")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
