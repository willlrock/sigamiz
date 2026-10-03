"""The same search contract powers API queries, the bot and notifications."""
import json
from backend.catalogs import AMENITIES, DISTRICTS, HOUSING_TYPES, UNIVERSITIES
from backend.listing_service import ListingServiceError, parse_int_field, bool_from_payload

AMENITY_COLUMNS = tuple(column for _, _, column in AMENITIES)


def normalize_filters(payload):
    payload = dict(payload)
    districts = payload.get("districts") or ([payload["district"]] if payload.get("district") else [])
    if isinstance(districts, str):
        try:
            districts = json.loads(districts)
        except ValueError:
            districts = [districts]
    if not isinstance(districts, list) or any(d not in DISTRICTS for d in districts):
        raise ListingServiceError("Tuman noto'g'ri tanlangan")
    result = {"districts": districts}
    for key in ("price_min", "price_max", "room_count"):
        result[key] = parse_int_field(payload, key, minimum=0 if key.startswith("price") else 1, maximum=100_000_000 if key.startswith("price") else 20, required=False)
    if result["price_min"] is not None and result["price_max"] is not None and result["price_min"] > result["price_max"]:
        raise ListingServiceError("Minimal narx maksimal narxdan katta")
    for key, choices in (("housing_type", HOUSING_TYPES), ("university", UNIVERSITIES), ("seeker_gender", ("male", "female", "any")), ("preferred_gender", ("male", "female", "any"))):
        value = payload.get(key) or None
        if value is not None and value not in choices:
            raise ListingServiceError(f"{key}: noto'g'ri qiymat")
        result[key] = value
    for column in AMENITY_COLUMNS:
        result[column] = bool_from_payload(payload, column)
    return result


def search_clause(filters, prefix="listings."):
    f = normalize_filters(filters)
    clauses = [f"{prefix}status = 'active'", f"datetime({prefix}expires_at) > datetime('now')", f"{prefix}listing_type = 'offer'"]
    params = []
    for key, operator in (("price_min", ">="), ("price_max", "<=")):
        if f[key] is not None:
            clauses.append(f"{prefix}price_per_person {operator} ?")
            params.append(f[key])
    if f["districts"]:
        clauses.append(f"{prefix}district IN ({','.join('?' for _ in f['districts'])})")
        params.extend(f["districts"])
    for key in ("housing_type", "room_count", "university"):
        if f[key] is not None:
            clauses.append(f"{prefix}{key} = ?")
            params.append(f[key])
    if f["preferred_gender"] and f["preferred_gender"] != "any":
        clauses.append(f"{prefix}author_gender = ?")
        params.append(f["preferred_gender"])
    if f["seeker_gender"] and f["seeker_gender"] != "any":
        clauses.append(f"({prefix}preferred_gender = ? OR {prefix}preferred_gender = 'any')")
        params.append(f["seeker_gender"])
    for column in AMENITY_COLUMNS:
        if f[column]:
            clauses.append(f"{prefix}{column} = 1")
    return " AND ".join(clauses), params


def save_preferences(cursor, user_id, payload):
    filters = normalize_filters(payload)
    filters["districts"] = json.dumps(filters["districts"], ensure_ascii=False)
    columns = list(filters)
    cursor.execute(f"INSERT INTO search_preferences (telegram_user_id, {','.join(columns)}, updated_at) VALUES (?, {','.join('?' for _ in columns)}, datetime('now')) ON CONFLICT(telegram_user_id) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in columns) + ",updated_at=excluded.updated_at", [user_id, *filters.values()])
    return filters


def bot_filters(data):
    return {"price_min": data.get("s_price_min"), "price_max": data.get("s_price_max"), "districts": [data["s_district"]] if data.get("s_district") else [], "seeker_gender": data.get("s_gender"), "preferred_gender": data.get("s_preferred_gender"), **{col: key in data.get("s_amenities", []) for key, _, col in AMENITIES}}
