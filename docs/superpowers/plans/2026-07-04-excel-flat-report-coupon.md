# 가격조사 엑셀 개편 + 쿠폰가 크롤링 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 크롤러가 판매가/쿠폰적용가를 분리 수집하고 품절을 본문에서 감지하며, 엑셀 결과를 플랫 테이블(제품명|판매처|URL|판매가|쿠폰율|쿠폰적용가|배송비|최종가격|상태|비고)로 생성한다.

**Architecture:** `BaseCrawler`에 공통 헬퍼(가격 파싱, 결과 dict 빌더, 품절 감지)를 추가하고 사이트별 크롤러 5개가 판매가/쿠폰가 선택자를 분리 사용한다. 엑셀 생성은 `utils/excel_report.py` 신규 모듈로 분리하고 엔진의 `_save_results`가 위임한다. DB·웹 UI·SSE는 변경하지 않는다.

**Tech Stack:** Python 3.12 (venv: `perfume/`), Flask, BeautifulSoup(lxml), xlsxwriter, openpyxl(테스트 검증용), pytest(신규)

## Global Constraints

- **DB 무변경**: `models/`, `database.py`, `crawling.db` 스키마·데이터를 절대 건드리지 않는다. 마이그레이션 없음.
- **크롤러 반환 dict의 기존 키 유지**: `상품 url`, `상품 가격`, `배송비`, `배송비 여부`, `최종 가격`, `결과 상태`, `추출 날짜`, `에러 발생`. 신규 키: `판매가`, `쿠폰적용가`.
- **엑셀 시트1 컬럼 순서 고정**: `제품명 | 판매처 | URL | 판매가 | 쿠폰율 | 쿠폰적용가 | 배송비 | 최종가격 | 상태 | 비고`
- **상태 표시 문자열**: success→`판매중`, sold_out→`품절`, not_found→`추출실패`, error→`오류`
- 모든 파이썬 실행은 venv 사용: `perfume/bin/python`, 테스트는 `perfume/bin/python -m pytest tests/ -v`
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 추가

---

### Task 1: Git 저장소 초기화

프로젝트가 git 저장소가 아니므로 초기화한다. DB/venv/결과물은 커밋에서 제외한다.

**Files:**
- Create: `.gitignore`

**Interfaces:**
- Produces: git 저장소 (이후 모든 태스크가 커밋 가능)

- [ ] **Step 1: .gitignore 작성**

```gitignore
# 가상환경
perfume/

# 파이썬
__pycache__/
*.pyc

# 데이터베이스 (기존 사용자 데이터 - 절대 커밋 금지)
crawling.db
crawling.db-wal
crawling.db-shm

# 산출물/로그
results/
logs/

# 환경설정
.env

# macOS
.DS_Store

# 무관한 별도 프로젝트
0415_multitrust_new/
```

- [ ] **Step 2: git init 및 초기 커밋**

```bash
cd /Users/nohminsung/Desktop/perfume3
git init
git add .
git status   # crawling.db, perfume/, results/ 가 스테이징에 없는지 확인
git commit -m "chore: 프로젝트 초기 커밋 (엑셀 개편 작업 시작 전 스냅샷)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: `git status`에서 crawling.db가 untracked에도 나타나지 않음 (ignored).

---

### Task 2: pytest 도입 + BaseCrawler 공통 헬퍼

가격 텍스트 파싱, 선택자 목록에서 첫 가격 추출, 결과 dict 빌더, 품절 감지를 `BaseCrawler`에 추가한다. 기존 `crawl_price`의 sold_out/error 반환 dict도 새 빌더를 쓰도록 교체해 신규 키(`판매가`, `쿠폰적용가`)가 항상 존재하게 한다.

**Files:**
- Modify: `requirements.txt` (pytest 추가)
- Modify: `crawlers/base_crawler.py`
- Test: `tests/test_base_crawler.py` (신규, `tests/` 디렉토리도 신규)

**Interfaces:**
- Produces (이후 모든 크롤러 태스크가 사용):
  - `BaseCrawler.parse_price(text: str) -> Optional[int]` — 숫자만 추출, 100 이하·빈값은 None
  - `BaseCrawler.select_first_price(soup, selectors: List[str]) -> Optional[int]` — 선택자 순서대로 첫 유효 가격
  - `BaseCrawler.build_price_result(url, sale_price=None, coupon_price=None, delivery_price=0, delivery_status="무료", status=None, error=None) -> Dict` — 표준 결과 dict 생성. `상품 가격` = 쿠폰적용가 우선, `최종 가격` = 대표가+배송비, status 미지정 시 대표가 유무로 success/not_found 자동 결정. coupon_price >= sale_price면 coupon_price는 None 처리.
  - `BaseCrawler.get_sold_out_selectors() -> List[str]` — 서브클래스 오버라이드용 (기본 빈 리스트)
  - `BaseCrawler.detect_sold_out(soup) -> bool` — 사이트별 선택자는 존재만으로, 범용 선택자는 품절 키워드 텍스트까지 확인

- [ ] **Step 1: pytest 설치 및 requirements.txt 추가**

```bash
perfume/bin/pip install pytest==8.2.2
```

`requirements.txt` 맨 아래 `# 유틸리티` 섹션에 추가:

