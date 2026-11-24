// Agent API base URL (Render). Local pages use the local backend.
// Live API: https://dealdesk-api-hyz7.onrender.com
window.DEALDESK_API = (location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:")
  ? "http://localhost:8000"
  : "https://dealdesk-api-hyz7.onrender.com";
