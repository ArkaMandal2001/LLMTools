"use client";

import { useState, useRef, useEffect } from "react";
import { getRealtimeWebSocketUrl } from "@/constants/api";

interface ChatProps {
  onLogout: () => void;
}

export default function ChatRealtime({ onLogout }: ChatProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const isListeningRef = useRef(false);
  const currentResponseIdRef = useRef<string | null>(null);

  // Initialize WebSocket connection
  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    if (!token) {
      setError("Not authenticated");
      return;
    }

    // Get client timezone
    const clientTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Get timezone offset in format "+HH:MM" or "-HH:MM"
    const now = new Date();
    const offsetMinutes = -now.getTimezoneOffset(); // Negative because getTimezoneOffset returns opposite
    const offsetHours = Math.floor(Math.abs(offsetMinutes) / 60);
    const offsetMins = Math.abs(offsetMinutes) % 60;
    const offsetSign = offsetMinutes >= 0 ? "+" : "-";
    const timezoneOffset = `${offsetSign}${String(offsetHours).padStart(2, "0")}:${String(offsetMins).padStart(2, "0")}`;
    
    console.log("[REALTIME] Client timezone:", clientTimezone, "offset:", timezoneOffset);
    
    // Get WebSocket URL from constants
    const wsUrl = getRealtimeWebSocketUrl(token, timezoneOffset);
    
    console.log("[REALTIME] Connecting to:", wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("[REALTIME] WebSocket connected - state:", ws.readyState, "(should be 1=OPEN)");
      setIsConnected(true);
      setError(null);
      // Force a re-render to update button state
      // If we're already listening, the audio processor will now start sending
      if (isListeningRef.current) {
        console.log("[REALTIME] WebSocket opened while listening - audio will now be sent");
      }
    };

    ws.onmessage = async (event) => {
      try {
        // Try to parse as JSON first
        if (typeof event.data === 'string') {
          const data = JSON.parse(event.data);
          
          // Handle connection update
          if (data.type === "connection.update" && data.status === "connected") {
            console.log("[REALTIME] Connection confirmed by server. WebSocket state:", wsRef.current?.readyState);
            setIsConnected(true);
            setError(null);
            // If we're already listening, the audio processor will now start sending
            if (isListeningRef.current) {
              console.log("[REALTIME] Server confirmed connection while listening - audio will now be sent");
            }
            return;
          }
          
          // Log response-related events for debugging
          if (data.type && (data.type.includes("response") || data.type.includes("output") || data.type.includes("function"))) {
            console.log(`[REALTIME] Received ${data.type} event:`, data);
          }
          
          await handleRealtimeEvent(data);
        }
      } catch (e) {
        console.error("[REALTIME] Error handling message:", e);
      }
    };

    ws.onerror = (error) => {
      console.error("[REALTIME] WebSocket error:", error);
      console.error("[REALTIME] WebSocket state:", ws.readyState);
      setError(`Connection error: ${ws.readyState === WebSocket.CLOSED ? 'Connection closed' : 'Connection failed'}`);
    };

    ws.onclose = (event) => {
      console.log("[REALTIME] WebSocket disconnected", event.code, event.reason);
      setIsConnected(false);
      if (event.code !== 1000) {
        setError(`Connection closed: ${event.reason || 'Unknown error'}`);
      }
    };

    wsRef.current = ws;

    return () => {
      isListeningRef.current = false;
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close(1000, "Component unmounting");
      }
      stopRecording();
      stopAudioPlayback();
    };
  }, []);

  const handleRealtimeEvent = async (event: any) => {
    const eventType = event.type;
    
    // Log all events for debugging
    if (eventType.includes("response") || eventType.includes("output")) {
      console.log(`[REALTIME] Received event: ${eventType}`, event);
    }

    switch (eventType) {
      case "conversation.item.input_audio_transcription.completed":
        // User's speech was transcribed - don't display, audio-only interface
        break;

      case "response.created":
        // Track new response
        currentResponseIdRef.current = event.response?.id || null;
        setIsLoading(true);
        setIsSpeaking(true);
        break;

      case "response.audio.delta":
        // Audio chunk from assistant (base64 encoded PCM16)
        if (event.delta) {
          try {
            console.log("[REALTIME] Received audio delta, length:", event.delta.length);
            const audioData = base64ToArrayBuffer(event.delta);
            console.log("[REALTIME] Decoded audio data, size:", audioData.byteLength, "bytes");
            audioQueueRef.current.push(audioData);
            // Trigger playback - it will handle the queue properly
            playAudioQueue();
          } catch (e) {
            console.error("[REALTIME] Error processing audio delta:", e);
          }
        } else {
          console.warn("[REALTIME] response.audio.delta event has no delta field");
        }
        break;
      
      case "response.audio.done":
        // Audio streaming complete - but don't stop speaking yet
        // Wait for response.done to ensure all chunks are processed
        console.log("[REALTIME] Audio streaming done, queue length:", audioQueueRef.current.length);
        break;

      case "response.output_item.done":
        // Output item completed - might contain tool results or response content
        console.log("[REALTIME] Output item done:", event);
        break;

      case "response.done":
        setIsLoading(false);
        // Don't set isSpeaking(false) here - let the audio queue finish playing
        // The playAudioQueue function will set it to false when done
        // Wait a bit to ensure all audio chunks are processed
        setTimeout(() => {
          // If queue is empty and not playing, we're done
          if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
            setIsSpeaking(false);
          }
        }, 500);
        break;

      case "error":
        setError(event.error?.message || "An error occurred");
        setIsLoading(false);
        break;

      default:
        // Log unhandled events for debugging
        if (eventType.includes("response") || eventType.includes("output") || eventType.includes("function")) {
          console.log(`[REALTIME] Unhandled event type: ${eventType}`, event);
        }
        break;
    }
  };

  const playAudioQueue = async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) {
      if (isPlayingRef.current) {
        console.log("[REALTIME] Audio already playing, queue length:", audioQueueRef.current.length);
      }
      return;
    }

    console.log("[REALTIME] Starting audio playback, queue length:", audioQueueRef.current.length);
    isPlayingRef.current = true;
    setIsSpeaking(true);

    try {
      // Create AudioContext for playback (24kHz sample rate for Realtime API PCM16)
      if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
        console.log("[REALTIME] Creating new AudioContext");
        audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({
          sampleRate: 24000,
        });
      }
      
      // Resume context if suspended
      if (audioContextRef.current.state === 'suspended') {
        console.log("[REALTIME] Resuming suspended AudioContext");
        await audioContextRef.current.resume();
      }

      console.log("[REALTIME] AudioContext state:", audioContextRef.current.state);

      // Process all chunks in the queue, but allow new chunks to be added
      // Use a local copy to avoid issues with concurrent modifications
      while (audioQueueRef.current.length > 0) {
        const audioData = audioQueueRef.current.shift()!;
        console.log("[REALTIME] Playing audio chunk, size:", audioData.byteLength, "bytes, remaining in queue:", audioQueueRef.current.length);
        
        // Convert Int16 PCM to Float32 for Web Audio API
        const pcmData = new Int16Array(audioData);
        const float32Data = new Float32Array(pcmData.length);
        for (let i = 0; i < pcmData.length; i++) {
          float32Data[i] = pcmData[i] / 32768.0;
        }
        
        // Create audio buffer (24kHz, mono)
        const audioBuffer = audioContextRef.current.createBuffer(1, float32Data.length, 24000);
        audioBuffer.getChannelData(0).set(float32Data);
        
        // Play audio
        const source = audioContextRef.current.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContextRef.current.destination);

        await new Promise<void>((resolve) => {
          source.onended = () => {
            console.log("[REALTIME] Audio chunk finished playing");
            resolve();
          };
          source.start();
          console.log("[REALTIME] Audio chunk started playing");
        });
      }
      
      // After processing current queue, check if more chunks arrived
      // If so, continue playing (this handles late-arriving chunks)
      if (audioQueueRef.current.length > 0) {
        console.log("[REALTIME] More audio chunks arrived, continuing playback");
        // Recursively call playAudioQueue, but reset the flag first so it can run again
        isPlayingRef.current = false;
        playAudioQueue();
        return; // Exit early, new call will handle remaining chunks
      }
      
      console.log("[REALTIME] Finished playing all audio chunks in queue");
    } catch (error) {
      console.error("[REALTIME] Audio playback error:", error);
    } finally {
      isPlayingRef.current = false;
      setIsSpeaking(false);
    }
  };

  const stopAudioPlayback = () => {
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    setIsSpeaking(false);
  };

  const base64ToArrayBuffer = (base64: string): ArrayBuffer => {
    const binaryString = window.atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  };

  const startRecording = async () => {
    try {
      console.log("[REALTIME] Requesting microphone access...");
      // Get user media stream
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: 1,
          sampleRate: 24000, // Realtime API expects 24kHz
          echoCancellation: true,
          noiseSuppression: true,
        }
      });
      
      console.log("[REALTIME] Microphone access granted, stream:", stream.id);
      mediaStreamRef.current = stream;
      
      // Create AudioContext for processing
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 24000,
      });
      audioContextRef.current = audioContext;
      
      // Resume context if suspended (required by some browsers)
      if (audioContext.state === 'suspended') {
        await audioContext.resume();
        console.log("[REALTIME] AudioContext resumed");
      }
      
      console.log("[REALTIME] AudioContext state:", audioContext.state, "sampleRate:", audioContext.sampleRate);
      
      // Create source from stream
      const source = audioContext.createMediaStreamSource(stream);
      
      // Create script processor for real-time audio processing
      // Buffer size: 4096 samples = ~170ms at 24kHz
      const scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
      
      let chunkCount = 0;
      scriptProcessor.onaudioprocess = (event) => {
        // Use ref to check listening state (more reliable than state variable)
        if (!isListeningRef.current) {
          return;
        }
        
        // Check WebSocket state - must be OPEN (1) to send data
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          // Don't log every time to avoid spam, but log occasionally
          if (chunkCount === 0 || chunkCount % 100 === 0) {
            console.warn(`[REALTIME] WebSocket not ready (chunk #${chunkCount}), state: ${wsRef.current?.readyState} (0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED)`);
          }
          return; // Don't process audio if WebSocket isn't ready
        }
        
        chunkCount++;
        const inputBuffer = event.inputBuffer.getChannelData(0);
        
        // Check if we're actually getting audio data (non-zero values)
        const hasAudio = inputBuffer.some(sample => Math.abs(sample) > 0.001);
        
        // Log first few chunks to verify audio processing is working
        if (chunkCount <= 5 || chunkCount % 100 === 0) {
          const maxAmplitude = Math.max(...Array.from(inputBuffer).map(Math.abs));
          console.log(`[REALTIME] Audio chunk #${chunkCount}, samples: ${inputBuffer.length}, max amplitude: ${maxAmplitude.toFixed(4)}, hasAudio: ${hasAudio}`);
        }
        
        // Convert Float32Array to Int16Array (PCM format)
        const pcmData = new Int16Array(inputBuffer.length);
        for (let i = 0; i < inputBuffer.length; i++) {
          // Clamp and convert to 16-bit integer
          const s = Math.max(-1, Math.min(1, inputBuffer[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        // Send binary audio data directly to backend
        try {
          wsRef.current.send(pcmData.buffer);
          // Log first few sends to verify
          if (chunkCount <= 5 || chunkCount % 100 === 0) {
            console.log(`[REALTIME] ✓ Sent audio chunk #${chunkCount} to backend: ${pcmData.length} samples (${pcmData.length * 2} bytes)`);
          }
        } catch (error) {
          console.error("[REALTIME] Error sending audio:", error);
        }
      };
      
      // Connect nodes
      source.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);
      
      scriptProcessorRef.current = scriptProcessor;
      isListeningRef.current = true;
      setIsListening(true);
      console.log("[REALTIME] Started continuous audio streaming - scriptProcessor connected");
    } catch (error) {
      console.error("[REALTIME] Recording error:", error);
      setError(`Failed to start recording: ${error}`);
    }
  };

  const stopRecording = () => {
    // Update ref first to stop audio processing immediately
    isListeningRef.current = false;
    
    // Disconnect audio nodes
    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }
    
    // Stop media stream tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    
    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(console.error);
      audioContextRef.current = null;
    }
    
    setIsListening(false);
    console.log("[REALTIME] Stopped audio streaming");
  };

  const handleToggleRecording = () => {
    // Check connection state
    if (!isConnected) {
      setError("Not connected to server");
      console.error("[REALTIME] Cannot start recording - not connected");
      return;
    }
    
    // Double-check WebSocket state for safety
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      const state = wsRef.current?.readyState ?? 'null';
      const stateNames = { 0: 'CONNECTING', 1: 'OPEN', 2: 'CLOSING', 3: 'CLOSED' };
      setError(`WebSocket not ready (state: ${state} = ${stateNames[state as keyof typeof stateNames]})`);
      console.error("[REALTIME] Cannot start recording - WebSocket not OPEN. State:", state);
      setIsConnected(false); // Update state to reflect actual connection status
      return;
    }
    
    if (isListening) {
      // Stop recording - Realtime API will automatically respond when it detects speech end
      console.log("[REALTIME] Stopping recording...");
      stopRecording();
    } else {
      // Start continuous recording - audio will stream continuously
      console.log("[REALTIME] Starting recording... WebSocket state:", wsRef.current.readyState, "(should be 1=OPEN)");
      startRecording();
    }
  };

  return (
    <div className="flex h-screen flex-col bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Calendar Chat (Realtime)
            </h1>
            <div className="flex items-center gap-2">
              <div
                className={`h-3 w-3 rounded-full ${
                  isConnected ? "bg-green-500" : "bg-red-500"
                }`}
              />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                {isConnected ? "Connected" : "Disconnected"}
              </span>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="rounded-lg bg-red-500 px-4 py-2 font-semibold text-white transition-colors hover:bg-red-600 dark:hover:bg-red-700"
          >
            Logout
          </button>
        </div>
      </div>

      {/* Messages Area - Audio only, no text display */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl space-y-4 flex items-center justify-center h-full">
          {isLoading && (
            <div className="flex justify-center">
              <div className="rounded-lg bg-white px-4 py-2 shadow-sm dark:bg-gray-700">
                <div className="flex space-x-2">
                  <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400"></div>
                  <div className="animation-delay-100 h-2 w-2 animate-bounce rounded-full bg-gray-400"></div>
                  <div className="animation-delay-200 h-2 w-2 animate-bounce rounded-full bg-gray-400"></div>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-lg bg-red-50 p-4 text-red-600 dark:bg-red-900 dark:text-red-200">
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 bg-white px-6 py-4 shadow-lg dark:border-gray-700 dark:bg-gray-800">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-center justify-center gap-4">
            <button
              onClick={handleToggleRecording}
              disabled={!isConnected || isLoading}
              className={`flex h-16 w-16 items-center justify-center rounded-full transition-all ${
                isListening
                  ? "bg-red-500 hover:bg-red-600 scale-110"
                  : "bg-blue-500 hover:bg-blue-600"
              } disabled:opacity-50 disabled:cursor-not-allowed`}
              title={
                !isConnected
                  ? "Waiting for connection..."
                  : isListening
                  ? "Click to stop recording"
                  : "Click to start recording"
              }
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-8 w-8 text-white"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {isListening ? (
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                ) : (
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                )}
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
            <div className="text-center">
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {isListening
                  ? "Listening... Click to stop"
                  : isSpeaking
                  ? "Speaking..."
                  : "Click to start conversation"}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
