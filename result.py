import requests
from bs4 import BeautifulSoup
from fields import OUTPUT_KEYS
from datetime import datetime
import argparse
import re

# --- UI Mapping: Japanese label -> output key ---
UI_MAPPING = {
    "物件名": "building_name_ja",
    "種別": "building_type",
    "建物構造": "structure",
    "所在地": "address",
    "築年月": "year",
    "部屋番号": "unit_no",
    "所在階/階建": "floor_no/floors",
    "間取り（タイプ）": "room_type",
    "専有面積": "size",
    "方位": "facing",
    "賃料": "monthly_rent",
    "管理費・共益費": "monthly_maintenance",
    "敷金/保証金": "deposit/security_deposit",
    "礼金/償却・敷引": "key_money/amortization",
    "更新料": "months_renewal",
    "保険料": "fire_insurance",
    "フリーレント": "discount",
    "入居可能日": "available_from",
    "退去時費用": "other_initial_fees",
    "ペット可区分": "pets",
    "備考": "property_notes",
    "設備・条件": "features",
}

# --- Feature mapping (Japanese -> English key) ---
FEATURES_MAPPING = {
    "壁掛けｴｱｺﾝ1台": "aircon",
    "エアコン暖房付き": "aircon_heater",
    "オール電化": "all_electric",
    "自動お湯張り": "auto_fill_bath",
    "バルコニー": "balcony",
    "浴室": "bath",
    "浴室乾燥機能": "bath_water_heater",
    "ブラインド": "blinds",
    "BS対応可": "bs",
    "ケーブルテレビ": "cable",
    "カーペット": "carpet",
    "清掃サービス": "cleaning_service",
    "カウンターキッチン": "counter_kitchen",
    "食器洗浄機": "dishwasher",
    "カーテン": "drapes",
    "女性専用": "female_only",
    "暖炉": "fireplace",
    "フローリング": "flooring",
    "フルキッチン": "full_kitchen",
    "家具付き": "furnished",
    "ガス": "gas",
    "IHクッキングヒーター": "induction_cooker",
    "インターネット無料": "internet_broadband",
    "Wi-Fi": "internet_wifi",
    "温水洗浄便座": "japanese_toilet",
    "リネン": "linen",
    "ロフト": "loft",
    "電子レンジ": "microwave",
    "オーブン": "oven",
    "電話回線": "phoneline",
    "コンロ": "range",
    "冷蔵庫": "refrigerator",
    "冷蔵庫/冷凍庫": "refrigerator_freezer",
    "屋上バルコニー": "roof_balcony",
    "トイレ別": "separate_toilet",
    "シャワー": "shower",
    "SOHO可": "soho",
    "収納": "storage",
    "学生向け": "student_friendly",
    "システムキッチン": "system_kitchen",
    "畳": "tatami",
    "床暖房": "underfloor_heating",
    "ユニットバス": "unit_bath",
    "調理器具付き": "utensils_cutlery",
    "ベランダ": "veranda",
    "洗濯機/乾燥機": "washer_dryer",
    "洗濯機置場": "washing_machine",
    "ウォシュレット": "washlet",
    "洋式トイレ": "western_toilet",
}

# --- Facing direction mapping ---
JP_TO_EN_FACING = {
    "北": "facing_north",
    "北東": "facing_northeast",
    "東": "facing_east",
    "南東": "facing_southeast",
    "南": "facing_south",
    "南西": "facing_southwest",
    "西": "facing_west",
    "北西": "facing_northwest",
}

# --- Default features always marked "Y" ---
DEFAULT_FEATURES = [
    "aircon", "aircon_heater", "bs", "internet_broadband", "phoneline",
    "flooring", "system_kitchen", "bath", "shower", "unit_bath",
    "western_toilet", "credit_card",
]

# --- Helper functions ---
def get_value_by_label(soup, label: str):
    """Find value in <dt>/<dd> or <th>/<td> by Japanese label"""
    dt = soup.find(lambda tag: tag.name == "dt" and label in tag.get_text(strip=True))
    if dt and dt.find_next_sibling("dd"):
        return dt.find_next_sibling("dd").get_text(strip=True)
    th = soup.find(lambda tag: tag.name == "th" and label in tag.get_text(strip=True))
    if th and th.find_next_sibling("td"):
        return th.find_next_sibling("td").get_text(strip=True)
    return None

