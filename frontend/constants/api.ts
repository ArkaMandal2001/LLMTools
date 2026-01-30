// Backend API endpoints
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "https://oolsackend-arkatigps9522-1ju1urxk.leapcell.dev";

export const API_ENDPOINTS = {
  // Auth endpoints
  AUTH: {
    GOOGLE_LOGIN: `${API_BASE_URL}/auth/google/login`,
    GOOGLE_CALLBACK: `${API_BASE_URL}/auth/google/callback`,
  },
  // Chat endpoints
  CHAT: {
    SEND_MESSAGE: `${API_BASE_URL}/chat`,
  },
  // Health check
  HEALTH: `${API_BASE_URL}/health`,
};

export default API_ENDPOINTS;
