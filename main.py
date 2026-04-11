# main.py
"""LINE Calendar Bot – Flask アプリケーション エントリーポイント"""
import os
import json
import uuid
import logging

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, PostbackEvent,
    TextSendMessage, TemplateSendMessage, ConfirmTemplate, PostbackAction,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

# ── 共有状態の初期化 ──────────────────────────────────────────
import state

state.init_line_bot_api()
state.load_user_ids()

# ── Flask アプリ ──────────────────────────────────────────────
app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ── ヘルパー関数 ──────────────────────────────────────────────

def _fmt_event_preview(event_data: dict) -> str:
    """カレンダー追加確認メッセージ用のプレビューテキストを生成する"""
    summary = event_data.get('summary', '予定')
    start = event_data.get('start_datetime', '')
    desc = event_data.get('description', '')

    lines = [f"📌 {summary}"]
    if start:
        lines.append(f"🕐 {start}")
    if desc:
        lines.append(f"📝 {desc[:50]}")
    return '\n'.join(lines)


def build_confirm_message(event_id: str, event_data: dict, prefix: str = '') -> TemplateSendMessage:
    """Googleカレンダー追加確認用の ConfirmTemplate を返す"""
    preview = _fmt_event_preview(event_data)
    body = (prefix + preview)[:240]  # ConfirmTemplate のテキスト上限

    return TemplateSendMessage(
        alt_text='Googleカレンダーに追加しますか？',
        template=ConfirmTemplate(
            text=body,
            actions=[
                PostbackAction(
                    label='追加する ✅',
                    data=json.dumps({'action': 'add', 'event_id': event_id}),
                ),
                PostbackAction(
                    label='追加しない ❌',
                    data=json.dumps({'action': 'skip', 'event_id': event_id}),
                ),
            ],
        ),
    )


# ── LINE Webhook ──────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("LINEシグネチャが不正です")
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def on_text_message(event):
    """【機能3】LINEメッセージから予定を検出してカレンダー追加を提案する"""
    user_id = event.source.user_id
    text = event.message.text.strip()

    # ユーザーIDを保存（プッシュ通知用）
    state.save_user_id(user_id)

    from ai_analyzer import analyze_message
    try:
        result = analyze_message(text)
    except Exception as e:
        logger.error(f"AI分析エラー: {e}")
        return

    if not (result and result.get('has_schedule')):
        return  # 予定が検出されなければ何もしない

    eid = str(uuid.uuid4())
    state.pending_events[eid] = {
        'user_id': user_id,
        'source': 'line',
        'event_data': result['event_data'],
        'original_text': text,
    }

    msg = build_confirm_message(
        eid,
        result['event_data'],
        prefix='📅 予定を検出しました！\n\n',
    )
    state.line_bot_api.reply_message(event.reply_token, msg)


@handler.add(PostbackEvent)
def on_postback(event):
    """「追加する」「追加しない」ボタンのポストバックを処理する"""
    try:
        data = json.loads(event.postback.data)
    except (json.JSONDecodeError, KeyError):
        return

    action = data.get('action')
    eid = data.get('event_id', '')

    if action == 'add':
        pending = state.pending_events.pop(eid, None)
        if not pending:
            state.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text='⚠️ 予定情報が見つかりませんでした（タイムアウトの可能性）。'),
            )
            return

        from google_calendar import add_event
        result = add_event(pending['event_data'])

        if result:
            summary = result.get('summary', '予定')
            start_info = result.get('start', {})
            start_str = start_info.get('dateTime', start_info.get('date', ''))
            state.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f'✅ Googleカレンダーに追加しました！\n\n📌 {summary}\n🕐 {start_str}'
                ),
            )
        else:
            state.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text='❌ カレンダーへの追加に失敗しました。\n'
                         '認証が必要な場合は /auth/google にアクセスしてください。'
                ),
            )

    elif action == 'skip':
        state.pending_events.pop(eid, None)
        state.line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='わかりました。カレンダーには追加しませんでした。'),
        )


# ── Google OAuth2 エンドポイント ──────────────────────────────

@app.route('/auth/google')
def auth_google():
    """Google OAuth2 フローを開始する"""
    from google_calendar import get_auth_url
    try:
        url = get_auth_url(request.host_url)
        return (
            '<h2>Google Calendar 認証</h2>'
            f'<p><a href="{url}" style="font-size:1.2em;">🔗 こちらをクリックしてGoogleアカウントで認証</a></p>'
            '<p>認証後、このページに自動的にリダイレクトされます。</p>'
        )
    except Exception as e:
        return f'<p>エラー: {e}</p>', 500


@app.route('/auth/google/callback')
def auth_google_callback():
    """Google OAuth2 コールバックを処理してトークンを保存する"""
    code = request.args.get('code')
    if not code:
        return '認証がキャンセルされました。', 400

    from google_calendar import handle_auth_callback
    ok = handle_auth_callback(code, request.host_url)
    if ok:
        return (
            '<h2>✅ 認証完了！</h2>'
            '<p>Googleカレンダーへのアクセスが有効になりました。</p>'
            '<p>このブラウザタブを閉じてください。</p>'
        )
    return '❌ 認証処理に失敗しました。サーバーログを確認してください。', 500


# ── ヘルスチェック ─────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
    user_count = len(state.user_ids)
    auth_status = '✅ 認証済み' if os.path.exists('token.json') else '❌ 未認証 → /auth/google'
    return (
        f'<h2>LINE Calendar Bot 🤖</h2>'
        f'<p>Status: 稼働中</p>'
        f'<p>Google Calendar: {auth_status}</p>'
        f'<p>登録ユーザー数: {user_count}</p>'
        f'<p><a href="/auth/google">Google認証はこちら</a></p>'
    )


# ── アプリ起動時の初期化 ──────────────────────────────────────

def _startup():
    from scheduler import start_scheduler
    start_scheduler()


_startup()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
