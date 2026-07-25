"use client";

import { useEffect, useState } from "react";
import { authApi, Game } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Props = {
  fallbackGames: Game[];
};

export default function FeedSection({ fallbackGames }: Props) {
  const [feed, setFeed] = useState<Game[]>([]);
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    authApi.getMe()
      .then(() => {
        setIsLoggedIn(true);
        return authApi.getFeed();
      })
      .then((games) => { if (games.length > 0) setFeed(games); })
      .catch(() => setIsLoggedIn(false));
  }, []);

  return (
    <div className="space-y-10">
      {feed.length > 0 && (
        <section>
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="text-base font-semibold text-white">あなたへのおすすめ</h2>
            <span className="text-xs text-white/30">評価を増やすほど精度が上がります</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {feed.map((game) => (
              <div key={game.id} className="flex flex-col gap-1.5">
                <GameCard game={game} />
                {game.reason_tags && game.reason_tags.length > 0 && (
                  <p className="px-1 text-xs text-white/30">
                    {game.reason_tags.map((t) => t.name_ja ?? t.name).join("・")}が好きな人に
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {isLoggedIn === false && (
        <div className="rounded-xl border border-white/10 bg-white/5 px-5 py-4 text-sm text-white/50">
          <a
            href={`${API_URL}/auth/steam`}
            className="font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
          >
            Steam でログイン
          </a>
          すると、あなたのライブラリから音楽の好みを分析してパーソナルおすすめを表示します。
          <span className="mt-1 block text-xs text-white/25">
            パスワード不要 · Steam 公式認証 · ログインしなくても音楽で探索できます
          </span>
        </div>
      )}

      <section>
        <h2 className="mb-5 text-base font-semibold text-white">データベース収録タイトル</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {fallbackGames.map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>
      </section>
    </div>
  );
}
