# YouTube Views Dashboard

This Streamlit dashboard tracks the combined view count for a list of YouTube videos and refreshes automatically every 5 minutes.

## Setup

1. Copy `.env.example` to `.env`.
2. Add your YouTube Data API key to `.env`.
3. Replace the rows in `videos.csv` with your own video URLs or IDs.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Run the dashboard:

```bash
streamlit run app.py
```

## Notes

- The app batches all video IDs into a single YouTube API request.
- With ~26 videos, a 5-minute refresh cycle is comfortably within YouTube API quota limits.
- The dashboard shows total views, per-video breakdown, and a top videos chart.
