# chatwork_monitor.py
"""Chatwork メッセージ監視・ポーリング（機能2）"""
import os
import json
import uuid
import logging
from typing import Optional

import requests
import state

logger = logging.getLogger(__name__)

_API_BASE = 'https://api.chatwork.com/v2'

# 初回ポーリング済みルームID（既読ドレイン済み）
_initialized_rooms: set = set()


def _token() -> str:
    return os.environ.get('CHATWORK_API_TOKEN', '').strip()


def _headers() -> dict:
    return {'X-ChatWorkToken': _token()}


# ── Chatwork API 呼び出し ──────────────────────────────────────

def _get_rooms() -> list:
    """参加中のルーム一覧を取得する"""
    try:
        r = requests.get(f'{_API_BASE}/rooms', headers=_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Chatwork ルーム取得エラー: {e}")
        return []


def _get_new_messages(room_id) -> list:
    """ルームの未読メッセージを取得する（force=0 でサーバー管理の既読位置を使用）"""
    try:
        r = requests.get(
            f'{_API_BASE}/rooms/{room_id}/messages',
            headers=_headers(),
            params={'force': 0},
            timeout=10,
        )
        if r.status_code == 204:  # 新着なし
            return []
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Chatwork メッセージ取得エラー (room={room_id}): {e}")
        return []


# ── メッセージ処理 ────────────────────────────────────────────

def _process_messages(room_id, messages: list):
    """メッセージを AI で分析して予定を検出したら LINE に通知する"""
    from ai_analyzer import analyze_message
    from linebot.models import TemplateSendMessage, ConfirmTemplate, PostbackAction

    for msg in messages:
        body: str = msg.get('body', '').strip()
        sender: str = msg.get('account', {}).get('name', '不明')

        # システムメッセージやリプライ記法はスキップ
        if not body or body.startswith('[info]') or body.startswith('[To:'):
            continue

        # 長すぎるメッセージは先頭 1000 文字だけ分析
        analyze_text = body[:1000]

        try:
            result = analyze_message(analyze_text)
        except Exception as e:
            logger.error(f"AI分析エラー (msg={msg.get('message_id')}): {e}")
            continue

        if not (result and result.get('has_schedule')):
            continue

        eid = str(uuid.uuid4())
        event_data: dict = result['event_data']
        state.pending_events[eid] = {
            'source': 'chatwork',
            'room_id': room_id,
            'event_data': event_data,
            'original_text': body,
        }

        user_id = state.get_primary_user_id()
        if not user_id or not state.line_bot_api:
            logger.warning("LINE ユーザーID または API クライアント未設定のため通知不可")
            continue

        summary = event_data.get('summary', '予定')
        start = event_data.get('start_datetime', '')

        preview_lines = [f"📌 {summary}"]
        if start:
            preview_lines.append(f"🕐 {start}")

        notice_text = (
            f"📨 Chatworkに予定を検出しました！\n"
            f"👤 {sender}\n\n"
            + '\n'.join(preview_lines)
        )[:240]

        confirm_msg = TemplateSendMessage(
            alt_text='Googleカレンダーに追加しますか？',
            template=ConfirmTemplate(
                text=notice_text,
                actions=[
                    PostbackAction(
                        label='追加する ✅',
                        data=json.dumps({'action': 'add', 'event_id': eid}),
                    ),
                    PostbackAction(
                        label='追加しない ❌',
                        data=json.dumps({'action': 'skip', 'event_id': eid}),
                    ),
                ],
            ),
        )

        try:
            state.line_bot_api.push_message(user_id, confirm_msg)
            logger.info(f"Chatwork 予定通知送信 (event_id={eid}, room={room_id})")
        except Exception as e:
            logger.error(f"LINE push_message エラー: {e}")


# ── 公開ポーリング関数（スケジューラーから呼ばれる） ────────────

def poll_chatwork():
    """Chatwork の新着メッセージをチェックして予定を検出する"""
    if not _token():
        logger.debug("CHATWORK_API_TOKEN 未設定のためスキップ")
        return

    # CHATWORK_ROOM_IDS が設定されていれば対象ルームを絞り込む
    target_ids_raw = os.environ.get('CHATWORK_ROOM_IDS', '').strip()
    target_ids: Optional[set] = set(target_ids_raw.split(',')) if target_ids_raw else None

    rooms = _get_rooms()

    for room in rooms:
        rid = str(room.get('room_id', ''))
        if not rid:
            continue
        if target_ids and rid not in target_ids:
            continue

        messages = _get_new_messages(rid)

        if rid not in _initialized_rooms:
            # 初回ポーリング：既存の未読メッセージを処理せずドレインのみ
            # （Bot 起動前のメッセージで大量通知が飛ぶのを防ぐ）
            _initialized_rooms.add(rid)
            logger.info(f"Chatwork ルーム {rid} を初期化（{len(messages)} 件の既存メッセージをスキップ）")
            continue

        if messages:
            logger.info(f"Chatwork ルーム {rid} の新着 {len(messages)} 件を処理中")
            _process_messages(rid, messages)
