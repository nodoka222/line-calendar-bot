"""Google Calendar API連携"""
import os
import json
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


def get_credentials_info( ):
    """環境変数からcredentials情報を取得"""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
    if not creds_json:
        if os.path.exists('credentials.json'):
            with open('credentials.json', 'r') as f:
                return json.load(f)
        return None

    try:
        return json.loads(creds_json)
    except json.JSONDecodeError:
        logger.error('GOOGLE_CREDENTIALS_JSONのパースに失敗しました')
        return None


def get_token():
    """保存済みトークンを取得"""
    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if token_json:
        try:
            return json.loads(token_json)
        except Exception:
            pass

    if os.path.exists('token.json'):
        with open('token.json', 'r') as f:
            return json.load(f)

    return None


def get_auth_url():
    """Google OAuth2認証URLを生成"""
    from google_auth_oauthlib.flow import Flow

    creds_info = get_credentials_info()
    if not creds_info:
        raise Exception('Google認証情報が設定されていません')

    flow = Flow.from_client_config(
        creds_info,
        scopes=SCOPES,
        redirect_uri=os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/google/callback' )
    )

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )

    return auth_url


def handle_callback(code: str):
    """OAuth2コールバック処理"""
    from google_auth_oauthlib.flow import Flow

    creds_info = get_credentials_info()
    if not creds_info:
        raise Exception('Google認証情報が設定されていません')

    flow = Flow.from_client_config(
        creds_info,
        scopes=SCOPES,
        redirect_uri=os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/google/callback' )
    )

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes) if creds.scopes else []
    }

    with open('token.json', 'w') as f:
        json.dump(token_data, f)

    logger.info('Google認証トークンを保存しました')
    return token_data


def get_todays_events():
    """今日のGoogleカレンダーの予定を取得"""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_data = get_token()
        if not token_data:
            logger.warning('Googleトークンが設定されていません')
            return []

        creds_info = get_credentials_info()
        if not creds_info:
            return []

        client_config = creds_info.get('web', creds_info.get('installed', {}))

        creds = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token' ),
            client_id=token_data.get('client_id', client_config.get('client_id', '')),
            client_secret=token_data.get('client_secret', client_config.get('client_secret', '')),
            scopes=token_data.get('scopes', SCOPES)
        )

        service = build('calendar', 'v3', credentials=creds)

        now = datetime.now(JST)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        return events_result.get('items', [])

    except Exception as e:
        logger.error(f'Googleカレンダー取得エラー: {e}')
        return []
