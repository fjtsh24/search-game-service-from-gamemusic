"use client";

import { useState } from "react";
import { authApi } from "@/app/lib/api";

type Props = {
  gameId: string;
  initialRating?: number;
};

export default function StarRating({ gameId, initialRating }: Props) {
  const [rating, setRating] = useState(initialRating ?? 0);
  const [hover, setHover] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  const handleRate = async (star: number) => {
    if (saving) return;
    setSaving(true);
    setError(false);
    try {
      await authApi.rateGame(gameId, star);
      setRating(star);
    } catch {
      setError(true);
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
      {error && (
        <p className="text-xs text-red-400">
          ログインが必要です
        </p>
      )}
    </div>
  );
}
