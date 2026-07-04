import requests
from bs4 import BeautifulSoup
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

tests = [
    ('SSG', 'https://www.ssg.com/item/itemView.ssg?itemId=1000035622592', ['em.ssg_price', '.ssg_price', '.cdtl_new_price .ssg_price']),
    ('CJ', 'https://display.cjonstyle.com/p/item/58371152', ['.ff_price', '.item_price strong.ff_price', '.txt_price .ff_price']),
    ('롯데', 'https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=1461876177', ['.price_product .final .num', '.final_price_area .price .num', '.final .num']),
    ('신세계', 'https://www.shinsegaetvshopping.com/display/detail/10149848', ['._bestPrice', '._salePrice', '.price--3']),
]

for name, url, selectors in tests:
    try:
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'lxml')
        found = False
        for sel in selectors:
            for e in soup.select(sel):
                txt = re.sub(r'[^\d]', '', e.get_text())
                if txt and int(txt) > 100:
                    print(f'✅ {name}: HTTP 가능! {int(txt):,}원 (선택자: {sel})')
                    found = True
                    break
            if found:
                break
        if not found:
            print(f'❌ {name}: JS 렌더링 필요 (HTML 크기: {len(r.text):,} bytes)')
    except Exception as e:
        print(f'💥 {name}: 오류 - {e}')
