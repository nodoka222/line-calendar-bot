# google_calendar.py
"""Google Calendar / Tasks API ラッパー"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')

# Calendar + Tasks の両スコープを要求
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks.readonly',
]

TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'


# ── 認証情報ヘルパー ──────────────────────────────────────────

def _creds_config() -> Optional[dict]:
    """OAuth2 クライアント設定を環境変数またはファイルから読み込む"""
    raw = os.environ.get('GOOGLE_CREDENTIALS_JSON', '').strip()
    if raw:
        return json.loads(raw)
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, encoding='utf-8') as f:
            return json.load(f)
    return None


def _load_token() -> Optional[Credentials]:
    """環境変数またはファイルからトークンを読み込む"""
    raw = os.environ.get('GOOGLE_TOKEN_JSON', '').strip()
    if raw:
        try:
            return Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        except Exception as e:
            logger.error(f"環境変数からのトークン読み込み失敗: {e}")

    if os.path.exists(TOKEN_FILE):
        try:
            return Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.error(f"ファイルからのトークン読み込み失敗: {e}")

    return None


def _save_token(creds: Credentials):
    """トークンをファイルに保存する"""
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
        logger.info("Googleトークンを保存しました")
    except Exception as e:
        logger.error(f"トークン保存失敗: {e}")


def get_credentials() -> Optional[Credentials]:
    """有効な（必要なら更新した）認証情報を返す。未認証の場合は None"""
    creds = _load_token()
    if creds is None:
        logger.warning("Google認証情報が見つかりません。/auth/google にアクセスして認証してください。")
        return None

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            logger.info("Googleトークンを更新しました")
        except Exception as e:
            logger.error(f"トークン更新失敗: {e}")
            return None

    return creds if creds.valid else None


# ── OAuth2 フロー ─────────────────────────────────────────────

def _redirect_uri(host_url: str) -> str:
    return host_url.rstrip('/') + '/auth/google/callback'


def get_auth_url(host_url: str) -> str:
    """Google OAuth2 認証URLを生成する"""
    cfg = _creds_config()
    if not cfg:
        raise ValueError(
            "Google認証情報が設定されていません。"
            "GOOGLE_CREDENTIALS_JSON 環境変数または credentials.json を設置してください。"
        )
    flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=_redirect_uri(host_url))
    url, _ = flow.authorization_url(access_type='offline', prompt='consent')
    return url


def handle_auth_callback(code: str, host_url: str) -> bool:
    """OAuth2 コールバックを処理してトークンを保存する"""
    try:
        cfg = _creds_config()
        if not cfg:
            return False
        flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=_redirect_uri(host_url))
        flow.fetch_token(code=code)
        _save_token(flow.credentials)
        logger.info("Google OAuth2 認証が完了しました")
        return True
    except Exception as e:
        logger.error(f"OAuth2 コールバックエラー: {e}")
        return False


# ── Calendar API ──────────────────────────────────────────────

def get_today_events() -> Optional[list]:
    """今日のカレンダーイベントを返す。認証エラーの場合は None"""
    creds = get_credentials()
    if not creds:
        return None

    try:
        svc = build('calendar', 'v3', credentials=creds)
        now = datetime.now(JST)
        t_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        t_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        result = svc.events().list(
            calendarId='primary',
            timeMin=t_min,
            timeMax=t_max,
            singleEvents=True,
            orderBy='startTime',
        ).execute()

        return result.get('items', [])
    except Exception as e:
        logger.error(f"get_today_events エラー: {e}")
        return None


def get_today_tasks() -> list:
    """Google Tasks の未完了タスクをすべて返す（認証エラー時は空リスト）"""
    creds = get_credentials()
    if not creds:
        return []

    try:
        svc = build('tasks', 'v1', credentials=creds)
        lists_result = svc.tasklists().list(maxResults=20).execute()
        all_tasks = []

        for tl in lists_result.get('items', []):
            tasks_result = svc.tasks().list(
                tasklist=tl['id'],
                showCompleted=False,
                maxResults=50,
            ).execute()
            for t in tasks_result.get('items', []):
                if t.get('status') != 'completed':
                    all_tasks.append(t)

        return all_tasks
    except Exception as e:
        logger.error(f"get_today_tasks エラー: {e}")
        return []


def add_event(event_data: dict) -> Optional[dict]:
    """Googleカレンダーにイベントを作成して返す。失敗時は None"""
    creds = get_credentials()
    if not creds:
        logger.error("認証情報がないためイベントを追加できません")
        return None

    try:
        svc = build('calendar', 'v3', credentials=creds)
        start_dt = event_data.get('start_datetime', '')
        end_dt = event_data.get('end_datetime')
        is_all_day = event_data.get('is_all_day', False)

        if is_all_day:
            date_str = str(start_dt)[:10]
            body = {
                'summary': event_data.get('summary', '予定'),
                'description': event_data.get('description', ''),
                'start': {'date': date_str},
                'end': {'date': date_str},
            }
        else:
            start_dt = _to_jst_iso(start_dt)
            if end_dt:
                end_dt = _to_jst_iso(end_dt)
            else:
                # 終了時刻が不明な場合はデフォルトで1時間
                try:
                    dt = datetime.fromisoformat(start_dt)
                    end_dt = (dt + timedelta(hours=1)).isoformat()
                except Exception:
                    end_dt = start_dt

            body = {
                'summary': event_data.get('summary', '予定'),
                'description': event_data.get('description', ''),
                'start': {'dateTime': start_dt, 'timeZone': 'Asia/Tokyo'},
                'end': {'dateTime': end_dt, 'timeZone': 'Asia/Tokyo'},
            }

        created = svc.events().insert(calendarId='primary', body=body).execute()
        logger.info(f"イベント作成完了: {created.get('id')} - {created.get('summary')}")
        return created

    except Exception as e:
        logger.error(f"add_event エラー: {e}")
        return None


def _to_jst_iso(dt_str: str) -> str:
    """タイムゾーン情報がない場合は JST として解釈し、ISO文字列を返す"""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = JST.localize(dt)
        return dt.isoformat()
    except Exception:
        return dt_str
