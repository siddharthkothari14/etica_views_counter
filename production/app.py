import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
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
        background: linear-gradient(135deg, rgba(49, 130, 206, 0.14), rgba(99, 102, 241, 0.10));
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 18px;
        max-width: 900px;
        animation: riseIn 0.7s ease-out;
    }}
    .big-metric-label {{
        font-size: 0.9rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 0.25rem;
    }}
    .big-metric-value {{
        font-size: clamp(2.5rem, 5vw, 5rem);
        font-weight: 800;
        line-height: 1.1;
        color: #f8fafc;
        text-shadow: 0 0 18px rgba(96, 165, 250, 0.32);
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
chart_df = chart_df.sort_values("viewCount", ascending=True)
st.bar_chart(chart_df.set_index("title")["viewCount"])

st.subheader("Video breakdown")

st.dataframe(
    merged_df[["title", "viewCount", "likeCount", "commentCount"]].rename(
        columns={
            "title": "Video title",
            "viewCount": "Views",
            "likeCount": "Likes",
            "commentCount": "Comments",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    f"Last refreshed: {pd.Timestamp.now(tz='UTC').tz_convert('Asia/Kolkata').strftime('%Y-%m-%d %H:%M:%S IST')}"
)
if highest_video is not None:
    st.success(f"Leading video: {highest_video['title']} with {highest_video['viewCount']:,} views.")
