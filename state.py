# state.py
"""共有アプリケーション状態（循環インポート回避用）"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# main.py で初期化される
line_bot_api = None

# event_id -> {user_id, source, event_data, original_text}
pending_events: dict = {}

# LINEユーザーID集合（プッシュ通知用）
user_ids: set = set()


def init_line_bot_api():
    """LINE Bot API クライアントを初期化する"""
    global line_bot_api
    from linebot import LineBotApi
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
    if token:
        line_bot_api = LineBotApi(token)
        logger.info("LINE Bot API initialized")
    else:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN が未設定です")


def save_user_id(user_id: str):
    """LINE ユーザーIDを永続化する（再起動後もプッシュ通知可能にする）"""
    user_ids.add(user_id)
    try:
        with open('user_ids.json', 'w', encoding='utf-8') as f:
            json.dump(list(user_ids), f)
    except Exception as e:
        logger.error(f"ユーザーID保存失敗: {e}")


def load_user_ids():
    """保存済みのユーザーIDと環境変数のユーザーIDを読み込む"""
    try:
        with open('user_ids.json', 'r', encoding='utf-8') as f:
            for uid in json.load(f):
                user_ids.add(uid)
        logger.info(f"ユーザーID読み込み: {len(user_ids)} 件")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"ユーザーID読み込み失敗: {e}")

    env_uid = os.environ.get('LINE_USER_ID', '').strip()
    if env_uid:
        user_ids.add(env_uid)


def get_primary_user_id() -> Optional[str]:
    """プッシュ通知先のメインユーザーIDを返す"""
    if user_ids:
        return next(iter(user_ids))
    return None
