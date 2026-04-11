# scheduler.py
"""APScheduler セットアップ（毎朝6時の通知 + Chatwork ポーリング）"""
import os
import logging
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

JST = pytz.timezone('Asia/Tokyo')
_scheduler: Optional[BackgroundScheduler] = None


# ── ジョブ定義 ────────────────────────────────────────────────

def _morning_notification_job():
    """【機能1】毎朝6時にGoogleカレンダーの予定とToDoをLINEに送信する"""
    logger.info("朝の通知ジョブ開始")
    try:
        import state
        from google_calendar import get_today_events, get_today_tasks
        from linebot.models import TextSendMessage

        user_id = state.get_primary_user_id()
        if not user_id:
            logger.warning("朝の通知: LINE ユーザーID が未設定です（LINEでメッセージを送ると自動登録されます）")
            return
        if not state.line_bot_api:
            logger.warning("朝の通知: LINE Bot API が未初期化です")
            return

        events = get_today_events()
        tasks = get_today_tasks()
        message = _build_morning_message(events, tasks)

        state.line_bot_api.push_message(user_id, TextSendMessage(text=message))
        logger.info("朝の通知を送信しました")

    except Exception as e:
        logger.error(f"朝の通知エラー: {e}")


def _chatwork_poll_job():
    """Chatwork の新着メッセージをポーリングする"""
    try:
        from chatwork_monitor import poll_chatwork
        poll_chatwork()
    except Exception as e:
        logger.error(f"Chatwork ポーリングエラー: {e}")


# ── メッセージ生成 ────────────────────────────────────────────

def _build_morning_message(events, tasks) -> str:
    """朝の通知メッセージを組み立てる"""
    from datetime import datetime as dt_

    today = dt_.now(JST)
    weekday_ja = ['月', '火', '水', '木', '金', '土', '日'][today.weekday()]
    date_str = today.strftime(f'%Y年%m月%d日({weekday_ja})')

    lines = [
        f'☀️ おはようございます！',
        f'📅 {date_str}の予定をお知らせします。',
        '',
    ]

    # ── カレンダーイベント ──
    lines.append('【📆 今日のカレンダー】')
    if events is None:
        lines.append('  ⚠️ Googleカレンダーに接続できませんでした')
        lines.append('  → アプリの /auth/google で認証してください')
    elif events:
        for ev in events:
            summary = ev.get('summary', '（タイトルなし）')
            start = ev.get('start', {})
            dt_str = start.get('dateTime', start.get('date', ''))
            if 'T' in dt_str:
                try:
                    t = dt_.fromisoformat(dt_str)
                    time_label = t.strftime('%H:%M')
                except Exception:
                    time_label = dt_str
                lines.append(f'  🕐 {time_label}　{summary}')
            else:
                lines.append(f'  📌 {summary}（終日）')
    else:
        lines.append('  今日の予定はありません')

    lines.append('')

    # ── ToDo / タスク ──
    lines.append('【✅ ToDo】')
    if tasks:
        for t in tasks[:10]:  # 最大10件
            title = t.get('title', '（タイトルなし）')
            due = t.get('due', '')
            due_str = f'  (期限: {due[:10]})' if due else ''
            lines.append(f'  □ {title}{due_str}')
        if len(tasks) > 10:
            lines.append(f'  … 他 {len(tasks) - 10} 件')
    else:
        lines.append('  タスクはありません')

    lines.append('')
    lines.append('今日も良い一日を！ 🌟')

    return '\n'.join(lines)


# ── スケジューラー起動 ────────────────────────────────────────

def start_scheduler():
    """APScheduler を起動する（二重起動防止済み）"""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("スケジューラーはすでに起動中です")
        return

    poll_minutes = int(os.environ.get('CHATWORK_POLL_INTERVAL', '5'))

    _scheduler = BackgroundScheduler(timezone=JST)

    # ── 毎朝6時に予定を通知 ──
    _scheduler.add_job(
        _morning_notification_job,
        CronTrigger(hour=6, minute=0, timezone=JST),
        id='morning_notification',
        name='朝6時の予定通知',
        misfire_grace_time=600,  # 10分以内に実行できれば遅延実行を許可
        replace_existing=True,
    )

    # ── Chatwork ポーリング（デフォルト5分ごと） ──
    _scheduler.add_job(
        _chatwork_poll_job,
        'interval',
        minutes=poll_minutes,
        id='chatwork_poll',
        name='Chatwork ポーリング',
        misfire_grace_time=60,
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"スケジューラー起動完了 "
        f"（朝の通知: 毎朝6:00 JST, Chatwork ポーリング: {poll_minutes}分ごと）"
    )
