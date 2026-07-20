"use client";

import { useEffect, useState } from "react";
import { authApi, Game } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

type Props = {
  fallbackGames: Game[];
};

export default function FeedSection({ fallbackGames }: Props) {
  const [feed, setFeed] = useState<Game[] | null>(null);

  useEffect(() => {
    authApi.getMe()
      .then(() => authApi.getFeed())
      .then((games) => {
        if (games.length > 0) setFeed(games);
      })
      .catch(() => {
        // 未ログインまたはフィードなし — fallback のまま
      });
  }, []);

  const games = feed ?? fallbackGames;
  const title = feed
    ? "あなたへのおすすめ"
    : "データベース収録タイトル";

  return (
    <section>
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
        {title}
      </h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {games.map((game) => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>
    </section>
  );
}
