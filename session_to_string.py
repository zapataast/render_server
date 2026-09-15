from telethon.sessions import SQLiteSession, StringSession

SESSION_FILE = "telegram_session_new.session"

session = SQLiteSession(SESSION_FILE)

session_string = StringSession.save(session)

print("\n===== TELEGRAM SESSION STRING =====\n")
print(session_string)
print("\n===================================\n")