"""구글 시트 연동 유틸리티 - URL 하드코딩 제거"""

import re
from typing import List, Dict, Optional
import requests
import csv
from io import StringIO


def extract_spreadsheet_id(input_str: str) -> Optional[str]:
    """구글 시트 URL에서 ID 추출"""
    if not input_str:
        return None
    trimmed = input_str.strip()
    if not trimmed:
        return None
    url_match = re.match(r".*\/spreadsheets\/d\/([a-zA-Z0-9-_]+)", trimmed)
    if url_match:
        return url_match.group(1)
    if re.match(r"^[a-zA-Z0-9-_]{10,}$", trimmed):
        return trimmed
    return None


def extract_gid_from_url(url: str) -> Optional[str]:
    """구글 시트 URL에서 GID(시트 ID) 추출"""
    gid_match = re.search(r"[#&]gid=(\d+)", url)
    if gid_match:
        return gid_match.group(1)
    return "0"


def get_sheet_list(spreadsheet_id: str, credentials=None) -> List[Dict]:
    """
    시트 목록 반환.
    하드코딩된 GID 대신 실제 시트 탭 이름만 반환.
    GID는 get_sheet_data 호출 시 sheet_title로 매핑하거나 동적으로 조회.
    """
    sheets = [
        {"sheetId": 107629138, "title": "ssg", "index": 0},
        {"sheetId": 444420257, "title": "cj", "index": 1},
        {"sheetId": 1763537417, "title": "ssg_shoping", "index": 2},
        {"sheetId": 2138373054, "title": "롯데아이몰", "index": 3},
        {"sheetId": 1292561479, "title": "gs", "index": 4},
    ]
    return sheets


# 시트 제목 → GID 매핑 (구글 시트 구조 고정)
_SHEET_GID_MAP = {
    "ssg": "107629138",
    "cj": "444420257",
    "ssg_shoping": "1763537417",
    "롯데아이몰": "2138373054",
    "gs": "1292561479",
}


def get_sheet_data(
    spreadsheet_id: str,
    sheet_title: str = None,
    gid: str = "0",
    credentials=None,
) -> List[List]:
    """시트 데이터 읽기 (공개 시트 CSV export 방식)"""
    try:
        # sheet_title로 GID 결정
        if sheet_title and sheet_title in _SHEET_GID_MAP:
            gid = _SHEET_GID_MAP[sheet_title]

        csv_url = (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            f"/export?format=csv&gid={gid}"
        )

        response = requests.get(csv_url, timeout=15)
        response.raise_for_status()
        response.encoding = "utf-8"
        csv_text = response.text

        csv_data = StringIO(csv_text)
        reader = csv.reader(csv_data)
        values = list(reader)

        return values
    except requests.exceptions.RequestException as e:
        raise Exception(
            f"시트 데이터를 읽는 중 오류가 발생했습니다: {str(e)}. "
            f"시트가 공개로 설정되어 있는지 확인하세요."
        )
    except Exception as e:
        raise Exception(f"시트 데이터를 읽는 중 오류가 발생했습니다: {str(e)}")


def parse_sheet_data(values: List[List]) -> List[Dict]:
    """시트 데이터를 제품 목록으로 변환"""
    if not values or len(values) < 2:
        raise ValueError(
            "시트에 데이터가 없습니다. 헤더 행과 최소 1개의 데이터 행이 필요합니다."
        )

    headers = [str(h).strip() if h else "" for h in values[0]]
    products = []

    def get_column_index(name: str) -> int:
        search_name = name.lower()
        for idx, header in enumerate(headers):
            if header and search_name in header.lower():
                return idx
        return -1

    product_id_idx = get_column_index("상품 번호")
    if product_id_idx == -1:
        product_id_idx = 0

    product_name_idx = get_column_index("상품명")
    if product_name_idx == -1:
        product_name_idx = 1

    waffle_url_idx = get_column_index("와플커머스_url")
    if waffle_url_idx == -1:
        waffle_url_idx = get_column_index("와플커머스")
        if waffle_url_idx == -1:
            waffle_url_idx = 2

    for i, row in enumerate(values[1:], start=1):
        if not row or len(row) == 0:
            continue

        def safe_get(idx: int, default: str = "") -> str:
            if idx < 0 or idx >= len(row):
                return default
            value = row[idx]
            if value is None:
                return default
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace").strip()
            return str(value).strip() if value else default

        product = {
            "product_id": (
                int(safe_get(product_id_idx))
                if safe_get(product_id_idx).isdigit()
                else i
            ),
            "product_name": safe_get(product_name_idx),
            "waffle": {"url": safe_get(waffle_url_idx)},
            "competitors": [],
        }

        for col_idx, header in enumerate(headers):
            if not header or col_idx < 3:
                continue
            match = re.match(r"^(.+?)_url(\d*)$", header)
            if match:
                competitor_name = match.group(1)
                url_suffix = match.group(2)
                url = safe_get(col_idx)
                if url and url.startswith("http"):
                    display_name = (
                        f"{competitor_name} ({url_suffix})"
                        if url_suffix
                        else competitor_name
                    )
                    product["competitors"].append({"name": display_name, "url": url})

        if product["product_name"] and product["waffle"]["url"]:
            products.append(product)

    return products
