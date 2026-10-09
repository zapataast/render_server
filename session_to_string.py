from telethon.sessions import SQLiteSession, StringSession

SESSION_FILE = "for_versel.session"

session = SQLiteSession(SESSION_FILE)

session_string = StringSession.save(session)

print("\n===== TELEGRAM SESSION STRING =====\n")
print(session_string)
print("\n===================================\n")