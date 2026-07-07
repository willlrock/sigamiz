import os
import sqlite3
from datetime import datetime, timedelta


DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")


TEST_LISTINGS = [
    ("test_listing_01", "TATU", "Yunusobod", "Kvartira", 3, 41.3406, 69.2868, 900000, 2, 1, 0, 1, 1, 1, "TATU yonida, metroga yaqin 3 xonali kvartira."),
    ("test_listing_02", "WIUT", "Chilonzor", "Kvartira", 2, 41.2856, 69.2034, 750000, 1, 1, 1, 1, 0, 1, "Chilonzor metro atrofida sokin xona."),
    ("test_listing_03", "INHA", "Mirzo-Ulug'bek", "Xonadonli uy", 2, 41.3381, 69.3362, 1100000, 1, 1, 1, 1, 1, 0, "INHA tomonda hovlili uy, xo'jayinsiz."),
    ("test_listing_04", "TMI", "Mirobod", "Kvartira", 1, 41.3182, 69.2476, 650000, 1, 1, 0, 0, 0, 1, "Mirobod markazida bitta joy."),
    ("test_listing_05", "TDIU", "Yakkasaroy", "Kvartira", 3, 41.2940, 69.2550, 1250000, 2, 1, 1, 1, 1, 0, "Yakkasaroyda yangi remont, konditsioner bor."),
    ("test_listing_06", "O'zMU", "Olmazor", "Yotoqxona", 4, 41.3515, 69.2064, 500000, 3, 1, 0, 1, 0, 1, "O'zMUga yaqin arzon variant."),
    ("test_listing_07", "TSUULL", "Shayxontohur", "Kvartira", 2, 41.3260, 69.2420, 850000, 1, 0, 1, 1, 1, 0, "Shayxontohurda talaba qizlar uchun joy."),
    ("test_listing_08", "TTA", "Yashnobod", "Kvartira", 2, 41.2960, 69.3700, 700000, 2, 1, 0, 0, 1, 0, "Yashnobodda TTAga borish qulay."),
    ("test_listing_09", "Other", "Uchtepa", "Xonadonli uy", 3, 41.3030, 69.1660, 600000, 2, 0, 0, 1, 1, 0, "Uchtepada hovlili uy, tinch mahalla."),
    ("test_listing_10", "Other", "Sergeli", "Kvartira", 2, 41.2260, 69.2200, 550000, 1, 1, 1, 0, 0, 0, "Sergelida byudjet variant, avtobus bekatiga yaqin."),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    expires_at = datetime.now() + timedelta(days=14)

    cursor.execute("DELETE FROM listings WHERE telegram_username LIKE 'test_listing_%'")

    for index, item in enumerate(TEST_LISTINGS, start=1):
        (
            username,
            university,
            district,
            housing_type,
            room_count,
            lat,
            lng,
            price,
            people_needed,
            has_wifi,
            has_ac,
            has_washing_machine,
            no_landlord_in_yard,
            near_metro,
            description,
        ) = item
        cursor.execute(
            """
            INSERT INTO listings (
                telegram_user_id, telegram_username, listing_type, university, district, housing_type,
                description, phone_number, room_count, author_gender, preferred_gender,
                lat, lng, price_per_person, people_needed,
                has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro,
                status, expires_at
            )
            VALUES (?, ?, 'offer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                9_100_000 + index,
                username,
                university,
                district,
                housing_type,
                description,
                f"+99890000{index:04d}",
                room_count,
                "male" if index % 2 else "female",
                "any",
                lat,
                lng,
                price,
                people_needed,
                has_wifi,
                has_ac,
                has_washing_machine,
                no_landlord_in_yard,
                near_metro,
                expires_at,
            ),
        )

    conn.commit()
    conn.close()
    print(f"Seeded {len(TEST_LISTINGS)} test listings.")


if __name__ == "__main__":
    seed()
