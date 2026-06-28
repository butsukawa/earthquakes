import os
import requests
import json
from datetime import datetime, timedelta, timezone

# Discord Webhook URL (GitHub ActionsのSecretsから読み込む)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATUS_FILE = "last_earthquake.txt"

# 気象庁の地震情報JSON (最新の地震リスト)
JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

def get_earthquake_list():
    try:
        response = requests.get(JMA_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"データの取得に失敗しました: {e}")
    return []

def get_embed_color(max_int):
    """
    震度に応じたDiscord Embedの10進数カラーコードを返す
    """
    color_map = {
        "1": 16777215,  # 白色 (#FFFFFF)
        "2": 5294297,   # 水色 (#50C8EF)
        "3": 3381621,   # 青緑色 (#339975)
        "4": 3066993,   # 緑色 (#2ECC71)
        "5-": 16766720, # 黄色 (#F1C40F)
        "5+": 15105570, # オレンジ色 (#E67E22)
        "6-": 16538562, # ピンク色 (#FC5C82)
        "6+": 15158332, # 赤色 (#E74C3C)
        "7": 10181046,  # 紫色 (#9B59B6)
    }
    return color_map.get(max_int, 9807270)

def main():
    if not WEBHOOK_URL:
        print("エラー: DISCORD_WEBHOOK_URL が設定されていません。")
        return

    quakes = get_earthquake_list()
    if not quakes:
        print("地震データが空、または取得できませんでした。")
        return

    # 過去の最新ID（前回通知済みの一番新しい地震）を読み込み
    last_id = ""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            last_id = f.read().strip()

    # 現在時刻から24時間前の基準時刻を計算 (JSTベース)
    # 気象庁の at は ISO8601形式 (例: 2026-06-28T09:12:00+09:00)
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    one_day_ago = now_jst - timedelta(days=1)

    # 通知対象の地震をフィルタリングする
    targets = []
    new_latest_id = None

    for i, quake in enumerate(quakes):
        quake_id = quake.get("eid", quake.get("at", ""))
        
        # 配列の先頭（インデックス0）が気象庁データの一番最新のID
        if i == 0:
            new_latest_id = quake_id

        # 前回通知したIDに到達したら、それより古い（過去の）データは処理しない
        if last_id and quake_id == last_id:
            break

        # 震度情報がないデータ（「顕著な地震要素更新」など）はスキップ
        max_int = quake.get("maxi", "").strip()
        if max_int == "" or max_int == "-":
            continue

        # 時刻のチェック（過去24時間以内か）
        at_str = quake.get("at", "")
        try:
            # ISO形式からdatetimeオブジェクトに変換
            dt = datetime.fromisoformat(at_str)
            if dt < one_day_ago:
                # 24時間より古いデータに達したらループ終了（JMAデータは新しい順に並んでいるため）
                break
        except Exception as e:
            print(f"時刻パースエラー: {e}")
            continue

        # 条件をクリアした地震を通知候補に追加
        targets.append((quake_id, quake, dt, max_int))

    if not targets:
        print("通知対象の新しい地震（過去24時間以内）はありません。")
        # ログファイルが空だった場合などのために最新IDだけ保存して終了
        if new_latest_id and new_latest_id != last_id:
            with open(STATUS_FILE, "w") as f:
                f.write(new_latest_id)
        return

    # 気象庁データは「新しい順」に入っているので、過去を遡る時は「古い順」に並び替えて通知する
    targets.reverse()

    print(f"{len(targets)} 件の地震情報をDiscordに送信します。")

    for quake_id, quake, dt, max_int in targets:
        time_str = dt.strftime("%Y/%m/%d %H:%M")
        place = quake.get("anm", "調査中")
        mag = quake.get("mag", "不明")
        
        int_display_map = {"5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強"}
        max_int_display = int_display_map.get(max_int, max_int)
        embed_color = get_embed_color(max_int)

        payload = {
            "embeds": [
                {
                    "title": f"🚨 地震情報（{quake.get('ttl', '震源・震度情報')}）",
                    "color": embed_color,
                    "fields": [
                        {"name": "発生時刻", "value": time_str, "inline": True},
                        {"name": "震源地", "value": place, "inline": True},
                        {"name": "最大震度", "value": f"**震度 {max_int_display}**", "inline": False},
                        {"name": "規模 (M)", "value": f"M{mag}", "inline": True},
                    ],
                    "footer": {"text": "情報元: 気象庁ホームページ"},
                    "url": "https://www.data.jma.go.jp/multi/quake/index.html?lang=jp"
                }
            ]
        }

        # Discordに送信
        res = requests.post(WEBHOOK_URL, json=payload)
        if res.status_code == 204:
            print(f"通知成功: {time_str} - {place}")
        else:
            print(f"Discordへの通知に失敗しました: {res.status_code}")

    # すべての送信が終わったら、一番最新の地震IDをファイルに記録
    if new_latest_id:
        with open(STATUS_FILE, "w") as f:
            f.write(new_latest_id)

if __name__ == "__main__":
    main()
