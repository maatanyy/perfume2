"""크롤러 베이스 클래스"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import requests
from datetime import datetime
import time


# 품절 감지 키워드 (본문 텍스트용)
SOLD_OUT_KEYWORDS = [
    "품절", "일시품절", "매진", "판매종료", "판매 종료",
    "sold out", "soldout", "재고없음", "재고 없음", "구매불가", "구매 불가",
]

# 범용 품절 선택자 (키워드 텍스트 동반 시에만 품절 판정)
GENERIC_SOLD_OUT_SELECTORS = [
    "[class*='soldout']",
    "[class*='sold_out']",
    "[class*='sold-out']",
]


class BaseCrawler(ABC):
    """크롤러 베이스 클래스"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0",
            }
        )

    @staticmethod
    def parse_price(text) -> Optional[int]:
        """텍스트에서 가격(int) 추출. 100 이하(%, 개수 등 오탐)는 None."""
        import re as _re
        digits = _re.sub(r"[^\d]", "", text or "")
        if not digits:
            return None
        price = int(digits)
        return price if price > 100 else None

    @staticmethod
    def select_first_price(soup, selectors: List[str]) -> Optional[int]:
        """선택자 목록을 순서대로 시도해 첫 유효 가격 반환."""
        for selector in selectors:
            try:
                elems = soup.select(selector)
            except Exception:
                continue
            for elem in elems:
                price = BaseCrawler.parse_price(elem.get_text())
                if price is not None:
                    return price
        return None

    def build_price_result(
        self,
        url: str,
        sale_price: Optional[int] = None,
        coupon_price: Optional[int] = None,
        delivery_price: Optional[int] = 0,
        delivery_status: str = "무료",
        status: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict:
        """표준 결과 dict 생성. 대표가(상품 가격) = 쿠폰적용가 우선."""
        if (
            sale_price is not None
            and coupon_price is not None
            and coupon_price >= sale_price
        ):
            coupon_price = None  # 쿠폰가가 판매가보다 싸지 않으면 쿠폰 없음
        representative = coupon_price if coupon_price is not None else sale_price
        if status is None:
            status = "success" if representative is not None else "not_found"
        total = None
        if representative is not None:
            total = representative + (delivery_price or 0)
        result = {
            "상품 url": url,
            "판매가": sale_price,
            "쿠폰적용가": coupon_price,
            "상품 가격": representative,
            "배송비": delivery_price,
            "배송비 여부": delivery_status,
            "최종 가격": total,
            "결과 상태": status,
            "추출 날짜": datetime.now().isoformat(),
        }
        if error:
            result["에러 발생"] = error
        return result

    def get_sold_out_selectors(self) -> List[str]:
        """사이트별 품절 표시 선택자 (서브클래스 오버라이드)."""
        return []

    def detect_sold_out(self, soup) -> bool:
        """본문에서 품절 표시 감지.
        사이트별 선택자는 요소 존재만으로, 범용 선택자는 키워드 텍스트까지 확인."""
        for selector in self.get_sold_out_selectors():
            try:
                if soup.select_one(selector):
                    return True
            except Exception:
                continue
        for selector in GENERIC_SOLD_OUT_SELECTORS:
            try:
                elems = soup.select(selector)
            except Exception:
                continue
            for elem in elems:
                text = elem.get_text(strip=True).lower()
                if any(kw in text for kw in SOLD_OUT_KEYWORDS):
                    return True
        return False

    def fetch_page(self, url: str) -> Optional[str]:
        """HTTP로 페이지 가져오기 (브라우저가 필요한 사이트는 서브클래스에서 오버라이드)"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"페이지 로드 실패: {e}")
            return None

    @abstractmethod
    def extract_price(self, html: str, url: str) -> Dict:
        """가격 정보 추출 (서브클래스에서 구현)"""
        pass

    def crawl_price(self, url: str, max_retries: int = 2) -> Dict:
        """가격 크롤링 (재시도 로직 포함)"""
        for attempt in range(1, max_retries + 1):
            try:
                html = self.fetch_page(url)

                if not html:
                    raise Exception("페이지를 가져올 수 없습니다.")

                if len(html) < 2000:
                    print(f"[WARNING] Attempt {attempt}: HTML too short ({len(html)} bytes), retrying...")
                    if attempt < max_retries:
                        time.sleep(3 * attempt)
                        continue

                result = self.extract_price(html, url)

                if result.get("상품 가격") is None:
                    # 가격을 못 찾았어도 결과 반환 (not_found 상태로 처리됨)
                    print(f"[WARNING] 가격 추출 실패 - 재시도 없이 진행")
                return result

            except Exception as e:
                error_msg = str(e)
                print(f"[ERROR] Attempt {attempt} failed: {error_msg}")

                skip_keywords = [
                    "매진", "품절", "판매종료", "판매 종료", "sold out",
                    "재고없음", "재고 없음", "구매불가", "구매 불가",
                    "삭제된 상품", "존재하지 않는",
                ]
                if any(kw in error_msg.lower() for kw in skip_keywords):
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="매진/품절",
                        status="sold_out", error=error_msg,
                    )

                if attempt == max_retries:
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="크롤링 실패",
                        status="error", error=error_msg,
                    )
                time.sleep(2 * attempt)

        return self.build_price_result(
            url, delivery_price=None, delivery_status="모든 재시도 실패",
            status="error",
        )
