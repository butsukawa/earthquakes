import os
import requests
import json
from datetime import datetime

# Discord Webhook URL (GitHub ActionsのSecretsから読み込む)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATUS_FILE = "last_earthquake.txt"

# 気象庁の地震情報JSON (最新の地震リスト)
JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

def get_latest_earthquake():
    try:
        response = requests.get(JMA_URL)
        response.raise_for_status()
        data = response.json()
        if data:
            # 配列の先頭が最新の地震情報
            return data[0]
    except Exception as e:
        print(f"データの取得に失敗しました: {e}")
    return None

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
    # 万が一想定外の表記（海外の地震など）だった場合はグレーにする
    return color_map.get(max_int, 9807270)

def main():
    if not WEBHOOK_URL:
        print("エラー: DISCORD_WEBHOOK_URL が設定されていません。")
        return

    quake = get_latest_earthquake()
    if not quake:
        return

    # 一意のID（発表時刻やコードなどをキーにする）
    quake_id = quake.get("eid", quake.get("at", ""))
    
    # 過去の最新IDを読み込み
    last_id = ""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            last_id = f.read().strip()

    # 新しい地震がない場合は終了
    if quake_id == last_id:
        print("新しい地震情報はありません。")
        return

    # 1. 震度情報がないデータ（「顕著な地震の震源要素更新のお知らせ」など）の除外処理
    max_int = quake.get("maxi", "").strip()
    if max_int == "" or max_int == "-":
        print(f"震度情報が含まれないため通知をスキップします。 (タイトル: {quake.get('ttl')})")
        # 次回重複して読み込まないように、通知はしなくてもIDだけは更新しておく
        with open(STATUS_FILE, "w") as f:
            f.write(quake_id)
        return

    # 地震情報のパース
    at_str = quake.get("at", "不明")
    try:
        dt = datetime.fromisoformat(at_str)
        time_str = dt.strftime("%Y/%m/%d %H:%M")
    except:
        time_str = at_str

    place = quake.get("anm", "調査中") # 震源地
    mag = quake.get("mag", "不明")    # マグニチュード
    
    # 震度表示の日本語表記調整 (5- や 5+ を 5弱 や 5強 に見やすく変換)
    int_display_map = {"5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強"}
    max_int_display = int_display_map.get(max_int, max_int)

    # 震度に基づいたEmbedカラーを取得
    embed_color = get_embed_color(max_int)

    # Discordへの通知メッセージ（埋め込み形式）
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
        print("Discordへの通知に成功しました。")
        # 今回通知したIDを保存
        with open(STATUS_FILE, "w") as f:
            f.write(quake_id)
    else:
        print(f"Discordへの通知に失敗しました: {res.status_code}")

if __name__ == "__main__":
    main()
