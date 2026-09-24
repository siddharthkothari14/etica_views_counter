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


def format_duration(duration: str) -> str:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return "N/A"

    hours, minutes, seconds = (int(value or 0) for value in match.groups())
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


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


@st.cache_data(ttl=300, show_spinner=False)
def fetch_video_metadata(video_ids: list[str]) -> pd.DataFrame:
    if not video_ids:
        return pd.DataFrame(
            columns=[
                "video_id",
                "title",
                "publishedAt",
                "duration",
                "thumbnailUrl",
                "viewCount",
                "likeCount",
                "commentCount",
            ]
        )

    service = build("youtube", "v3", developerKey=API_KEY)
    results = []

    for index in range(0, len(video_ids), 50):
        batch = video_ids[index : index + 50]
        response = (
            service.videos()
            .list(
                part="snippet,statistics,contentDetails",
                id=",".join(batch),
            )
            .execute()
        )

        for item in response.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            thumbnails = snippet.get("thumbnails", {})
            thumbnail = thumbnails.get("maxres") or thumbnails.get("high") or thumbnails.get("medium") or {}
            results.append(
                {
                    "video_id": item.get("id"),
                    "title": snippet.get("title") or "Untitled video",
                    "publishedAt": snippet.get("publishedAt"),
                    "duration": format_duration(content_details.get("duration", "")),
                    "thumbnailUrl": thumbnail.get("url"),
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

merged_df = video_df[["video_id", "title", "url"]].merge(stats_df, on="video_id", how="left")
merged_df["title_x"] = merged_df["title_x"].fillna(merged_df["title_y"])
merged_df = merged_df.rename(columns={"title_x": "title"}).drop(columns=["title_y"], errors="ignore")
merged_df["viewCount"] = merged_df["viewCount"].fillna(0).astype(int)
merged_df["likeCount"] = merged_df["likeCount"].fillna(0).astype(int)
merged_df["commentCount"] = merged_df["commentCount"].fillna(0).astype(int)
merged_df["publishedAt"] = pd.to_datetime(merged_df["publishedAt"], utc=True, errors="coerce")
merged_df["releaseDate"] = merged_df["publishedAt"].dt.strftime("%d %b %Y").fillna("N/A")
merged_df["duration"] = merged_df["duration"].fillna("N/A")
merged_df = merged_df.sort_values("viewCount", ascending=False).reset_index(drop=True)


def render_video_analysis_page(video: pd.Series, rank: int, total_videos: int) -> None:
    """Render the public-data analysis page for one video."""
    st.title("Video Analysis")
    if st.button("← Back to dashboard"):
        st.query_params.clear()
        st.rerun()

    st.header(video["title"])
    st.markdown(f"[Open video on YouTube]({video['url']})")

    thumbnail_url = video.get("thumbnailUrl") or f"https://i.ytimg.com/vi/{video['video_id']}/hqdefault.jpg"
    thumbnail_col, _ = st.columns([1, 2])
    with thumbnail_col:
        st.image(thumbnail_url, caption="Video thumbnail", use_container_width=True)

    views = int(video["viewCount"])
    likes = int(video["likeCount"])
    comments = int(video["commentCount"])
    published_at = video["publishedAt"]
    age_days = max((pd.Timestamp.now(tz="UTC") - published_at).days, 1) if pd.notna(published_at) else None
    engagement_rate = ((likes + comments) / views * 100) if views else 0
    like_rate = (likes / views * 100) if views else 0
    comment_rate = (comments / views * 100) if views else 0

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Views", f"{views:,}")
    metric_col2.metric("Likes", f"{likes:,}")
    metric_col3.metric("Comments", f"{comments:,}")
    metric_col4.metric("Engagement rate", f"{engagement_rate:.2f}%")

    metric_col5, metric_col6, metric_col7, metric_col8 = st.columns(4)
    metric_col5.metric("Like rate", f"{like_rate:.2f}%")
    metric_col6.metric("Comment rate", f"{comment_rate:.2f}%")
    metric_col7.metric("Views per day", f"{views / age_days:,.0f}" if age_days else "N/A")
    metric_col8.metric("List rank", f"#{rank} of {total_videos}")

    st.subheader("Video details")
    detail_col1, detail_col2, detail_col3 = st.columns(3)
    detail_col1.write(f"**Published:** {video['releaseDate']}")
    detail_col2.write(f"**Duration:** {video['duration']}")
    detail_col3.write(f"**Age:** {age_days:,} days" if age_days else "**Age:** N/A")

    chart_df = pd.DataFrame(
        {
            "Metric": ["Views", "Likes", "Comments"],
            "Count": [views, likes, comments],
        }
    )
    chart = (
        alt.Chart(chart_df)
        .mark_bar(color="#c51b82", cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
        .encode(
            x=alt.X("Metric:N", title=None),
            y=alt.Y("Count:Q", title="Count", axis=alt.Axis(format=",.0f")),
            tooltip=[alt.Tooltip("Metric:N"), alt.Tooltip("Count:Q", format=",.0f")],
        )
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True)

    st.subheader("Audience retention")
    st.info(
        "Audience-retention data is not available through the public YouTube Data API. "
        "It requires YouTube Analytics API OAuth access to the channel that owns this video."
    )


requested_video_id = st.query_params.get("video")
if requested_video_id:
    requested_video = merged_df.loc[merged_df["video_id"] == requested_video_id]
    if requested_video.empty:
        st.error("That video could not be found in the tracked video list.")
        if st.button("Back to dashboard"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    selected_video = requested_video.iloc[0]
    selected_rank = int(merged_df.index[merged_df["video_id"] == requested_video_id][0]) + 1
    render_video_analysis_page(selected_video, selected_rank, len(merged_df))
    st.stop()

st.title("YouTube Views Dashboard")
st.caption("Combined view count across your tracked videos. The dashboard refreshes automatically every minute.")

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
chart_df = merged_df[["title", "publishedAt", "viewCount"]].dropna(subset=["publishedAt"]).copy()
chart_df = chart_df.sort_values("publishedAt")

chart = (
    alt.Chart(chart_df)
    .mark_line(color="#c51b82", point=alt.OverlayMarkDef(color="#9e1468", size=70))
    .encode(
        x=alt.X("publishedAt:T", title="Release date", axis=alt.Axis(format="%d %b %Y", labelAngle=-35, labelColor="#4b3543")),
        y=alt.Y("viewCount:Q", title="Views", axis=alt.Axis(format=",.0f", labelColor="#6b6b6b", titleColor="#6b6b6b")),
        tooltip=[
            alt.Tooltip("title:N", title="Video"),
            alt.Tooltip("publishedAt:T", title="Released", format="%d %b %Y"),
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
st.caption("Select Analysis for a local breakdown using the statistics already fetched above.")

st.markdown(
    """
    <style>
    .video-row {
        border-top: 1px solid #f0e5eb;
        padding: 0.35rem 0;
    }
    .video-title {
        color: #9e1468;
        font-weight: 650;
        text-decoration: none;
    }
    .video-title:hover {
        color: #c51b82;
        text-decoration: underline;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

header_title, header_release, header_duration, header_views, header_likes, header_comments, header_action = st.columns(
    [3.5, 1.2, 1, 1, 1, 1, 1.25]
)
header_title.markdown("**Video title**")
header_release.markdown("**Release date**")
header_duration.markdown("**Duration**")
header_views.markdown("**Views**")
header_likes.markdown("**Likes**")
header_comments.markdown("**Comments**")

for row in merged_df.itertuples(index=False):
    title_col, release_col, duration_col, views_col, likes_col, comments_col, action_col = st.columns(
        [3.5, 1.2, 1, 1, 1, 1, 1.25]
    )
    title_col.markdown(
        f'<a class="video-title" href="{escape(str(row.url), quote=True)}" target="_blank" rel="noopener noreferrer">{escape(str(row.title))}</a>',
        unsafe_allow_html=True,
    )
    release_col.write(row.releaseDate)
    duration_col.write(row.duration)
    views_col.write(f"{int(row.viewCount):,}")
    likes_col.write(f"{int(row.likeCount):,}")
    comments_col.write(f"{int(row.commentCount):,}")
    if action_col.button("Analysis", key=f"analysis_{row.video_id}", use_container_width=True):
        st.query_params["video"] = row.video_id
        st.rerun()

st.caption(
    f"Last refreshed: {pd.Timestamp.now(tz='UTC').tz_convert('Asia/Kolkata').strftime('%Y-%m-%d %H:%M:%S IST')}"
)
if highest_video is not None:
    st.success(f"Leading video: {highest_video['title']} with {highest_video['viewCount']:,} views.")
