"use client";

import { useEffect, useState } from "react";
import { authApi, Game } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

type Props = {
  fallbackGames: Game[];
};

export default function FeedSection({ fallbackGames }: Props) {
  const [feed, setFeed] = useState<Game[] | null>(null);
  const [isPersonalized, setIsPersonalized] = useState(false);

  useEffect(() => {
    authApi.getMe()
      .then(() => authApi.getFeed())
      .then((games) => {
        if (games.length > 0) {
          setFeed(games);
          setIsPersonalized(true);
        }
      })
      .catch(() => {
        // 未ログインまたはフィードなし — fallback のまま
      });
  }, []);

  const games = feed ?? fallbackGames;

  return (
    <section>
      <div className="mb-5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-white">
          {isPersonalized ? "あなたへのおすすめ" : "データベース収録タイトル"}
        </h2>
        {isPersonalized && (
          <span className="text-xs text-white/30">評価を増やすほど精度が上がります</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {games.map((game) => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>
    </section>
  );
}
