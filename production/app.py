import os
import re
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import altair as alt
import streamlit as st
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html as st_html

load_dotenv()

VIDEO_FILE = Path(__file__).resolve().parent / "videos.csv"
API_KEY = os.getenv("YOUTUBE_API_KEY")


def extract_video_id(value: str) -> str | None:
    cleaned_value = (value or "").strip()
    if not cleaned_value:
        return None

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", cleaned_value):
        return cleaned_value

    parsed = urlparse(cleaned_value)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]

    if "youtu.be" in host:
        if path_parts:
            return path_parts[0] if re.fullmatch(r"[A-Za-z0-9_-]{11}", path_parts[0]) else None
        return None

    if "youtube.com" in host:
        if parsed.path in ("/watch", "/shorts", "/live"):
            query = parse_qs(parsed.query)
            return query.get("v", [None])[0]

        if path_parts:
            if path_parts[0] in {"shorts", "live", "embed"} and len(path_parts) > 1:
                candidate = path_parts[1]
                return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", path_parts[0]):
                return path_parts[0]

    return None


def load_video_list(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        st.error(f"Missing video list file: {file_path.name}")
        st.stop()

    rows = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.lower() == "title,url":
            continue

        if "," not in cleaned:
            continue

        title, url = cleaned.rsplit(",", 1)
        title = title.strip().strip('"')
        url = url.strip().strip('"')

        if not title or not url:
            continue

        rows.append({"title": title, "url": url})

    df = pd.DataFrame(rows, columns=["title", "url"])

    if df.empty:
        st.warning("The video list is empty. Add at least one YouTube URL or video ID to videos.csv.")
        st.stop()

    df["video_id"] = df["url"].map(extract_video_id)
    df = df.dropna(subset=["video_id"]).copy()
    df["title"] = df["title"].fillna("")
    df["video_id"] = df["video_id"].astype(str)
    df = df.drop_duplicates(subset=["video_id"], keep="first")
    return df[["title", "url", "video_id"]].reset_index(drop=True)


def fetch_video_metadata(video_ids: list[str]) -> pd.DataFrame:
    if not video_ids:
        return pd.DataFrame(columns=["video_id", "title", "viewCount", "likeCount", "commentCount"])

    service = build("youtube", "v3", developerKey=API_KEY)
    results = []

    for index in range(0, len(video_ids), 50):
        batch = video_ids[index : index + 50]
        response = (
            service.videos()
            .list(
                part="snippet,statistics",
                id=",".join(batch),
            )
            .execute()
        )

        for item in response.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            results.append(
                {
                    "video_id": item.get("id"),
                    "title": snippet.get("title") or "Untitled video",
                    "viewCount": int(stats.get("viewCount", 0) or 0),
                    "likeCount": int(stats.get("likeCount", 0) or 0),
                    "commentCount": int(stats.get("commentCount", 0) or 0),
                }
            )

    return pd.DataFrame(results)


st.set_page_config(page_title="YouTube Views Dashboard", page_icon="📊", layout="wide")

st_autorefresh(interval=60000, key="youtube_dashboard_refresh")

st.markdown(
    """
    <style>
    :root {
        --etica-magenta: #c51b82;
        --etica-magenta-dark: #9e1468;
        --etica-ink: #292929;
        --etica-muted: #6b6b6b;
        --etica-border: #eadde5;
    }
    .stApp {
        background: linear-gradient(180deg, #ffffff 0%, #fffafd 55%, #f8f5f7 100%);
        color: var(--etica-ink);
    }
    h1, h2, h3 {
        color: var(--etica-ink) !important;
        letter-spacing: 0 !important;
    }
    h1 {
        font-weight: 750 !important;
    }
    [data-testid="stCaptionContainer"] {
        color: var(--etica-muted);
    }
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid var(--etica-border);
        border-radius: 10px;
        padding: 0.8rem 1rem;
        box-shadow: 0 5px 18px rgba(75, 34, 58, 0.05);
    }
    [data-testid="stMetricLabel"] {
        color: var(--etica-muted);
    }
    [data-testid="stMetricValue"] {
        color: var(--etica-magenta-dark);
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--etica-border);
        border-radius: 10px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("YouTube Views Dashboard")
st.caption("Combined view count across your tracked videos. The dashboard refreshes automatically every minute.")

if not API_KEY:
    st.warning(
        "No YouTube Data API key was found. Add YOUTUBE_API_KEY to a .env file in the same folder as this app and restart the dashboard."
    )
    st.code("YOUTUBE_API_KEY=your_api_key_here")
    st.stop()

video_df = load_video_list(VIDEO_FILE)

if video_df.empty:
    st.warning("No valid YouTube video IDs were found in videos.csv.")
    st.stop()

with st.spinner("Fetching the latest YouTube stats..."):
    try:
        stats_df = fetch_video_metadata(video_df["video_id"].tolist())
    except HttpError as exc:
        st.error(f"YouTube API request failed: {exc}")
        st.stop()

if stats_df.empty:
    st.warning("No statistics were returned for the videos in your list.")
    st.stop()

merged_df = video_df[["video_id", "title"]].merge(stats_df, on="video_id", how="left")
merged_df["title_x"] = merged_df["title_x"].fillna(merged_df["title_y"])
merged_df = merged_df.rename(columns={"title_x": "title"}).drop(columns=["title_y"], errors="ignore")
merged_df["viewCount"] = merged_df["viewCount"].fillna(0).astype(int)
merged_df["likeCount"] = merged_df["likeCount"].fillna(0).astype(int)
merged_df["commentCount"] = merged_df["commentCount"].fillna(0).astype(int)
merged_df = merged_df.sort_values("viewCount", ascending=False).reset_index(drop=True)

combined_views = int(merged_df["viewCount"].sum())
avg_views = int(merged_df["viewCount"].mean()) if not merged_df.empty else 0
highest_video = merged_df.iloc[0] if not merged_df.empty else None

if "last_total_views" not in st.session_state:
    st.session_state.last_total_views = combined_views

previous_total_views = int(st.session_state.last_total_views)
current_total_views = int(combined_views)
start_total_views = previous_total_views
st.session_state.last_total_views = current_total_views

st_html(
    f"""
    <style>
    .big-metric-wrapper {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        padding: 1.2rem 1rem 0.8rem;
        margin: 0.5rem auto 1.5rem;
        background: linear-gradient(135deg, rgba(197, 27, 130, 0.12), rgba(255, 250, 253, 0.96));
        border: 1px solid rgba(197, 27, 130, 0.24);
        border-radius: 12px;
        max-width: 900px;
        animation: riseIn 0.7s ease-out;
        box-shadow: 0 12px 30px rgba(101, 26, 72, 0.08);
    }}
    .big-metric-label {{
        font-size: 0.9rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #7b536b;
        margin-bottom: 0.25rem;
    }}
    .big-metric-value {{
        font-size: clamp(2.5rem, 5vw, 5rem);
        font-weight: 800;
        line-height: 1.1;
        color: #a8146c;
        text-shadow: 0 0 18px rgba(197, 27, 130, 0.20);
    }}
    @keyframes riseIn {{
        from {{ opacity: 0; transform: translateY(12px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    </style>
    <div class="big-metric-wrapper">
        <div class="big-metric-label">Total Views</div>
        <div id="rolling-total-views" class="big-metric-value" data-start="{start_total_views}" data-end="{current_total_views}">0</div>
    </div>
    <script>
    const el = document.getElementById('rolling-total-views');
    const start = Number(el.dataset.start || 0);
    const end = Number(el.dataset.end || 0);
    const duration = 1400;
    const startTime = performance.now();

    function updateCounter(now) {{
        const progress = Math.min((now - startTime) / duration, 1);
        const current = Math.round(start + (end - start) * progress);
        el.textContent = new Intl.NumberFormat('en-US').format(current);
        if (progress < 1) {{
            requestAnimationFrame(updateCounter);
        }} else {{
            el.textContent = new Intl.NumberFormat('en-US').format(end);
        }}
    }}

    requestAnimationFrame(updateCounter);
    </script>
    """,
    height=220,
    scrolling=False,
)

summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
summary_col1.metric("Average per video", f"{avg_views:,}")
summary_col2.metric("Videos tracked", f"{len(merged_df):,}")
summary_col3.metric(
    "Top video",
    (
        highest_video["title"][:20] + "..."
        if highest_video is not None and len(highest_video["title"]) > 20
        else (highest_video["title"] if highest_video is not None else "N/A")
    ),
)
summary_col4.metric(
    "Last update",
    pd.Timestamp.now(tz="UTC").tz_convert("Asia/Kolkata").strftime("%H:%M IST")
)
st.subheader("Top performing videos")
chart_df = merged_df[["title", "viewCount"]].head(10).copy()
chart_df = chart_df.sort_values("viewCount", ascending=False)
chart_df["short_title"] = chart_df["title"].str.slice(0, 28).where(
    chart_df["title"].str.len() <= 28,
    chart_df["title"].str.slice(0, 28) + "...",
)

chart = (
    alt.Chart(chart_df)
    .mark_bar(color="#c51b82", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X("short_title:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-35, labelColor="#4b3543")),
        y=alt.Y("viewCount:Q", title="Views", axis=alt.Axis(format=",.0f", labelColor="#6b6b6b", titleColor="#6b6b6b")),
        tooltip=[
            alt.Tooltip("title:N", title="Video"),
            alt.Tooltip("viewCount:Q", title="Views", format=",.0f"),
        ],
    )
    .properties(height=360)
    .configure(background="#fffafd")
    .configure_view(stroke="#eadde5", fill="#fffafd")
    .configure_axis(gridColor="#f0e5eb", domainColor="#eadde5", labelColor="#6b5360", titleColor="#6b5360")
)
st.altair_chart(chart, use_container_width=True)

st.subheader("Video breakdown")

table_rows = "".join(
    f"""
    <tr>
        <td>{escape(str(row.title))}</td>
        <td>{int(row.viewCount):,}</td>
        <td>{int(row.likeCount):,}</td>
        <td>{int(row.commentCount):,}</td>
    </tr>
    """
    for row in merged_df.itertuples(index=False)
)
st.markdown(
    f"""
    <style>
    .etica-table-wrap {{
        overflow-x: auto;
        border: 1px solid #eadde5;
        border-radius: 10px;
        background: #fffafd;
        box-shadow: 0 5px 18px rgba(75, 34, 58, 0.05);
    }}
    .etica-table {{
        width: 100%;
        border-collapse: collapse;
        color: #292929;
        font-size: 0.92rem;
    }}
    .etica-table th {{
        padding: 0.7rem 0.8rem;
        background: #c51b82;
        color: white;
        font-weight: 650;
        text-align: left;
    }}
    .etica-table td {{
        padding: 0.65rem 0.8rem;
        border-top: 1px solid #f0e5eb;
        background: #fffafd;
    }}
    .etica-table tr:nth-child(even) td {{
        background: #fdf4f9;
    }}
    .etica-table td:not(:first-child) {{
        text-align: right;
        color: #9e1468;
        font-variant-numeric: tabular-nums;
    }}
    </style>
    <div class="etica-table-wrap">
        <table class="etica-table">
            <thead>
                <tr><th>Video title</th><th>Views</th><th>Likes</th><th>Comments</th></tr>
            </thead>
            <tbody>{table_rows}</tbody>
        </table>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption(
    f"Last refreshed: {pd.Timestamp.now(tz='UTC').tz_convert('Asia/Kolkata').strftime('%Y-%m-%d %H:%M:%S IST')}"
)
if highest_video is not None:
    st.success(f"Leading video: {highest_video['title']} with {highest_video['viewCount']:,} views.")
