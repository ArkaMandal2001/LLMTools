"use client";

import { useState, useEffect } from "react";
import SignIn from "@/components/SignIn";
import ChatRealtime from "@/components/ChatRealtime";

export default function Home() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Check if user is logged in on mount
  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    setIsLoggedIn(!!token);
    setIsLoading(false);

    // Check for token in URL (from OAuth callback)
    const params = new URLSearchParams(window.location.search);
    const authToken = params.get("token");

    if (authToken) {
      localStorage.setItem("auth_token", authToken);
      setIsLoggedIn(true);
      // Clean up URL
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    setIsLoggedIn(false);
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
        <div className="text-center">
          <div className="mb-4 inline-block h-12 w-12 animate-spin rounded-full border-4 border-gray-300 border-t-blue-500"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  return isLoggedIn ? (
    <ChatRealtime onLogout={handleLogout} />
  ) : (
    <SignIn onSignInSuccess={() => setIsLoggedIn(true)} />
  );
}
