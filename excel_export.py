# excel_export.py
import sqlite3
import pandas as pd
from datetime import datetime
import os
from config import DB_NAME, logger


def export_database_to_excel():
    try:
        temp_dir = "temp_exports"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(temp_dir, f"bot_database_export_{timestamp}.xlsx")

        conn = sqlite3.connect(DB_NAME)

        with pd.ExcelWriter(filename, engine='openpyxl') as writer:

            users_df = pd.read_sql_query("SELECT * FROM users", conn)
            if not users_df.empty:
                users_df.to_excel(writer, sheet_name='Пользователи', index=False)

            transactions_df = pd.read_sql_query("SELECT * FROM transactions", conn)
            if not transactions_df.empty:
                transactions_df.to_excel(writer, sheet_name='Транзакции', index=False)

            payments_df = pd.read_sql_query("SELECT * FROM payments", conn)
            if not payments_df.empty:
                payments_df.to_excel(writer, sheet_name='Платежи', index=False)

            sessions_df = pd.read_sql_query("SELECT * FROM sessions", conn)
            if not sessions_df.empty:
                sessions_df.to_excel(writer, sheet_name='Сессии', index=False)

            settings_df = pd.read_sql_query("SELECT * FROM settings", conn)
            if not settings_df.empty:
                settings_df.to_excel(writer, sheet_name='Настройки', index=False)

            stats_data = generate_statistics(conn)
            stats_df = pd.DataFrame([stats_data])
            stats_df.to_excel(writer, sheet_name='Статистика', index=False)

        conn.close()

        logger.info(f"✅ База данных успешно экспортирована в {filename}")
        return filename

    except Exception as e:
        logger.error(f"❌ Ошибка при экспорте базы данных: {e}")

        try:
            if 'filename' in locals() and os.path.exists(filename):
                os.remove(filename)
        except:
            pass

        return None


def generate_statistics(conn):
    stats = {}

    try:
        users_stats = pd.read_sql_query("""
            SELECT 
                COUNT(*) as total_users,
                COUNT(DISTINCT referrer_id) as users_with_referrals,
                SUM(balance) as total_balance,
                AVG(balance) as avg_balance
            FROM users
        """, conn)

        if not users_stats.empty:
            stats['Всего пользователей'] = users_stats.iloc[0]['total_users']
            stats['Пользователей с рефералами'] = users_stats.iloc[0]['users_with_referrals']
            stats['Общий баланс'] = round(users_stats.iloc[0]['total_balance'] or 0, 2)
            stats['Средний баланс'] = round(users_stats.iloc[0]['avg_balance'] or 0, 2)

        transactions_stats = pd.read_sql_query("""
            SELECT 
                type,
                COUNT(*) as count,
                SUM(amount) as total_amount
            FROM transactions 
            WHERE status = 'completed'
            GROUP BY type
        """, conn)

        for _, row in transactions_stats.iterrows():
            stats[f'Транзакций {row["type"]}'] = row['count']
            stats[f'Сумма {row["type"]}'] = round(row['total_amount'] or 0, 2)

        payments_stats = pd.read_sql_query("""
            SELECT 
                status,
                COUNT(*) as count,
                SUM(amount) as total_amount
            FROM payments 
            GROUP BY status
        """, conn)

        for _, row in payments_stats.iterrows():
            stats[f'Платежей {row["status"]}'] = row['count']
            stats[f'Сумма платежей {row["status"]}'] = round(row['total_amount'] or 0, 2)

        top_users = pd.read_sql_query("""
            SELECT username, balance 
            FROM users 
            WHERE balance > 0 
            ORDER BY balance DESC 
            LIMIT 5
        """, conn)

        for i, (_, row) in enumerate(top_users.iterrows(), 1):
            stats[f'Топ {i} ({row["username"]})'] = round(row['balance'], 2)

        stats['Дата экспорта'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    except Exception as e:
        logger.error(f"Ошибка генерации статистики: {e}")
        stats['Ошибка статистики'] = str(e)

    return stats



def cleanup_old_exports(max_files=5):
    try:
        temp_dir = "temp_exports"
        if not os.path.exists(temp_dir):
            return

        export_files = [f for f in os.listdir(temp_dir) if f.startswith('bot_database_export_') and f.endswith('.xlsx')]

        if len(export_files) > max_files:
            export_files.sort(key=lambda x: os.path.getctime(os.path.join(temp_dir, x)))

            for old_file in export_files[:-max_files]:
                file_path = os.path.join(temp_dir, old_file)
                os.remove(file_path)
                logger.info(f"🗑️ Удален старый файл экспорта: {old_file}")

        if not os.listdir(temp_dir):
            os.rmdir(temp_dir)
            logger.info("🗑️ Удалена пустая временная папка экспортов")

    except Exception as e:
        logger.error(f"Ошибка очистки старых файлов экспорта: {e}")


def cleanup_all_temp_exports():
    try:
        temp_dir = "temp_exports"
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"🗑️ Удален временный файл: {file}")

            os.rmdir(temp_dir)
            logger.info("✅ Все временные файлы экспорта удалены")

    except Exception as e:
        logger.error(f"Ошибка принудительной очистки временных файлов: {e}")