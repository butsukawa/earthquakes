import os
import requests
import json
import re
import time
from datetime import datetime, timedelta, timezone

# Discord Webhook URL (GitHub ActionsのSecretsから読み込む)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATUS_FILE = "last_earthquake.txt"

# 気象庁の地震情報JSON (最新の地震リスト)
JMA_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

def get_earthquake_list():
    try:
        response = requests.get(JMA_LIST_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"リストの取得に失敗しました: {e}")
    return []

# --- 追加・変更箇所（関数を新規追加 / parse_coordinateも少し修正） ---

def parse_coordinate(coord_str):
    """
    気象庁のCoordinate形式 (+35.8+138.3-10000/) をパースし、
    (緯度経度文字列, 緯度数値, 経度数値, 震源深度) のタプルで返す
    """
    if not coord_str:
        return "不明", None, None, "不明"
    
    matches = re.findall(r'([+-]\d+(?:\.\d+)?)', coord_str)
    if len(matches) < 2:
        return "不明", None, None, "不明"
        
    lat_val = float(matches[0])
    lon_val = float(matches[1])
    latlon_str = f"{lat_val}N, {lon_val}E"
    
    depth_str = "不明"
    if len(matches) >= 3:
        depth_val = float(matches[2])
        if depth_val >= 0:
            depth_str = "ごく浅い"
        else:
            depth_str = f"{int(abs(depth_val) / 1000)}km"
            
    return latlon_str, lat_val, lon_val, depth_str


def get_gsi_maps_url(lat, lon):
    """
    緯度・経度を小数点第6位に四捨五入/0埋めし、国土地理院地図のURLを生成する
    """
    if lat is None or lon is None:
        return None
    # 小数点第6位で四捨五入（formatでf指定すると自動で四捨五入・0埋めされます）
    lat_formatted = f"{lat:.6f}"
    lon_formatted = f"{lon:.6f}"
    return f"https://maps.gsi.go.jp/#9/{lat_formatted}/{lon_formatted}/"

def get_earthquake_detail(json_filename):
    """
    個別詳細JSONから必要な詳細データを取得する
    """
    # 変更点：デフォルト値に "gsi_url" を追加
    default_res = {"latlon": "不明", "depth": "不明", "gsi_url": None, "headline": "", "forecast_comment": ""}
    if not json_filename:
        return default_res
    try:
        detail_url = f"https://www.jma.go.jp/bosai/quake/data/{json_filename}"
        res = requests.get(detail_url)
        res.raise_for_status()
        data = res.json()
        
        # 1. 緯度・経度と深度の取得
        coord = data.get("Body", {}).get("Earthquake", {}).get("Hypocenter", {}).get("Area", {}).get("Coordinate", "")
        
        # 変更点：新しく定義した parse_coordinate から、緯度(lat_val)・経度(lon_val)の数値も一緒に受け取る
        latlon, lat_val, lon_val, depth = parse_coordinate(coord) 

        # 変更点：取得した数値を使って国土地理院地図のURLを生成する
        gsi_url = get_gsi_maps_url(lat_val, lon_val)

        # 2. ヘッドラインの取得 (元のロジックのまま)
        headline = data.get("Head", {}).get("Headline", {}).get("Text", "")

        # 3. 津波コメントの取得 (元のロジックのまま)
        forecast_comment = data.get("Body", {}).get("Comments", {}).get("ForecastComment", {}).get("Text", "")

        # 変更点：戻り値の辞書に "gsi_url" を追加して返す
        return {
            "latlon": latlon,
            "depth": depth,
            "gsi_url": gsi_url, # ここに追加
            "headline": headline,
            "forecast_comment": forecast_comment
        }
    except Exception as e:
        print(f"詳細JSONの取得エラー ({json_filename}): {e}")
    return default_res

