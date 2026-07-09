from datetime import datetime, timedelta

try:
    from db import get_db
except ModuleNotFoundError:
    from backend.db import get_db


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
    ("test_listing_11", "TATU", "Olmazor", "Kvartira", 2, 41.3480, 69.2140, 820000, 1, 1, 0, 1, 0, 1, "Olmazorda TATUga qatnash uchun qulay, metro yaqin."),
    ("test_listing_12", "TSUL", "Shayxontohur", "Kvartira", 3, 41.3220, 69.2450, 980000, 2, 1, 1, 1, 1, 0, "Shayxontohur markazida toza kvartira, talabalar uchun."),
    ("test_listing_13", "TDIU", "Mirobod", "Kvartira", 2, 41.3035, 69.2855, 1150000, 1, 1, 1, 1, 0, 1, "Mirobodda biznes markazlarga yaqin, sharoiti yaxshi."),
    ("test_listing_14", "MDIS", "Yakkasaroy", "Xonadonli uy", 3, 41.2790, 69.2600, 780000, 2, 0, 1, 1, 1, 0, "Yakkasaroyda hovlili uy, egasi boshqa joyda yashaydi."),
    ("test_listing_15", "TTA", "Mirzo-Ulug'bek", "Kvartira", 1, 41.3230, 69.3345, 690000, 1, 1, 0, 0, 0, 1, "Mirzo-Ulug'bekda ixcham xona, avtobus bekati yonida."),
    ("test_listing_16", "O'zMU", "Olmazor", "Yotoqxona", 4, 41.3560, 69.2100, 450000, 3, 1, 0, 1, 0, 0, "O'zMUga yaqin yotoqxona uslubidagi arzon joy."),
    ("test_listing_17", "WIUT", "Chilonzor", "Kvartira", 3, 41.2765, 69.2055, 1000000, 2, 1, 1, 1, 1, 1, "Chilonzorda metroga 7 daqiqa, yangi remont."),
    ("test_listing_18", "INHA", "Yunusobod", "Kvartira", 2, 41.3620, 69.2905, 1250000, 1, 1, 1, 1, 0, 1, "Yunusobodda INHA tomonga qatnash oson, xona keng."),
    ("test_listing_19", "Other", "Bektemir", "Xonadonli uy", 3, 41.2110, 69.3370, 500000, 2, 0, 0, 1, 1, 0, "Bektemirda sokin hovli, byudjet variant."),
    ("test_listing_20", "TMI", "Sergeli", "Kvartira", 2, 41.2320, 69.2180, 620000, 1, 1, 0, 1, 0, 0, "Sergelida yangi uy, avtobus va do'konlar yaqin."),
    ("test_listing_21", "TSUULL", "Uchtepa", "Kvartira", 3, 41.2990, 69.1740, 720000, 2, 1, 1, 0, 1, 0, "Uchtepada talaba qizlar uchun tartibli kvartira."),
    ("test_listing_22", "TATU", "Yashnobod", "Kvartira", 2, 41.2920, 69.3600, 870000, 1, 1, 1, 1, 0, 1, "Yashnobodda internet va konditsioner bor, metro tomonga qulay."),
    ("test_listing_23", "TTA", "Mirobod", "Kvartira", 4, 41.2925, 69.2920, 1350000, 3, 1, 1, 1, 1, 1, "Mirobodda katta kvartira, 3 ta joy bo'sh."),
    ("test_listing_24", "MDIS", "Yakkasaroy", "Kvartira", 2, 41.2875, 69.2580, 950000, 1, 1, 0, 1, 0, 1, "Yakkasaroyda MDISga yaqin, toza va yorug' xona."),
    ("test_listing_25", "Other", "Yunusobod", "Xonadonli uy", 3, 41.3710, 69.2810, 760000, 2, 0, 1, 1, 1, 0, "Yunusobodda hovlili uy, tinch mahalla va do'konlar yaqin."),
]


def seed():
    conn = get_db()
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