```
# 테스트
pytest==8.2.2
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_base_crawler.py`:

```python
"""BaseCrawler 공통 헬퍼 테스트"""

from bs4 import BeautifulSoup
from crawlers.base_crawler import BaseCrawler


class DummyCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(use_selenium=False)

    def extract_price(self, html, url):
        return {}

    def get_sold_out_selectors(self):
        return [".my-soldout-badge"]


def make_soup(html):
    return BeautifulSoup(html, "lxml")


# ---------- parse_price ----------

def test_parse_price_extracts_digits():
    assert BaseCrawler.parse_price("45,000원") == 45000

def test_parse_price_rejects_small_numbers():
    # 100 이하는 퍼센트 등 오탐이므로 제외
    assert BaseCrawler.parse_price("10%") is None

def test_parse_price_empty_and_none():
    assert BaseCrawler.parse_price("") is None
    assert BaseCrawler.parse_price(None) is None


# ---------- select_first_price ----------

def test_select_first_price_priority_order():
    soup = make_soup(
        '<div><em class="second">9,900</em><em class="first">45,000</em></div>'
    )
    price = BaseCrawler.select_first_price(soup, [".first", ".second"])
    assert price == 45000

def test_select_first_price_no_match():
    soup = make_soup("<div><p>no price</p></div>")
    assert BaseCrawler.select_first_price(soup, [".first"]) is None


# ---------- build_price_result ----------

def test_build_result_with_coupon():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=45000, coupon_price=40500,
                             delivery_price=2500, delivery_status="유료")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500          # 대표가 = 쿠폰가 우선
    assert r["최종 가격"] == 43000          # 쿠폰가 + 배송비
    assert r["결과 상태"] == "success"

def test_build_result_sale_only():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=45000)
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 45000
    assert r["최종 가격"] == 45000
    assert r["결과 상태"] == "success"

def test_build_result_coupon_not_cheaper_is_dropped():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=40000, coupon_price=45000)
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 40000

def test_build_result_not_found_when_no_price():
    c = DummyCrawler()
    r = c.build_price_result("http://x")
    assert r["결과 상태"] == "not_found"
    assert r["최종 가격"] is None

def test_build_result_explicit_sold_out():
    c = DummyCrawler()
    r = c.build_price_result("http://x", status="sold_out",
                             delivery_price=None, delivery_status="매진/품절",
                             error="품절 감지")
    assert r["결과 상태"] == "sold_out"
    assert r["에러 발생"] == "품절 감지"
    assert r["판매가"] is None


# ---------- detect_sold_out ----------

def test_detect_sold_out_site_selector_presence():
    c = DummyCrawler()
    soup = make_soup('<div class="my-soldout-badge"></div>')
    assert c.detect_sold_out(soup) is True

def test_detect_sold_out_generic_requires_keyword():
    c = DummyCrawler()
    # 범용 선택자 매치되지만 품절 키워드 없음 → False (오탐 방지)
    soup = make_soup('<div class="soldout_layer">알림 신청</div>')
    assert c.detect_sold_out(soup) is False
    soup2 = make_soup('<div class="soldout_layer">일시품절</div>')
    assert c.detect_sold_out(soup2) is True

def test_detect_sold_out_clean_page():
    c = DummyCrawler()
    soup = make_soup("<div><p>정상 판매중 상품</p></div>")
    assert c.detect_sold_out(soup) is False
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_base_crawler.py -v
```

Expected: FAIL — `AttributeError: ... has no attribute 'parse_price'` 등

- [ ] **Step 4: BaseCrawler에 헬퍼 구현**

`crawlers/base_crawler.py` 상단 import에 추가:

```python
from datetime import datetime
```

`SESSION_DEAD_KEYWORDS` 정의 아래에 모듈 상수 추가:

```python
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
```

`BaseCrawler` 클래스 내부, `get_price_wait_selectors` 아래에 추가:

```python
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
```

- [ ] **Step 5: crawl_price의 예외 반환 dict를 빌더로 교체**

`crawl_price` 내 `except SoldOutError as e:` 블록의 반환을 다음으로 교체:

```python
                except SoldOutError as e:
                    print(f"[INFO] 매진/품절 상품 - 재시도 없이 건너뜀: {str(e)}")
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="매진/품절",
                        status="sold_out", error=f"매진/품절: {str(e)}",
                    )
```

`except SkipRetryError as e:` 블록의 반환을 교체:

```python
                except SkipRetryError as e:
                    print(f"[INFO] 재시도 불필요 에러: {str(e)}")
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="처리 불가",
                        status="error", error=str(e),
                    )
```

`except Exception as e:` 블록 내 skip_keywords 매치 반환을 교체:

```python
                    if any(kw in error_msg.lower() for kw in skip_keywords):
                        return self.build_price_result(
                            url, delivery_price=None, delivery_status="매진/품절",
                            status="sold_out", error=error_msg,
                        )
```

같은 블록 내 `if attempt == max_retries:` 반환을 교체:

```python
                    if attempt == max_retries:
                        return self.build_price_result(
                            url, delivery_price=None, delivery_status="크롤링 실패",
                            status="error", error=error_msg,
                        )
```

