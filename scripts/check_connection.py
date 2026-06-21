from db import connect


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select current_database(), current_user, version();")
            database, user, version = cur.fetchone()
            print(f"Connected to database: {database}")
            print(f"Connected as user: {user}")
            print(version.splitlines()[0])


if __name__ == "__main__":
    main()
