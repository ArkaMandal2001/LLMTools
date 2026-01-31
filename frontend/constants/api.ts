// Backend API endpoints
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "https://llmtoolsbackend-production.up.railway.app";

export const API_ENDPOINTS = {
  // Auth endpoints
  AUTH: {
    GOOGLE_LOGIN: `${API_BASE_URL}/auth/google/login`,
    GOOGLE_CALLBACK: `${API_BASE_URL}/auth/google/callback`,
  },
};

// Helper to get WebSocket URL for realtime endpoint
export const getRealtimeWebSocketUrl = (token: string, timezone: string): string => {
  const wsProtocol = API_BASE_URL.startsWith("https") ? "wss" : "ws";
  const wsHost = API_BASE_URL.replace("http://", "").replace("https://", "");
  return `${wsProtocol}://${wsHost}/realtime?token=${encodeURIComponent(token)}&timezone=${encodeURIComponent(timezone)}`;
};

export default API_ENDPOINTS;
