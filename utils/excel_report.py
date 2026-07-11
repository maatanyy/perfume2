"""플랫 테이블 엑셀 리포트 생성

시트1 "전체 결과": 제품명|판매처|URL|판매가|쿠폰율|쿠폰적용가|배송비|최종가격|상태|비고
시트2 "가격 역전 항목": 동일 컬럼 + 가격차이 (경쟁사 최종가 < Waffle 최종가인 제품만)
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import xlsxwriter

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

HEADERS = ["제품명", "판매처", "URL", "판매가", "쿠폰율", "쿠폰적용가",
           "배송비", "최종가격", "상태", "비고"]
COL_WIDTHS = [38, 18, 50, 12, 8, 12, 10, 12, 10, 30]

STATUS_DISPLAY = {
    "success": "판매중",
    "sold_out": "품절",
    "not_found": "추출실패",
    "error": "오류",
}


def coupon_rate_display(sale_price, coupon_price) -> str:
    """쿠폰율 = (판매가-쿠폰적용가)/판매가. 계산 불가하면 '-'."""
    if (
        isinstance(sale_price, (int, float))
        and isinstance(coupon_price, (int, float))
        and sale_price > 0
        and coupon_price < sale_price
    ):
        return f"{round((sale_price - coupon_price) / sale_price * 100)}%"
    return "-"


def _seller_display(seller) -> str:
    if seller == "waffle":
        return "Waffle (우리회사)"
    return f"경쟁사 ({seller or 'N/A'})"


def _num_or_dash(value):
    return value if isinstance(value, (int, float)) else "-"


def _build_row(product_name: str, price: Dict) -> Dict:
    """가격 항목 1개 → 엑셀 1행 값 dict (status_key는 서식 선택용)."""
    status = price.get("결과 상태", "error")
    row = {
        "제품명": product_name,
        "판매처": _seller_display(price.get("seller")),
        "URL": str(price.get("상품 url", "") or ""),
        "상태": STATUS_DISPLAY.get(status, status),
        "비고": str(price.get("에러 발생", "") or "")[:100],
        "status_key": status,
    }
    if status == "success":
        sale = price.get("판매가")
        coupon = price.get("쿠폰적용가")
        row["판매가"] = _num_or_dash(sale)
        row["쿠폰율"] = coupon_rate_display(sale, coupon)
        row["쿠폰적용가"] = _num_or_dash(coupon)
        row["배송비"] = _num_or_dash(price.get("배송비"))
        row["최종가격"] = _num_or_dash(price.get("최종 가격"))
    elif status == "sold_out":
        row.update({"판매가": "품절", "쿠폰율": "-", "쿠폰적용가": "-",
                    "배송비": "-", "최종가격": "-"})
    else:  # not_found / error
        row.update({"판매가": "-", "쿠폰율": "-", "쿠폰적용가": "-",
                    "배송비": "-", "최종가격": "-"})
    return row


def _make_formats(workbook) -> Dict:
    return {
        "header": workbook.add_format({
            "bold": True, "bg_color": "#366092", "font_color": "white",
            "align": "center", "valign": "vcenter", "border": 1,
        }),
        "text": workbook.add_format({}),
        "num": workbook.add_format({"num_format": "#,##0"}),
        "sold_out": workbook.add_format({
            "bg_color": "#FFC7CE", "font_color": "#9C0006", "bold": True,
        }),
        "not_found": workbook.add_format({"font_color": "#FF8C00"}),
        "error": workbook.add_format({"font_color": "#CC0000"}),
        "diff": workbook.add_format({"bold": True, "font_color": "red"}),
    }


def _write_row(ws, row_idx: int, row: Dict, fmt: Dict):
    status = row["status_key"]
    if status == "sold_out":
        cell_fmt = num_fmt = fmt["sold_out"]
    elif status == "not_found":
        cell_fmt = num_fmt = fmt["not_found"]
    elif status == "error":
        cell_fmt = num_fmt = fmt["error"]
    else:
        cell_fmt, num_fmt = fmt["text"], fmt["num"]

    for col, key in enumerate(HEADERS):
        value = row.get(key, "-")
        if isinstance(value, (int, float)):
            ws.write_number(row_idx, col, value, num_fmt)
        else:
            ws.write(row_idx, col, value, cell_fmt)


def _write_flat_sheet(ws, results: List[Dict], fmt: Dict):
    for col, width in enumerate(COL_WIDTHS):
        ws.set_column(col, col, width)
    for col, header in enumerate(HEADERS):
        ws.write(0, col, header, fmt["header"])

    row_idx = 1
    for result in results:
        name = result.get("product_name", "N/A")
        for price in result.get("prices", []):
            _write_row(ws, row_idx, _build_row(name, price), fmt)
            row_idx += 1

    ws.freeze_panes(1, 0)
    if row_idx > 1:
        ws.autofilter(0, 0, row_idx - 1, len(HEADERS) - 1)


def _write_reversal_sheet(ws, results: List[Dict], fmt: Dict):
    headers = HEADERS + ["가격차이"]
    for col, width in enumerate(COL_WIDTHS + [14]):
        ws.set_column(col, col, width)
    for col, header in enumerate(headers):
        ws.write(0, col, header, fmt["header"])

    diff_col = len(headers) - 1
    row_idx = 1
    for result in results:
        prices = result.get("prices", [])
        waffle = next((p for p in prices if p.get("seller") == "waffle"), None)
        if not waffle or not isinstance(waffle.get("최종 가격"), (int, float)):
            continue
        waffle_total = waffle["최종 가격"]
        cheaper = [
            p for p in prices
            if p.get("seller") != "waffle"
            and isinstance(p.get("최종 가격"), (int, float))
            and p["최종 가격"] < waffle_total
        ]
        if not cheaper:
            continue

        name = result.get("product_name", "N/A")
        _write_row(ws, row_idx, _build_row(name, waffle), fmt)
        ws.write(row_idx, diff_col, "-", fmt["text"])
        row_idx += 1
        for p in cheaper:
            _write_row(ws, row_idx, _build_row(name, p), fmt)
            diff = int(waffle_total - p["최종 가격"])
            ws.write(row_idx, diff_col, f"-{diff}원 저렴", fmt["diff"])
            row_idx += 1

    if row_idx == 1:
        ws.write(1, 0, "가격 역전 항목이 없습니다.")
    else:
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, row_idx - 1, diff_col)


def save_results_excel(
    results: List[Dict], site_name: str, results_dir: str = "results"
) -> Optional[str]:
    """크롤링 결과를 플랫 테이블 엑셀로 저장. 실패 시 None."""
    try:
        os.makedirs(results_dir, exist_ok=True)
        timestamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(results_dir, f"{site_name}_가격조사_{timestamp}.xlsx")

        workbook = xlsxwriter.Workbook(filepath, {"strings_to_numbers": False})
        fmt = _make_formats(workbook)
        _write_flat_sheet(workbook.add_worksheet("전체 결과"), results, fmt)
        _write_reversal_sheet(workbook.add_worksheet("가격 역전 항목"), results, fmt)
        workbook.close()
        return filepath
    except Exception as e:
        logger.error(f"Excel 저장 실패: {e}")
        return None
