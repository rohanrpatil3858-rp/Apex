import sqlite3

def read_sqlite_db(db_path:str):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    if not tables:
        print("No tables found in the database.")
        return

    # Loop through each table and print its data
    for table in tables:
        table_name = table[0]
        print(f"\n===== TABLE: {table_name} =====")

        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()

        if not rows:
            print("No data in this table.")
            continue

        # Print column names
        column_names = [description[0] for description in cursor.description]
        print(" | ".join(column_names))

        # Print rows
        for row in rows:
            print(row)

    # Close connection
    conn.close()


read_sqlite_db("data\database_sources\internal_hr.sqlite")
