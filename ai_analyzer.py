# ai_analyzer.py
"""OpenAI API を使ったメッセージ分析（予定・締め切りの検出）"""
import os
import json
import logging
from datetime import datetime
from typing import Optional

import pytz
from openai import OpenAI

logger = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get('OPENAI_API_KEY', '').strip()
        if not key:
            raise EnvironmentError("OPENAI_API_KEY が設定されていません")
        _client = OpenAI(api_key=key)
    return _client


def analyze_message(text: str) -> dict:
    """
    メッセージを分析して予定・締め切りを抽出する。

    Returns:
        予定なし: {"has_schedule": false}
        予定あり: {
            "has_schedule": true,
            "event_data": {
                "summary": str,
                "description": str,
                "start_datetime": "YYYY-MM-DDTHH:MM:SS",
                "end_datetime": "YYYY-MM-DDTHH:MM:SS or null",
                "is_all_day": bool
            }
        }
    """
    today = datetime.now(JST).strftime('%Y年%m月%d日(%a)')
    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

    prompt = f"""\
あなたは日本語のメッセージから予定・締め切りを抽出するアシスタントです。
今日の日付: {today}

【抽出ルール】
- 具体的な日時（「3月15日」「来週月曜14時」「明日の午後3時」など）が含まれる場合のみ抽出
- 「後で」「そのうち」「いつか」など曖昧な表現は抽出しない
- 年が不明な場合は今年とする
- 相対表現（「明日」「来週月曜」など）は今日の日付を基準に絶対日付に変換する
- 終了時刻が不明な場合は end_datetime を null にする
- 終日の予定は is_all_day を true にする
- summary はイベントの内容を簡潔に表すタイトルにする（例：「田中さんとミーティング」「企画書提出締め切り」）

【出力形式】JSONのみで回答（説明文・コードブロック不要）

予定あり:
{{"has_schedule":true,"event_data":{{"summary":"タイトル","description":"詳細","start_datetime":"YYYY-MM-DDTHH:MM:SS","end_datetime":"YYYY-MM-DDTHH:MM:SS or null","is_all_day":false}}}}

予定なし:
{{"has_schedule":false}}

---
分析対象メッセージ:
{text}
"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()

        # マークダウンコードブロックがあれば除去
        if '```' in raw:
            parts = raw.split('```')
            # ```json ... ``` または ``` ... ``` の中身を取り出す
            for part in parts[1::2]:
                part = part.strip()
                if part.startswith('json'):
                    part = part[4:].strip()
                if part.startswith('{'):
                    raw = part
                    break

        result = json.loads(raw)
        logger.debug(f"AI分析結果: has_schedule={result.get('has_schedule')}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"AIレスポンスのJSON解析失敗: {e} | raw={raw!r}")
        return {'has_schedule': False}
    except Exception as e:
        logger.error(f"analyze_message エラー: {e}")
        return {'has_schedule': False}