def get_embed_color(max_int):
    """
    震度に応じたDiscord Embedの10進数カラーコードを返す
    """
    color_map = {
        "1": 8421504,   # 灰色 (#808080)
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

    # 過去の最新IDを読み込み
    last_id = ""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            last_id = f.read().strip()

    # 現在時刻から24時間前の基準時刻 (JSTベース)
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    one_day_ago = now_jst - timedelta(days=1)

    targets = []
    new_latest_id = None
    
    # 重複防止用セット
    processed_eids = set()
    processed_times = set()

    for i, quake in enumerate(quakes):
        quake_id = quake.get("eid", quake.get("at", ""))
        
        if i == 0:
            new_latest_id = quake_id

        if last_id and quake_id == last_id:
            break

        max_int = quake.get("maxi", "").strip()
        if max_int == "" or max_int == "-":
            continue

        at_str = quake.get("at", "")
        
        # 重複・古い速報データのスキップ
        if quake_id in processed_eids or at_str in processed_times:
            continue
        
        try:
            dt = datetime.fromisoformat(at_str)
            if dt < one_day_ago:
                break
        except Exception as e:
            print(f"時刻パースエラー: {e}")
            continue

        if quake.get("eid"):
            processed_eids.add(quake.get("eid"))
        processed_times.add(at_str)

        targets.append((quake_id, quake, dt, max_int))

    if not targets:
        print("通知対象の新しい地震はありません。")
        if new_latest_id and new_latest_id != last_id:
            with open(STATUS_FILE, "w") as f:
                f.write(new_latest_id)
        return

    # 古い順（発生した順）にソート
    targets.reverse()

    print(f"{len(targets)} 件の地震情報を送信します。")

    for quake_id, quake, dt, max_int in targets:
        place = quake.get("anm", "---")
        mag = quake.get("mag", "不明")
        ctt = quake.get("ctt", "")
        json_file = quake.get("json", "")
        ttl = quake.get("ttl", "震源・震度情報")

        # 1. 個別詳細JSONから詳細項目（緯度経度・ヘッドライン・津波）を取得
        detail = get_earthquake_detail(json_file)
        
        # 震度速報時などで震源が取得できない場合のケア
        if (place == "" or place == "---") and "速報" in ttl:
            place = "（震源地は調査中）"

        # 2. 発生日時のフォーマット（秒を除外して「頃」を付与）
        time_str_display = f"{dt.strftime('%Y-%m-%d %H:%M')} 頃"

        # 3. コメント欄の構築（ヘッドライン文 ＋ 津波情報をマージ）
        comment_parts = []
        if detail["headline"]:
            comment_parts.append(detail["headline"])
        if detail["forecast_comment"]:
            comment_parts.append(detail["forecast_comment"])
        comment_display = "\n".join(comment_parts) if comment_parts else "なし"

        # 4. タイトル用URL (cttを利用)
        detail_url = f"https://www.data.jma.go.jp/multi/quake/quake_detail.html?eventID={ctt}&lang=jp" if ctt else "https://www.data.jma.go.jp/multi/quake/index.html?lang=jp"

        # タイトルの日付作成用の年月日
        title_date_str = dt.strftime('%Y年%m月%d日')

        int_display_map = {"5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強"}
        max_int_display = int_display_map.get(max_int, max_int)
        embed_color = get_embed_color(max_int)

        # ご要望通りのメッセージ本文を組み立て（震源深度を追加）
        description_text = (
            f"**・地震概要**\n"
            f"震源地域: {place}（{detail['latlon']}）\n"
            f"震源深度: {detail['depth']}\n"
            f"発生日時: {time_str_display}\n"
            f"最大震度: 震度 {max_int_display}（地震の規模: M{mag}）\n\n"
            f"**・コメント**\n"
            f"{comment_display}"
        )

        payload = {
            "embeds": [
                {
                    "title": f"【地震速報】地震が発生しました。",
                    "url": detail_url,
                    "color": embed_color,
                    "description": description_text,
                    "footer": {"text": "情報提供: 気象庁"}
                }
            ]
        }

        # カンマで区切られた複数のURLをリストに分解する
        webhook_urls = [url.strip() for url in WEBHOOK_URL.split(",")]
        
        # それぞれのURLに対して順番に送信する
        for url in webhook_urls:
            if not url:
                continue
            try:
                res = requests.post(url, json=payload)
                if res.status_code == 204:
                    print(f"通知成功: {time_str_display} - {place}")
                else:
                    print(f"Discordへの通知に失敗しました ({res.status_code})")
            except Exception as e:
                print(f"Webhook送信中にエラーが発生しました: {e}")

    if new_latest_id:
        with open(STATUS_FILE, "w") as f:
            f.write(new_latest_id)

# --- 変更箇所（スクリプトの一番下、実行部分） ---
if __name__ == "__main__":
    # 5時間50分 = 350分 = 21,000秒
    RUN_DURATION = 21000  
    INTERVAL = 300 # 5分
    
    start_time = time.time()
    print("地震監視スクリプトを開始しました（5時間50分稼働します）")
    
    while True:
        # メイン処理の実行
        main()
        
        # 経過時間のチェック
        elapsed_time = time.time() - start_time
        if elapsed_time + INTERVAL > RUN_DURATION:
            print("5時間50分が経過するため、監視を終了します。")
            break
            
        print(f"次の確認まで {INTERVAL} 秒待機します... (残り時間: {int((RUN_DURATION - elapsed_time)/60)} 分)")
        time.sleep(INTERVAL)
