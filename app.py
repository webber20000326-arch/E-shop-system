# -*- coding: utf-8 -*-
"""PChome × MOMO 價格比較系統（Streamlit）"""
import re
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests

st.set_page_config(page_title="PChome × MOMO 價格比較", page_icon="🛒", layout="wide")

# ---------------------------------------------------------------
# 常數
# ---------------------------------------------------------------
PCHOME_API = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
PCHOME_ITEM = "https://24h.pchome.com.tw/prod/{}"
MOMO_API = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
MOMO_HOME = "https://www.momoshop.com.tw/"
MOMO_ITEM = "https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={}"
MOMO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}

PCHOME_SORT = {
    "銷量高到低": "sale/dc",
    "價格低到高": "prc/ac",
    "價格高到低": "prc/dc",
    "相關度": "rnk/dc",
}
PRICE_BINS = [0, 300, 500, 1000, 2000, 5000, float("inf")]
PRICE_LABELS = ["300以下", "301-500", "501-1000", "1001-2000", "2001-5000", "5000以上"]
COLORS = {"PChome": "#1f77b4", "MOMO": "#e8458b"}
PLATFORM_ORDER = ["PChome", "MOMO"]


# ---------------------------------------------------------------
# 爬蟲
# ---------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=600)
def crawl_pchome(keyword: str, pages: int, sort: str, delay: float) -> pd.DataFrame:
    session = requests.Session(impersonate="chrome")
    rows = []
    for page in range(1, pages + 1):
        resp = session.get(
            PCHOME_API,
            params={"q": keyword, "page": page, "sort": sort},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"PChome 第 {page} 頁請求失敗（HTTP {resp.status_code}）")
        prods = resp.json().get("prods", [])
        if not prods:
            break
        for p in prods:
            pid = p.get("Id", "")
            rows.append(
                {
                    "平台": "PChome",
                    "品名": p.get("name", ""),
                    "價格": p.get("price"),
                    "頁碼": page,
                    "連結": PCHOME_ITEM.format(pid) if pid else "",
                }
            )
        if page < pages:
            time.sleep(delay)
    return pd.DataFrame(rows, columns=["平台", "品名", "價格", "頁碼", "連結"])