def parse_japanese_address(address):
    """Split Japanese address into prefecture, city, district, chome/banchi"""
    prefecture_match = re.match(r"^(.*?[都道府県])", address)
    prefecture = prefecture_match.group(1) if prefecture_match else None

    remaining = address[len(prefecture):] if prefecture else address

    city_match = re.match(r"^(.*?[市区町村])", remaining)
    city = city_match.group(1) if city_match else None

    remaining = remaining[len(city):] if city else remaining

    district_match = re.match(r"^([^\d]+)", remaining)
    district = district_match.group(1) if district_match else None

    chome_banchi = remaining[len(district):] if district else remaining
    return prefecture, city, district, chome_banchi

def parse_images(soup, data, max_images=16):
    """Extract up to max_images images with category + URL"""
    images = soup.select("img")
    count = 0
    for img in images:
        if count >= max_images:
            break
        url = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not url:
            continue
        if url.startswith("/"):
            url = "https://rent.tokyu-housing-lease.co.jp" + url
        category = img.get("alt") or "None"
        count += 1
        data[f"image_category_{count}"] = category
        data[f"image_url_{count}"] = url
    # Fill remaining slots with None
    for i in range(count + 1, max_images + 1):
        data[f"image_category_{i}"] = None
        data[f"image_url_{i}"] = None

def parse_property(url):
    """Main parsing function"""
    resp = requests.get(url)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    data = {key: None for key in OUTPUT_KEYS}
    data["link"] = url
    data["create_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Parse UI fields
    for jp_label, output_key in UI_MAPPING.items():
        value = get_value_by_label(soup, jp_label)
        if not value:
            continue

        # Special handling by field type
        if output_key == "address":
            prefecture, city, district, chome_banchi = parse_japanese_address(value)
            data.update({"prefecture": prefecture, "city": city, "district": district, "chome_banchi": chome_banchi})
            continue
        if output_key == "facing":
            for k in JP_TO_EN_FACING.values():
                data[k] = "N"
            key_name = JP_TO_EN_FACING.get(value.strip())
            if key_name:
                data[key_name] = "Y"
            continue
        if output_key == "features":
            features_list = [f.strip() for f in value.split("、")]
            for jp_feature, key in FEATURES_MAPPING.items():
                data[key] = "Y" if jp_feature in features_list else "N"
            for key in DEFAULT_FEATURES:
                data[key] = "Y"
            continue
        if output_key == "floor_no/floors":
            parts = value.split("/")
            data["floor_no"] = parts[0].strip() if len(parts) > 0 else None
            data["floors"] = parts[1].strip() if len(parts) > 1 else None
            continue
        if output_key == "deposit/security_deposit":
            parts = value.split("/")
            if len(parts) == 2:
                data["months_security_deposit"] = "0" if parts[0].strip() == "-" else parts[0].strip()
                data["numeric_security_deposit"] = "0" if parts[1].strip() == "-" else parts[1].strip()
            continue
        if output_key == "key_money/amortization":
            parts = value.split("/")
            if len(parts) == 2:
                data["months_key"] = "0" if parts[0].strip() == "-" else parts[0].strip()
                data["numeric_key"] = "0" if parts[1].strip() == "-" else parts[1].strip()
            continue
        if output_key == "monthly_rent":
            if "〜" in value:
                value = value.split("〜")[0].strip()
            data["monthly_rent"] = value
            continue

        # Default case
        data[output_key] = value

    # --- Calculate rent & fees ---
    rent = 0
    monthly_rent = data.get("monthly_rent")
    if monthly_rent and monthly_rent != "-":
        try:
            rent_str = monthly_rent.split("〜")[0].replace("万円", "").replace(",", "").strip()
            rent = float(rent_str) * 10000
        except ValueError:
            rent = 0

    if not data.get("months_guarantor"):
        data["months_guarantor"] = round(rent * 0.5, 0)
    if not data.get("numeric_guarantor"):
        data["numeric_guarantor"] = round(rent * 1.0, 0)
    if not data.get("months_agency"):
        data["months_agency"] = round(rent * 1.1, 0)

    # --- Images ---
    parse_images(soup, data)

    return data

# --- CLI Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl property data")
    parser.add_argument("--url", type=str, required=True, help="Property listing URL")
    args = parser.parse_args()

    result = parse_property(args.url)
    for key, val in result.items():
        print(f"{key} : {val}")