루프 종료 후 최종 반환(`모든 재시도 실패` dict)을 교체:

```python
            return self.build_price_result(
                url, delivery_price=None, delivery_status="모든 재시도 실패",
                status="error",
            )
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_base_crawler.py -v
```

Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add requirements.txt crawlers/base_crawler.py tests/test_base_crawler.py
git commit -m "feat: BaseCrawler에 가격 분리/품절 감지 공통 헬퍼 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 신세계TV쇼핑 크롤러 개편

`_salePrice`(판매가)와 `_bestPrice`(혜택가=쿠폰적용가)를 분리 추출한다.

**Files:**
- Modify: `crawlers/shinsegae_crawler.py`
- Test: `tests/test_shinsegae_crawler.py` (신규)

**Interfaces:**
- Consumes: Task 2의 `select_first_price`, `build_price_result`, `detect_sold_out`
- Produces: `ShinsegaeCrawler.extract_price(html, url) -> Dict` (표준 스키마)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_shinsegae_crawler.py`:

```python
"""신세계TV쇼핑 크롤러 테스트 (HTML 픽스처 기반)"""

from crawlers.shinsegae_crawler import ShinsegaeCrawler

HTML_SALE_AND_BEST = """
<html><body>
<div class="price--3">
  <span class="_salePrice">45,000</span>
  <span class="_bestPrice">40,500</span>
</div>
</body></html>
"""

HTML_BEST_ONLY = """
<html><body>
<div class="div-best"><span class="_bestPrice">40,500</span></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body>
<div class="prd-detail"><span class="badge-soldout">일시품절</span></div>
</body></html>
"""

HTML_EMPTY = "<html><body><p>내용 없음</p></body></html>"


