"""スケジューラー - 毎朝6時にGoogleカレンダーの予定をLINEに送信"""
import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')
scheduler = BackgroundScheduler(timezone=JST)


def send_morning_summary():
    """毎朝6時に今日の予定をLINEに送信"""
    logger.info('朝の通知を送信します...')

    line_user_id = os.environ.get('LINE_USER_ID', '')
    if not line_user_id:
        logger.warning('LINE_USER_IDが設定されていません')
        return

    try:
        from google_calendar import get_todays_events
        events = get_todays_events()

        if events:
            message = '🌅 おはようございます！今日の予定です：\n\n'
            for event in events:
                start = event.get('start', {})
                time_str = start.get('dateTime', start.get('date', ''))
                if 'T' in time_str:
                    time_str = time_str[11:16]
                summary = event.get('summary', '（タイトルなし）')
                message += f'📅 {time_str} {summary}\n'
        else:
            message = '🌅 おはようございます！今日は予定がありません。\n良い一日をお過ごしください！'

        from main import send_line_message
        send_line_message(line_user_id, message)
        logger.info('朝の通知を送信しました')

    except Exception as e:
        logger.error(f'朝の通知エラー: {e}')
        try:
            from main import send_line_message
            send_line_message(line_user_id, f'朝の通知でエラーが発生しました: {str(e)}')
        except Exception:
            pass


def check_chatwork():
    """Chatworkのメッセージをチェックしてタスク・締切を検出"""
    logger.info('Chatworkをチェックします...')

    chatwork_token = os.environ.get('CHATWORK_API_TOKEN', '')
    chatwork_room_ids = os.environ.get('CHATWORK_ROOM_IDS', '')
    line_user_id = os.environ.get('LINE_USER_ID', '')

    if not chatwork_token or not chatwork_room_ids or not line_user_id:
        logger.debug('Chatwork設定が不完全です')
        return

    try:
        import requests as req
        room_ids = [r.strip() for r in chatwork_room_ids.split(',') if r.strip()]

        for room_id in room_ids:
            url = f'https://api.chatwork.com/v2/rooms/{room_id}/messages'
            headers = {'X-ChatWorkToken': chatwork_token}
            resp = req.get(url, headers=headers, timeout=10 )

            if resp.status_code == 200:
                messages = resp.json()
                if messages:
                    combined = '\n'.join([m.get('body', '') for m in messages[-5:]])

                    from main import analyze_message_with_ai, send_line_message
                    analysis = analyze_message_with_ai(combined)

                    if '予定' in analysis or '締切' in analysis or 'タスク' in analysis or 'deadline' in analysis.lower():
                        message = f'💬 Chatwork({room_id})から通知:\n{analysis}'
                        send_line_message(line_user_id, message)

    except Exception as e:
        logger.error(f'Chatworkチェックエラー: {e}')


def start_scheduler():
    """スケジューラーを開始"""
    if scheduler.running:
        logger.info('スケジューラーはすでに起動中です')
        return

    scheduler.add_job(
        send_morning_summary,
        CronTrigger(hour=6, minute=0, timezone=JST),
        id='morning_summary',
        replace_existing=True
    )
    logger.info('朝6時の予定通知ジョブを登録しました')

    chatwork_token = os.environ.get('CHATWORK_API_TOKEN', '')
    if chatwork_token:
        scheduler.add_job(
            check_chatwork,
            'interval',
            minutes=5,
            id='chatwork_check',
            replace_existing=True
        )
        logger.info('Chatworkポーリングジョブを登録しました（5分ごと）')

    scheduler.start()
    logger.info('スケジューラーを起動しました')
