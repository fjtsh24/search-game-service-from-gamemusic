import { notFound } from "next/navigation";
import Link from "next/link";
import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";
import YouTubePlayer from "@/app/components/YouTubePlayer";
import StarRating from "@/app/components/StarRating";

export default async function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const [game, similar] = await Promise.all([
    api.getGame(id).catch(() => null),
    api.getSimilarGames(id).catch(() => []),
  ]);

  if (!game) notFound();

  const tags = game.game_tags?.map((gt) => gt.mood_tags).filter(Boolean) ?? [];
  const composers = game.tracks
    ?.flatMap((t) => t.track_composers?.map((tc) => tc.composers) ?? [])
    .filter(Boolean)
    .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i) ?? [];

  return (
    <div className="space-y-10">
      {/* ヘッダー */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <div className="flex-1 space-y-3">
          <h1 className="text-3xl font-bold leading-tight">{game.title}</h1>
          {game.title_ja && <p className="text-white/50">{game.title_ja}</p>}
          {game.release_year && (
            <p className="text-sm text-white/40">{game.release_year}年</p>
          )}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <Link
                  key={tag.id}
                  href={`/tags/${tag.id}`}
                  className="rounded-full border border-white/20 px-3 py-1 text-xs text-white/70 hover:border-white/40 hover:text-white"
                >
                  {tag.name_ja ?? tag.name}
                </Link>
              ))}
            </div>
          )}
          {composers.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {composers.map((c) => (
                <Link
                  key={c.id}
                  href={`/composers/${c.id}`}
                  className="text-sm text-indigo-400 hover:text-indigo-300"
                >
                  {c.name}
                </Link>
              ))}
            </div>
          )}
          <StarRating gameId={id} />

          {game.steam_app_id && (
            <a
              href={`https://store.steampowered.com/app/${game.steam_app_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
            >
              Steam で見る →
            </a>
          )}
        </div>
      </div>

      {/* YouTube プレーヤー */}
      {game.tracks?.length > 0 && (
        <YouTubePlayer tracks={game.tracks} gameTitle={game.title} />
      )}

      {/* 類似ゲーム */}
      {similar.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            音楽的に似たゲーム
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
            {similar.map((g) => (
              <GameCard key={g.id} game={g} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