def test_sale_and_coupon_split():
    r = ShinsegaeCrawler().extract_price(HTML_SALE_AND_BEST, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500
    assert r["결과 상태"] == "success"


def test_best_price_only():
    r = ShinsegaeCrawler().extract_price(HTML_BEST_ONLY, "http://t")
    assert r["판매가"] is None
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500
    assert r["결과 상태"] == "success"


def test_sold_out_detected():
    r = ShinsegaeCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
    assert r["판매가"] is None


def test_not_found():
    r = ShinsegaeCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_shinsegae_crawler.py -v
```

Expected: FAIL (`판매가` 키 없음 / sold_out 미감지)

- [ ] **Step 3: 구현**

`crawlers/shinsegae_crawler.py`의 클래스 본문을 다음으로 교체 (`__init__`, `get_price_wait_selectors`는 유지):

```python
class ShinsegaeCrawler(BaseCrawler):
    """신세계TV쇼핑 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    # 판매가 (쿠폰 적용 전)
    SALE_PRICE_SELECTORS = [
        "._salePrice",
        ".price--3 ._salePrice",
        ".total_price .price em",
        ".sale_price",
    ]
    # 쿠폰/혜택 적용가
    COUPON_PRICE_SELECTORS = [
        "._bestPrice",
        ".price--3 ._bestPrice",
        ".div-best ._bestPrice",
    ]
    # 품절 표시 (실사이트 검증 태스크에서 보정)
    SOLD_OUT_SELECTORS = [
        ".badge-soldout",
        ".btn-soldout",
        "[class*='soldOut']",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            "._bestPrice",
            "._salePrice",
            ".price--3 ._bestPrice",
            ".div-best ._bestPrice",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[신세계] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[신세계] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[신세계] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        logger.info(f"[신세계] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}")
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=0, delivery_status="무료",
        )
```

주의: 판매가와 쿠폰가가 같은 값이면 `build_price_result`가 쿠폰가를 None 처리한다(정상).
파일 하단의 `_get_timestamp` 메서드는 삭제한다 (빌더가 날짜를 넣음).

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_shinsegae_crawler.py tests/test_base_crawler.py -v
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add crawlers/shinsegae_crawler.py tests/test_shinsegae_crawler.py
git commit -m "feat: 신세계TV 크롤러 판매가/쿠폰적용가 분리 + 품절 감지

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: SSG 크롤러 개편

**Files:**
- Modify: `crawlers/ssg_crawler.py`
- Test: `tests/test_ssg_crawler.py` (신규)

**Interfaces:**
- Consumes: Task 2 헬퍼
- Produces: `SSGCrawler.extract_price(html, url) -> Dict` (표준 스키마, 배송비 추출 포함)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ssg_crawler.py`:

```python
"""SSG 크롤러 테스트"""

from crawlers.ssg_crawler import SSGCrawler

HTML_SALE_WITH_DELIVERY = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">45,000</em></div>
<dl class="cdtl_dl cdtl_delivery_fee"><li><em class="ssg_price">3,000</em></li></dl>
</body></html>
"""

HTML_SALE_AND_COUPON = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">45,000</em></div>
<div class="cdtl_bene_price"><em class="ssg_price">40,500</em></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><a class="cdtl_btn_soldout">일시품절</a></body></html>
"""

HTML_EMPTY = "<html><body><p>x</p></body></html>"


def test_sale_price_and_delivery():
    r = SSGCrawler().extract_price(HTML_SALE_WITH_DELIVERY, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] is None
    assert r["배송비"] == 3000
    assert r["배송비 여부"] == "유료"
    assert r["최종 가격"] == 48000
    assert r["결과 상태"] == "success"


def test_sale_and_coupon_split():
    r = SSGCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["최종 가격"] == 40500


def test_sold_out():
    r = SSGCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"


def test_not_found():
    r = SSGCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_ssg_crawler.py -v
```

Expected: FAIL

- [ ] **Step 3: 구현**

`crawlers/ssg_crawler.py`의 클래스 본문을 다음으로 교체:

```python
class SSGCrawler(BaseCrawler):
    """SSG.COM 크롤러 - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".cdtl_new_price.notranslate .ssg_price",
        ".cdtl_price .ssg_price",
        ".price_total .ssg_price",
        "em.ssg_price",
        ".special_price .ssg_price",
        # 신세계TV 계열 URL이 fallback으로 들어올 때 대비
        ".price--3",
        "._salePrice",
        ".total_price .price em",
    ]
    COUPON_PRICE_SELECTORS = [
        ".cdtl_bene_price .ssg_price",
        ".cdtl_row_bene .ssg_price",
        "[class*='benefit'] .ssg_price",
    ]
    DELIVERY_SELECTORS = [
        ".cdtl_dl.cdtl_delivery_fee li em.ssg_price",
        ".delivery_fee .ssg_price",
        ".cdtl_delivery_fee em",
    ]
    SOLD_OUT_SELECTORS = [
        ".cdtl_btn_soldout",
        ".btn_soldout",
        ".cdtl_soldout",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",
            "em.ssg_price",
            "._salePrice",
            "._bestPrice",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                digits = re.sub(r"[^\d]", "", elem.get_text())
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[SSG] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[SSG] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[SSG] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[SSG] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
```

`_get_timestamp` 메서드는 삭제. 파일 상단 import(`re`, `BeautifulSoup`, `Dict`, `List`)는 기존 그대로 유지.

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_ssg_crawler.py -v
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add crawlers/ssg_crawler.py tests/test_ssg_crawler.py
git commit -m "feat: SSG 크롤러 판매가/쿠폰적용가 분리 + 품절 감지

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: CJ온스타일 크롤러 개편

**Files:**
- Modify: `crawlers/cj_crawler.py`
- Test: `tests/test_cj_crawler.py` (신규)

**Interfaces:**
- Consumes: Task 2 헬퍼
- Produces: `CJCrawler.extract_price(html, url) -> Dict` (표준 스키마). `use_selenium=True` 유지.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cj_crawler.py`:

```python
"""CJ온스타일 크롤러 테스트"""

from crawlers.cj_crawler import CJCrawler

HTML_SALE_AND_COUPON = """
<html><body>
<div class="item_price"><strong class="ff_price">43,000</strong></div>
<div class="coupon_price"><span class="ff_price">39,900</span></div>
<div class="delivery_fees"><strong>2,500원</strong></div>
</body></html>
"""

HTML_SALE_ONLY = """
<html><body>
<div class="item_price"><strong class="ff_price">43,000</strong></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><button class="btn_soldout">품절</button></body></html>
"""


def test_sale_and_coupon_split():
    r = CJCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 43000
    assert r["쿠폰적용가"] == 39900
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 42400
    assert r["결과 상태"] == "success"


def test_sale_only():
    r = CJCrawler().extract_price(HTML_SALE_ONLY, "http://t")
    assert r["판매가"] == 43000
    assert r["쿠폰적용가"] is None
    assert r["최종 가격"] == 43000


def test_sold_out():
    r = CJCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_cj_crawler.py -v
```

Expected: FAIL

- [ ] **Step 3: 구현**

`crawlers/cj_crawler.py`의 클래스 본문을 다음으로 교체:

```python
class CJCrawler(BaseCrawler):
    """CJ온스타일 크롤러 (Selenium) - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".item_price strong.ff_price",
        ".opt_area .item_price strong.ff_price",
        ".price_bx .txt_price .ff_price",
        ".txt_price .ff_price",
        ".total_price_wrap strong.ff_price",
        ".price_area .price_txt > strong.ff_price",
        ".ff_price",
    ]
    COUPON_PRICE_SELECTORS = [
        ".coupon_price .ff_price",
        ".price_coupon .ff_price",
        ".benefit_price .ff_price",
    ]
    DELIVERY_SELECTORS = [
        ".gift_delivery_wrap .delivery_fees strong",
        ".delivery_fees strong",
    ]
    SOLD_OUT_SELECTORS = [
        ".btn_soldout",
        ".soldout_layer .txt",
    ]

    def __init__(self):
        super().__init__(use_selenium=True)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".item_price strong.ff_price",
            ".ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                digits = re.sub(r"[^\d]", "", elem.get_text())
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[CJ] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[CJ] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[CJ] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[CJ] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
```

`_get_timestamp` 삭제. 상단에 `import re`가 없으면 추가 (기존 파일에 이미 있음).

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_cj_crawler.py -v
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add crawlers/cj_crawler.py tests/test_cj_crawler.py
git commit -m "feat: CJ 크롤러 판매가/쿠폰적용가 분리 + 품절 감지

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: GS샵 크롤러 개편 (결과 상태 키 누락 수정 포함)

기존 GS 크롤러는 반환 dict에 `결과 상태` 키가 없다. 빌더 사용으로 함께 해결된다.

**Files:**
- Modify: `crawlers/gs_crawler.py`
- Test: `tests/test_gs_crawler.py` (신규)

**Interfaces:**
- Consumes: Task 2 헬퍼
- Produces: `GSCrawler.extract_price(html, url) -> Dict` (표준 스키마, `결과 상태` 포함)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gs_crawler.py`:

```python
"""GS샵 크롤러 테스트"""

from crawlers.gs_crawler import GSCrawler

HTML_SALE_AND_COUPON = """
<html><body>
<div class="price-definition-ins"><ins><strong>50,000</strong></ins></div>
<div class="price-definition-coupon"><strong>45,000</strong></div>
<p class="shipCate"><strong>2,500원</strong></p>
</body></html>
"""

HTML_SALE_ONLY = """
<html><body>
<em id="totValue">50,000</em>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><div class="prd-btn-soldout">일시품절</div></body></html>
"""


def test_sale_and_coupon_split():
    r = GSCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 50000
    assert r["쿠폰적용가"] == 45000
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 47500
    assert r["결과 상태"] == "success"


def test_sale_only_has_status_key():
    r = GSCrawler().extract_price(HTML_SALE_ONLY, "http://t")
    assert r["판매가"] == 50000
    assert r["결과 상태"] == "success"   # 기존 버그: 이 키가 없었음


def test_sold_out():
    r = GSCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_gs_crawler.py -v
```

Expected: FAIL

- [ ] **Step 3: 구현**

`crawlers/gs_crawler.py`의 클래스 본문을 다음으로 교체:

```python
class GSCrawler(BaseCrawler):
    """GS샵 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".price-definition-ins ins strong",
        "#totValue",
        "em#totValue",
        ".item_price strong",
        ".price_value strong",
        ".sale_price strong",
    ]
    COUPON_PRICE_SELECTORS = [
        ".price-definition-coupon strong",
        ".coupon-price strong",
    ]
    DELIVERY_SELECTORS = [
        ".shipCate strong",
        "p.shipCate strong",
        ".paragraph1 .shipCate strong",
    ]
    SOLD_OUT_SELECTORS = [
        ".prd-btn-soldout",
        ".btn-soldout",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []  # HTTP 방식 - 불필요

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                first_part = elem.get_text().split("원")[0]
                digits = re.sub(r"[^\d]", "", first_part)
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[GS] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[GS] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[GS] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[GS] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
```

`_get_timestamp` 삭제.

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_gs_crawler.py -v
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add crawlers/gs_crawler.py tests/test_gs_crawler.py
git commit -m "feat: GS 크롤러 판매가/쿠폰적용가 분리 + 결과 상태 키 수정

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 롯데아이몰 크롤러 개편

기존 코드의 `.final .num`(최적가)을 쿠폰적용가로, `.sale .num`(판매가)을 판매가로 분리한다.

**Files:**
- Modify: `crawlers/lotte_crawler.py`
- Test: `tests/test_lotte_crawler.py` (신규)

**Interfaces:**
- Consumes: Task 2 헬퍼
- Produces: `LotteCrawler.extract_price(html, url) -> Dict` (표준 스키마)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_lotte_crawler.py`:

```python
"""롯데아이몰 크롤러 테스트"""

from crawlers.lotte_crawler import LotteCrawler

HTML_SALE_AND_FINAL = """
<html><body>
<div class="price_product">
  <div class="sale"><span class="num">95,000</span></div>
  <div class="final"><span class="num">89,000</span></div>
</div>
<div class="row_product delivery"><div class="cont"><p>배송비 2,500원</p></div></div>
</body></html>
"""

HTML_FINAL_ONLY = """
<html><body>
<div class="price_product"><div class="final"><span class="num">89,000</span></div></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><div class="btn_soldout_area">품절</div></body></html>
"""


def test_sale_and_coupon_split():
    r = LotteCrawler().extract_price(HTML_SALE_AND_FINAL, "http://t")
    assert r["판매가"] == 95000
    assert r["쿠폰적용가"] == 89000
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 91500
    assert r["결과 상태"] == "success"


def test_final_only_becomes_representative():
    r = LotteCrawler().extract_price(HTML_FINAL_ONLY, "http://t")
    assert r["판매가"] is None
    assert r["쿠폰적용가"] == 89000
    assert r["상품 가격"] == 89000


def test_sold_out():
    r = LotteCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_lotte_crawler.py -v
```

Expected: FAIL

- [ ] **Step 3: 구현**

`crawlers/lotte_crawler.py`의 클래스 본문을 다음으로 교체:

```python
class LotteCrawler(BaseCrawler):
    """롯데아이몰 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".price_product .sale .num",
        ".price_product .origin .num",
        ".sale_prc",
    ]
    COUPON_PRICE_SELECTORS = [
        ".price_product .final .num",
        ".price_product .price .final .num",
        ".final_price_area .heading .price .num",
        ".real_prc",
    ]
    DELIVERY_SELECTORS = [
        ".row_product.delivery .cont > p:first-of-type",
        ".row_product.delivery .cont p",
        ".delivery .cont p",
    ]
    SOLD_OUT_SELECTORS = [
        ".btn_soldout_area",
        ".soldout_wrap",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text()
                if "배송비" in text and "추가" not in text:
                    first_part = text.split("원")[0]
                    digits = re.sub(r"[^\d]", "", first_part)
                    delivery_price = int(digits) if digits else 0
                    return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[롯데] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[롯데] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[롯데] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[롯데] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
```

`_get_timestamp` 삭제.

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/ -v
```

Expected: 전 크롤러 테스트 PASS

- [ ] **Step 5: 커밋**

```bash
git add crawlers/lotte_crawler.py tests/test_lotte_crawler.py
git commit -m "feat: 롯데 크롤러 판매가/쿠폰적용가 분리 + 품절 감지

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: 플랫 테이블 엑셀 생성 모듈 (utils/excel_report.py)

엑셀 생성을 엔진에서 분리한 신규 모듈. 시트1 "전체 결과"(플랫 테이블), 시트2 "가격 역전 항목".

**Files:**
- Create: `utils/excel_report.py`
- Test: `tests/test_excel_report.py` (신규)

**Interfaces:**
- Consumes: 크롤러 표준 스키마의 `results` 리스트 (엔진 `_do_crawling`이 모으는 형태 —
  `[{"product_id", "product_name", "timestamp", "result_status", "prices": [{"seller", "상품 url", "판매가", "쿠폰적용가", "상품 가격", "배송비", "배송비 여부", "최종 가격", "결과 상태", "에러 발생"?}, ...]}, ...]`)
- Produces: `save_results_excel(results: List[Dict], site_name: str, results_dir: str = "results") -> Optional[str]` — 생성된 파일 경로 반환 (Task 9에서 엔진이 호출)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_excel_report.py`:

```python
"""플랫 테이블 엑셀 리포트 테스트"""

import openpyxl
from utils.excel_report import save_results_excel, coupon_rate_display

RESULTS = [
    {
        "product_id": 1,
        "product_name": "CK ALL 오 드 뚜알렛 100ml",
        "timestamp": "2026-07-04T12:00:00",
        "result_status": "success",
        "prices": [
            {"seller": "waffle", "상품 url": "http://waffle/1", "판매가": 45000,
             "쿠폰적용가": 40500, "상품 가격": 40500, "배송비": 2500,
             "배송비 여부": "유료", "최종 가격": 43000, "결과 상태": "success"},
            {"seller": "cj", "상품 url": "http://cj/1", "판매가": 43000,
             "쿠폰적용가": None, "상품 가격": 43000, "배송비": 0,
             "배송비 여부": "무료", "최종 가격": 43000, "결과 상태": "success"},
            {"seller": "gs", "상품 url": "http://gs/1", "판매가": None,
             "쿠폰적용가": None, "상품 가격": None, "배송비": None,
             "배송비 여부": "매진/품절", "최종 가격": None,
             "결과 상태": "sold_out", "에러 발생": "품절 감지"},
        ],
    },
    {
        "product_id": 2,
        "product_name": "딥디크 오로즈 EDT 50ml",
        "timestamp": "2026-07-04T12:01:00",
        "result_status": "success",
        "prices": [
            {"seller": "waffle", "상품 url": "http://waffle/2", "판매가": 98000,
             "쿠폰적용가": 93100, "상품 가격": 93100, "배송비": 0,
             "배송비 여부": "무료", "최종 가격": 93100, "결과 상태": "success"},
            {"seller": "lotte", "상품 url": "http://lotte/2", "판매가": 95000,
             "쿠폰적용가": 89000, "상품 가격": 89000, "배송비": 0,
             "배송비 여부": "무료", "최종 가격": 89000, "결과 상태": "success"},
        ],
    },
]

EXPECTED_HEADERS = ["제품명", "판매처", "URL", "판매가", "쿠폰율", "쿠폰적용가",
                    "배송비", "최종가격", "상태", "비고"]


def make_workbook(tmp_path):
    path = save_results_excel(RESULTS, "ssg", results_dir=str(tmp_path))
    assert path is not None
    return openpyxl.load_workbook(path)


def test_coupon_rate_display():
    assert coupon_rate_display(45000, 40500) == "10%"
    assert coupon_rate_display(45000, None) == "-"
    assert coupon_rate_display(None, 40500) == "-"
    assert coupon_rate_display(40000, 45000) == "-"   # 쿠폰가가 더 비싸면 무효


def test_flat_sheet_headers(tmp_path):
    wb = make_workbook(tmp_path)
    ws = wb["전체 결과"]
    headers = [c.value for c in ws[1]]
    assert headers == EXPECTED_HEADERS


def test_flat_sheet_row_count(tmp_path):
    wb = make_workbook(tmp_path)
    ws = wb["전체 결과"]
    # 헤더 1행 + 가격행 5개
    assert ws.max_row == 6


def test_flat_sheet_success_row(tmp_path):
    wb = make_workbook(tmp_path)
    ws = wb["전체 결과"]
    row = [c.value for c in ws[2]]  # 첫 데이터 행 = waffle/제품1
    assert row[0] == "CK ALL 오 드 뚜알렛 100ml"
    assert row[1] == "Waffle (우리회사)"
    assert row[3] == 45000       # 판매가 (숫자)
    assert row[4] == "10%"       # 쿠폰율
    assert row[5] == 40500       # 쿠폰적용가
    assert row[7] == 43000       # 최종가격
    assert row[8] == "판매중"


def test_flat_sheet_sold_out_row(tmp_path):
    wb = make_workbook(tmp_path)
    ws = wb["전체 결과"]
    row = [c.value for c in ws[4]]  # 제품1의 gs 행
    assert row[3] == "품절"      # 판매가 셀에 품절 명시
    assert row[7] == "-"
    assert row[8] == "품절"
    # 행 배경색 강조 확인 (빨간 계열)
    assert ws.cell(row=4, column=1).fill.start_color.rgb in ("FFFFC7CE", "00FFC7CE")


def test_reversal_sheet(tmp_path):
    wb = make_workbook(tmp_path)
    ws = wb["가격 역전 항목"]
    headers = [c.value for c in ws[1]]
    assert headers == EXPECTED_HEADERS + ["가격차이"]
    # 제품2만 역전 (lotte 89,000 < waffle 93,100) → waffle 행 + lotte 행
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 2
    assert rows[0][1] == "Waffle (우리회사)"
    assert rows[1][1] == "경쟁사 (lotte)"
    assert rows[1][10] == "-4100원 저렴"


def test_reversal_sheet_empty(tmp_path):
    no_reversal = [RESULTS[0]]  # 제품1은 역전 없음
    path = save_results_excel(no_reversal, "ssg", results_dir=str(tmp_path))
    wb = openpyxl.load_workbook(path)
    ws = wb["가격 역전 항목"]
    assert ws.cell(row=2, column=1).value == "가격 역전 항목이 없습니다."
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
perfume/bin/python -m pytest tests/test_excel_report.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'utils.excel_report'`

- [ ] **Step 3: 구현**

`utils/excel_report.py` (신규 파일 전체):

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
perfume/bin/python -m pytest tests/test_excel_report.py -v
```

Expected: 전부 PASS. (실패 시 openpyxl의 fill rgb 표현 차이면 assert 튜플에 실제 값 추가)

- [ ] **Step 5: 커밋**

```bash
git add utils/excel_report.py tests/test_excel_report.py
git commit -m "feat: 플랫 테이블 엑셀 리포트 모듈 추가 (쿠폰율/품절 강조/역전 시트)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: 엔진 연동 (_save_results 위임)

**Files:**
- Modify: `utils/crawling_engine_v2.py:671-866` (`_save_results` 전체 교체)

**Interfaces:**
- Consumes: Task 8의 `save_results_excel(results, site_name) -> Optional[str]`
- Produces: 기존과 동일한 엔진 인터페이스 (`_save_results(job_id, results, site_name) -> Optional[str]`) — 호출부(`_do_crawling`) 변경 없음

- [ ] **Step 1: _save_results 교체**

`utils/crawling_engine_v2.py`의 `_save_results` 메서드(현재 약 195줄) 전체를 다음으로 교체:

```python
    def _save_results(self, job_id: int, results: List[Dict], site_name: str) -> Optional[str]:
        """결과를 플랫 테이블 Excel로 저장 (utils/excel_report.py에 위임)"""
        from utils.excel_report import save_results_excel
        return save_results_excel(results, site_name)
```

파일 상단의 `import xlsxwriter` 관련 코드는 메서드 내부 import였으므로 함께 제거됨을 확인.

- [ ] **Step 2: 전체 테스트 + 임포트 확인**

```bash
perfume/bin/python -m pytest tests/ -v
perfume/bin/python -c "from utils.crawling_engine_v2 import CrawlingEngineV2; print('import OK')"
```

Expected: 테스트 전부 PASS, `import OK` 출력

- [ ] **Step 3: 커밋**

```bash
git add utils/crawling_engine_v2.py
git commit -m "refactor: 엑셀 생성을 excel_report 모듈로 위임

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: 실사이트 검증 스크립트 + 선택자 보정

쿠폰가/품절 선택자는 실제 사이트 DOM 확인 없이는 확정할 수 없다. 검증 CLI를 만들고, 과거 결과 엑셀에서 실제 상품 URL을 뽑아 사이트별로 검증·보정한다.

**Files:**
- Create: `scripts/verify_crawler.py`
- Modify (필요시): 각 크롤러의 `COUPON_PRICE_SELECTORS`, `SOLD_OUT_SELECTORS` 및 해당 테스트 픽스처

**Interfaces:**
- Consumes: `crawlers.crawler_factory.get_crawler_by_url(url)`
- Produces: `perfume/bin/python scripts/verify_crawler.py <URL>...` CLI (사람이 실행하는 검증 도구)

- [ ] **Step 1: 검증 스크립트 작성**

`scripts/verify_crawler.py` (신규):

```python
"""실제 상품 페이지로 크롤러 추출 결과를 검증하는 CLI.

사용법:
    perfume/bin/python scripts/verify_crawler.py <상품URL> [<상품URL> ...]

출력: 판매가/쿠폰적용가/배송비/최종가격/결과상태 JSON
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.crawler_factory import get_crawler_by_url


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    for url in sys.argv[1:]:
        crawler = get_crawler_by_url(url)
        if not crawler:
            print(f"\n지원하지 않는 URL: {url}")
            continue
        print(f"\n=== [{crawler.__class__.__name__}] {url[:80]}")
        try:
            result = crawler.crawl_price(url, auto_close=True)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 과거 결과 엑셀에서 사이트별 샘플 URL 추출**

```bash
perfume/bin/python - <<'EOF'
import glob
import openpyxl

for path in sorted(glob.glob("results/*.xlsx")):
    urls = set()
    wb = openpyxl.load_workbook(path, read_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if isinstance(cell, str) and cell.startswith("http"):
                    urls.add(cell)
    print(f"\n{path}")
    for u in list(urls)[:4]:
        print("  ", u)
EOF
```

Expected: 사이트별 실제 상품 URL 목록 (ssg/cj/신세계TV/롯데/gs)

- [ ] **Step 3: 사이트별 검증 실행 (사이트당 판매중 1개 이상)**

```bash
perfume/bin/python scripts/verify_crawler.py <ssg URL>
perfume/bin/python scripts/verify_crawler.py <cj URL>
perfume/bin/python scripts/verify_crawler.py <신세계TV URL>
perfume/bin/python scripts/verify_crawler.py <롯데 URL>
perfume/bin/python scripts/verify_crawler.py <gs URL>
```

각 결과에서 확인할 것:
1. `판매가`가 페이지 표시 판매가와 일치하는가
2. 페이지에 쿠폰/혜택가가 공개 표시되는데 `쿠폰적용가`가 None이면 → 브라우저 개발자도구(또는 아래 명령으로 HTML 덤프)로 실제 선택자를 찾아 해당 크롤러의 `COUPON_PRICE_SELECTORS`에 추가:

```bash
perfume/bin/python - <<'EOF'
from crawlers.crawler_factory import get_crawler_by_url
url = "<확인할 URL>"
crawler = get_crawler_by_url(url)
html = crawler.fetch_page(url)
with open("/tmp/page_dump.html", "w") as f:
    f.write(html or "")
print("dumped:", len(html or ""))
EOF
grep -o 'class="[^"]*쿠폰[^"]*"' /tmp/page_dump.html | sort -u
grep -io 'class="[^"]*coupon[^"]*"' /tmp/page_dump.html | sort -u | head -20
```

3. 품절 상품 URL이 있으면 `결과 상태 == "sold_out"` 확인, 품절 뱃지의 실제 클래스를 `SOLD_OUT_SELECTORS`에 반영

- [ ] **Step 4: 보정한 선택자에 맞춰 테스트 픽스처 갱신 후 전체 테스트**

선택자를 수정한 크롤러가 있으면 해당 `tests/test_*_crawler.py` 픽스처 HTML의 클래스명도 실제 DOM 구조로 갱신한다.

```bash
perfume/bin/python -m pytest tests/ -v
```

Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/verify_crawler.py crawlers/ tests/
git commit -m "feat: 실사이트 크롤러 검증 CLI 추가 및 쿠폰/품절 선택자 보정

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: 통합 스모크 테스트 및 마무리

**Files:**
- 없음 (검증만)

**Interfaces:**
- Consumes: 전체 시스템

- [ ] **Step 1: 전체 테스트 실행**

```bash
perfume/bin/python -m pytest tests/ -v
```

Expected: 전부 PASS

- [ ] **Step 2: DB 무변경 확인**

```bash
perfume/bin/python - <<'EOF'
import sqlite3
conn = sqlite3.connect("crawling.db")
for table in ("users", "crawling_jobs", "crawling_logs"):
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: {count} rows")
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    print("  columns:", cols)
EOF
```

Expected: 작업 전과 동일한 행 수/컬럼 목록 (스키마 변경 없음)

- [ ] **Step 3: 서버 기동 + 실제 잡 1회 (사용자와 함께)**

```bash
perfume/bin/python app.py
```

사용자의 구글 시트로 사이트 1개(권장: gs 또는 lotte — HTTP 방식이라 빠름) 크롤링 실행 후 생성된 `results/*_가격조사_*.xlsx` 열어 확인:
- 시트1이 플랫 테이블(헤더 고정 + 자동 필터)인가
- 컬럼 순서: 제품명|판매처|URL|판매가|쿠폰율|쿠폰적용가|배송비|최종가격|상태|비고
- 품절 행이 빨간 배경으로 강조되는가
- 시트2 역전 항목이 정상인가
- 웹 대시보드 SSE 진행률이 기존처럼 동작하는가

- [ ] **Step 4: 최종 커밋**

```bash
git add -A
git status   # crawling.db, results/ 미포함 확인
git commit -m "chore: 엑셀 플랫 리포트 + 쿠폰가 크롤링 마무리

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
