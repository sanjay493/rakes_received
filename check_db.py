import sqlite3

db_file = "rake_data.db"

try:
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rakes'")
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        print("→ Table 'rakes' does NOT exist in the database yet.")
    else:
        cursor.execute("SELECT COUNT(*) FROM rakes")
        count = cursor.fetchone()[0]
        print(f"→ Total records in 'rakes' table: {count}")

        # Optional extra info
        cursor.execute("SELECT MIN(received_time), MAX(received_time) FROM rakes")
        min_max = cursor.fetchone()
        print(f"Date range: {min_max[0]}  →  {min_max[1]}")

        cursor.execute("SELECT sttn_to, COUNT(*) FROM rakes GROUP BY sttn_to ORDER BY COUNT(*) DESC")
        print("\nRecords per destination:")
        for dest, cnt in cursor.fetchall():
            print(f"  {dest:>6} : {cnt:>5}")

    conn.close()

except sqlite3.Error as e:
    print("Database error:", e)