def _momo_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def crawl_momo(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    session = requests.Session(impersonate="chrome")
    session.get(MOMO_HOME, headers=MOMO_HEADERS)  # 先取得 cookie
    rows = []
    for page in range(1, pages + 1):
        resp = session.post(MOMO_API, headers=MOMO_HEADERS, json=_momo_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"MOMO 第 {page} 頁請求失敗（HTTP {resp.status_code}）")
        prods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not prods:
            break
        for p in prods:
            code = p.get("goodsCode", "")
            rows.append(
                {
                    "平台": "MOMO",
                    "品名": p.get("goodsName", ""),
                    "價格": p.get("goodsPrice", ""),
                    "頁碼": page,
                    "連結": MOMO_ITEM.format(code) if code else "",
                }
            )
        if page < pages:
            time.sleep(delay)
    return pd.DataFrame(rows, columns=["平台", "品名", "價格", "頁碼", "連結"])


# ---------------------------------------------------------------
# 資料整理
# ---------------------------------------------------------------
def extract_brand(name: str) -> str:
    """優先取【】內文字，否則取第一個中英文詞"""
    name = str(name).strip()
    m = re.match(r"^[【\[]([^】\]]+)[】\]]", name)
    if m:
        return m.group(1)[:10]
    m = re.match(r"^([A-Za-z0-9\u4e00-\u9fff]+)", name)
    return m.group(1)[:8] if m else "其他"


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["價格"] = pd.to_numeric(
        out["價格"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce"
    )
    out = out.dropna(subset=["價格"])
    out["價格"] = out["價格"].astype(int)
    out["價格區間"] = pd.cut(out["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True)
    out["品牌"] = out["品名"].apply(extract_brand)
    out["序號"] = out.groupby("平台").cumcount() + 1
    out["平台"] = pd.Categorical(out["平台"], categories=PLATFORM_ORDER, ordered=True)
    return out.sort_values(["平台", "序號"]).reset_index(drop=True)


# ---------------------------------------------------------------
# 側邊欄
# ---------------------------------------------------------------
st.title("🛒 PChome × MOMO 價格比較")
st.caption("輸入商品名稱與頁數，同時爬取兩大平台並比較價格分布")

with st.sidebar:
    st.header("搜尋設定")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數（每個平台）", min_value=1, max_value=20, value=2, step=1)
    use_pchome = st.checkbox("PChome 24h", value=True)
    use_momo = st.checkbox("MOMO 購物網", value=True)
    sort_label = st.selectbox("PChome 排序方式", list(PCHOME_SORT.keys()))
    delay = st.slider("每頁間隔秒數", 0.5, 5.0, 1.5, 0.5)
    run = st.button("開始爬取並比較", type="primary", use_container_width=True)

# ---------------------------------------------------------------
# 執行爬取
# ---------------------------------------------------------------
if run:
    kw_in = keyword.strip()
    if not kw_in:
        st.warning("請輸入產品名稱")
        st.stop()
    if not (use_pchome or use_momo):
        st.warning("請至少選擇一個平台")
        st.stop()

    frames, errors = [], []
    with st.spinner("爬取中，請稍候…"):
        if use_pchome:
            try:
                frames.append(crawl_pchome(kw_in, int(pages), PCHOME_SORT[sort_label], float(delay)))
            except Exception as e:
                errors.append(f"PChome 爬取失敗：{e}")
        if use_momo:
            try:
                frames.append(crawl_momo(kw_in, int(pages), float(delay)))
            except Exception as e:
                errors.append(f"MOMO 爬取失敗：{e}")
    for msg in errors:
        st.error(msg)

    frames = [f for f in frames if not f.empty]
    if not frames:
        st.info("沒有取得任何商品，請換個關鍵字或稍後再試")
        st.stop()
    st.session_state["df"] = prepare(pd.concat(frames, ignore_index=True))
    st.session_state["keyword"] = kw_in

if "df" not in st.session_state:
    st.info("請在左側輸入產品名稱與頁數，按「開始爬取並比較」")
    st.stop()

df: pd.DataFrame = st.session_state["df"]
kw: str = st.session_state["keyword"]
platforms = [p for p in PLATFORM_ORDER if p in df["平台"].astype(str).unique()]

# ---------------------------------------------------------------
# 平台統計摘要
# ---------------------------------------------------------------
st.subheader(f"「{kw}」平台比較")
cols = st.columns(len(platforms))
for col, p in zip(cols, platforms):
    sub = df[df["平台"] == p]
    with col:
        st.markdown(f"**{p}**")
        a, b = st.columns(2)
        a.metric("商品數", f"{len(sub):,}")
        b.metric("平均價格", f"{sub['價格'].mean():,.0f}")
        c, d = st.columns(2)
        c.metric("中位數", f"{sub['價格'].median():,.0f}")
        d.metric("價格範圍", f"{sub['價格'].min():,} ~ {sub['價格'].max():,}")

tab_line, tab_pie, tab_sun, tab_bar, tab_data = st.tabs(
    ["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📊 柱狀圖", "📄 資料表"]
)

# ---- 折線圖 ----
with tab_line:
    max_n = int(df.groupby("平台", observed=True).size().max())
    n = st.slider("每個平台顯示前幾筆", 1, max_n, min(70, max_n)) if max_n > 1 else 1
    sub = df[df["序號"] <= n]
    fig = px.line(
        sub, x="序號", y="價格", color="平台", markers=True,
        hover_data=["品名"], color_discrete_map=COLORS,
        category_orders={"平台": platforms},
        title=f"「{kw}」各平台商品售價",
    )
    for p in platforms:
        mean_p = df.loc[df["平台"] == p, "價格"].mean()
        fig.add_hline(
            y=mean_p, line_dash="dash", line_color=COLORS[p],
            annotation_text=f"{p} 平均 {mean_p:,.0f}",
            annotation_position="top left" if p == "PChome" else "bottom right",
        )
    fig.update_layout(height=550, xaxis_title="商品序號", yaxis_title="價格")
    st.plotly_chart(fig, use_container_width=True)

# ---- 圓餅圖 ----
with tab_pie:
    pcols = st.columns(len(platforms))
    for col, p in zip(pcols, platforms):
        sub = df[df["平台"] == p]
        pie_df = (
            sub["價格區間"].value_counts().reindex(PRICE_LABELS).fillna(0).astype(int).reset_index()
        )
        pie_df.columns = ["價格區間", "商品數"]
        pie_df = pie_df[pie_df["商品數"] > 0]
        fig = px.pie(pie_df, names="價格區間", values="商品數", hole=0.3,
                     title=f"{p} 價格區間占比",
                     category_orders={"價格區間": PRICE_LABELS})
        fig.update_traces(textinfo="percent+label", sort=False)
        fig.update_layout(height=500, showlegend=False)
        col.plotly_chart(fig, use_container_width=True)

# ---- 旭日圖 ----
with tab_sun:
    depth = st.radio(
        "旭日圖層級",
        ["平台 → 價格區間", "平台 → 價格區間 → 品牌"],
        index=1, horizontal=True,
    )
    top_brands = df["品牌"].value_counts().head(15).index
    sun_df = df.copy()
    sun_df["品牌"] = sun_df["品牌"].where(sun_df["品牌"].isin(top_brands), "其他")
    sun_df["平台"] = sun_df["平台"].astype(str)
    sun_df["價格區間"] = sun_df["價格區間"].astype(str)
    sun_df = sun_df.assign(商品數=1)
    path = ["平台", "價格區間"] if depth.count("→") == 1 else ["平台", "價格區間", "品牌"]
    fig = px.sunburst(
        sun_df, path=path, values="商品數", color="平台",
        color_discrete_map=COLORS, title=f"「{kw}」平台 / 價格區間 / 品牌結構",
    )
    fig.update_layout(height=650)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("品牌由品名自動擷取（【】內文字或第一個詞），僅供參考；只顯示前 15 大品牌，其餘歸為「其他」。")

# ---- 柱狀圖 ----
with tab_bar:
    b1, b2 = st.columns(2)

    with b1:
        cnt = (
            df.groupby(["價格區間", "平台"], observed=False).size().reset_index(name="商品數")
        )
        cnt["平台"] = cnt["平台"].astype(str)
        fig = px.bar(
            cnt, x="價格區間", y="商品數", color="平台", barmode="group",
            color_discrete_map=COLORS, text="商品數",
            category_orders={"價格區間": PRICE_LABELS},
            title="各價格區間商品數",
        )
        fig.update_layout(height=480)
        st.plotly_chart(fig, use_container_width=True)

    with b2:
        stat = (
            df.groupby("平台", observed=True)["價格"]
            .agg(平均價格="mean", 中位數="median", 最低價="min", 最高價="max")
            .round(0).reset_index()
            .melt(id_vars="平台", var_name="指標", value_name="價格")
        )
        stat["平台"] = stat["平台"].astype(str)
        fig = px.bar(
            stat, x="指標", y="價格", color="平台", barmode="group",
            color_discrete_map=COLORS, text="價格",
            title="價格統計比較",
        )
        fig.update_layout(height=480)
        st.plotly_chart(fig, use_container_width=True)

    brand_n = st.slider("品牌平均價格：顯示前幾大品牌", 3, 20, 8)
    top_b = df["品牌"].value_counts().head(brand_n).index
    brand_df = (
        df[df["品牌"].isin(top_b)]
        .groupby(["品牌", "平台"], observed=True)["價格"].mean().round(0).reset_index()
    )
    brand_df["平台"] = brand_df["平台"].astype(str)
    fig = px.bar(
        brand_df, x="品牌", y="價格", color="平台", barmode="group",
        color_discrete_map=COLORS, text="價格",
        title=f"熱門品牌（前 {brand_n} 名）平均價格比較",
        category_orders={"品牌": list(top_b)},
    )
    fig.update_layout(height=480)
    st.plotly_chart(fig, use_container_width=True)

# ---- 資料表 ----
with tab_data:
    f1, f2 = st.columns([1, 2])
    plat_sel = f1.multiselect("平台篩選", platforms, default=platforms)
    lo, hi = int(df["價格"].min()), int(df["價格"].max())
    price_rng = f2.slider("價格範圍", lo, hi, (lo, hi)) if lo < hi else (lo, hi)

    view = df[df["平台"].isin(plat_sel) & df["價格"].between(*price_rng)].copy()
    view["平台"] = view["平台"].astype(str)
    view["價格區間"] = view["價格區間"].astype(str)
    view = view.sort_values("價格").reset_index(drop=True)
    st.caption(f"共 {len(view):,} 筆，點擊「商品頁面」欄位的連結即可開啟商品")

    st.dataframe(
        view[["平台", "品名", "價格", "價格區間", "品牌", "頁碼", "連結"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "連結": st.column_config.LinkColumn("商品頁面", display_text="前往商品 🔗"),
            "價格": st.column_config.NumberColumn("價格", format="$%d"),
            "品名": st.column_config.TextColumn("品名", width="large"),
        },
    )
    st.download_button(
        "下載 CSV",
        data=view.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"比價_{kw}_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )
