// Agent API base URL. Set this to your Hugging Face Space / Render URL before deploying to Vercel.
// Example: "https://your-team-dealdesk.hf.space"
window.DEALDESK_API = (location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:")
  ? "http://localhost:8000"
  : "https://YOUR-SPACE-NAME.hf.space";
