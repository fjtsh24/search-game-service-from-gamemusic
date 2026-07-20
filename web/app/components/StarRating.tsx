"use client";

import { useState } from "react";
import { authApi } from "@/app/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Props = {
  gameId: string;
  initialRating?: number;
};

export default function StarRating({ gameId, initialRating }: Props) {
  const [rating, setRating] = useState(initialRating ?? 0);
  const [hover, setHover] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loginRequired, setLoginRequired] = useState(false);

  const handleRate = async (star: number) => {
    if (saving) return;
    setSaving(true);
    setLoginRequired(false);
    try {
      await authApi.rateGame(gameId, star);
      setRating(star);
    } catch {
      setLoginRequired(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            disabled={saving}
            onClick={() => handleRate(star)}
            onMouseEnter={() => setHover(star)}
            onMouseLeave={() => setHover(0)}
            aria-label={`${star} 星`}
            className={`text-2xl leading-none transition disabled:cursor-not-allowed ${
              star <= (hover || rating) ? "text-yellow-400" : "text-white/20"
            } hover:text-yellow-300`}
          >
            ★
          </button>
        ))}
      </div>
      {loginRequired && (
        <p className="text-xs text-white/50">
          <a
            href={`${API_URL}/auth/steam`}
            className="text-indigo-400 underline underline-offset-2 hover:text-indigo-300"
          >
            Steam でログイン
          </a>
          すると評価できます
        </p>
      )}
    </div>
  );
}
