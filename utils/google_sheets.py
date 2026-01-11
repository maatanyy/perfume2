"""구글 시트 연동 유틸리티"""

import re
from typing import List, Dict, Optional
import requests
import csv
from io import StringIO
from bs4 import BeautifulSoup


def extract_spreadsheet_id(input_str: str) -> Optional[str]:
    """구글 시트 URL에서 ID 추출"""
    if not input_str:
        return None

    trimmed = input_str.strip()
    if not trimmed:
        return None

    # URL 형식에서 ID 추출
    url_match = re.match(r".*\/spreadsheets\/d\/([a-zA-Z0-9-_]+)", trimmed)
    if url_match:
        return url_match.group(1)

    # 이미 ID 형식인 경우
    if re.match(r"^[a-zA-Z0-9-_]{10,}$", trimmed):
        return trimmed

    return None


def extract_gid_from_url(url: str) -> Optional[str]:
    """구글 시트 URL에서 GID(시트 ID) 추출"""
    gid_match = re.search(r"[#&]gid=(\d+)", url)
    if gid_match:
        return gid_match.group(1)
    return "0"  # 기본 시트


def get_sheet_list(
    spreadsheet_id: str, credentials: Optional[any] = None
) -> List[Dict]:
    """시트 목록 가져오기 (하드코딩된 시트 목록 사용)"""
    # 고정된 시트 목록 (실제 구글 시트의 탭 이름들과 gid)
    sheets = [
        {"sheetId": 107629138, "title": "ssg", "index": 0},
        {"sheetId": 444420257, "title": "cj", "index": 1},
        {"sheetId": 1763537417, "title": "ssg_shoping", "index": 2},
        {"sheetId": 1137887352, "title": "롯데아이몰", "index": 3},
        {"sheetId": 859729329, "title": "gs", "index": 4},
    ]

    return sheets


def get_sheet_data(
    spreadsheet_id: str,
    sheet_title: str = None,
    gid: str = "0",
    credentials: Optional[any] = None,
) -> List[List]:
    """시트 데이터 읽기 (공개 시트의 경우 CSV export 사용)"""
    try:
        # sheet_title에서 올바른 gid 매핑
        sheet_gid_map = {
            "ssg": "107629138",
            "cj": "444420257",
            "ssg_shoping": "1763537417",
            "롯데아이몰": "1137887352",
            "gs": "859729329",
        }

        # sheet_title이 제공되면 매핑된 gid 사용
        if sheet_title and sheet_title in sheet_gid_map:
            gid = sheet_gid_map[sheet_title]

        # 공개 구글 시트를 CSV로 다운로드
        csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

        response = requests.get(csv_url, timeout=10)
        response.raise_for_status()

        # UTF-8로 명시적 디코딩
        response.encoding = "utf-8"
        csv_text = response.text

        # CSV 파싱
        csv_data = StringIO(csv_text)
        reader = csv.reader(csv_data)
        values = list(reader)

        return values
    except requests.exceptions.RequestException as e:
        raise Exception(
            f"시트 데이터를 읽는 중 오류가 발생했습니다: {str(e)}. 시트가 공개로 설정되어 있는지 확인하세요."
        )
    except Exception as e:
        raise Exception(f"시트 데이터를 읽는 중 오류가 발생했습니다: {str(e)}")


def parse_sheet_data(values: List[List]) -> List[Dict]:
    """시트 데이터를 제품 목록으로 변환 (기존 JS 로직 참고)"""
    if not values or len(values) < 2:
        raise ValueError(
            "시트에 데이터가 없습니다. 헤더 행과 최소 1개의 데이터 행이 필요합니다."
        )

    headers = [str(h).strip() if h else "" for h in values[0]]
    products = []

    def get_column_index(name: str) -> int:
        """헤더에서 컬럼 인덱스 찾기"""
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
            # UTF-8 문자열로 확실하게 변환
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

        # 경쟁사 URL 찾기 (헤더에서 "회사명_url" 또는 "회사명_url1" 패턴)
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
